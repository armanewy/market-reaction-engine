use crate::config::Config;
use crate::io::{ensure_dir, read_observations_path, rel, write_string};
use crate::model::{DomainCandidate, DomainObservation, GateDecision};
use crate::registry::{normalize_slug, Registry};
use crate::report::{discovery_report, intake_doc};
use crate::scoring::score_candidate;
use anyhow::Context;
use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone)]
pub struct RunOutput {
    pub candidates: Vec<DomainCandidate>,
    pub artifacts_dir: PathBuf,
    pub report_path: PathBuf,
    pub json_path: PathBuf,
    pub intake_dir: PathBuf,
}

pub fn run_scan(root: &Path, config: &Config) -> anyhow::Result<RunOutput> {
    let registry_path = rel(root, &config.registry.path);
    let registry = Registry::load_markdown(&registry_path)
        .with_context(|| format!("failed to load registry {}", registry_path.display()))?;
    let feedback_path = rel(root, &config.feedback.path);
    let feedback = load_feedback(&feedback_path)?;

    let mut observations = Vec::new();
    for feed in &config.feeds {
        if feed.kind.to_lowercase() != "jsonl"
            && feed.kind.to_lowercase() != "json"
            && feed.kind.to_lowercase() != "toml"
        {
            continue;
        }
        let feed_path = rel(root, &feed.path);
        if feed_path.exists() {
            observations.extend(
                read_observations_path(&feed_path)
                    .with_context(|| format!("failed to read feed {}", feed_path.display()))?,
            );
        }
    }

    let mut by_slug: BTreeMap<String, Vec<DomainObservation>> = BTreeMap::new();
    for mut obs in observations {
        obs.slug = normalize_slug(&obs.slug);
        if obs.slug.is_empty() {
            continue;
        }
        by_slug.entry(obs.slug.clone()).or_default().push(obs);
    }

    let mut candidates = Vec::new();
    for (slug, obs) in by_slug {
        let mut candidate = DomainCandidate::from_observations(slug.clone(), obs);
        candidate.registry_status = registry.get(&slug).cloned();
        candidate = score_candidate(candidate, config);
        apply_feedback_penalty(&mut candidate, feedback.get(&slug), config);
        candidates.push(candidate);
    }

    candidates.sort_by(|a, b| {
        b.score
            .total
            .cmp(&a.score.total)
            .then_with(|| a.slug.cmp(&b.slug))
    });

    let artifacts_dir = rel(root, &config.artifacts_dir);
    let intake_dir = rel(root, &config.intake_dir);
    ensure_dir(&artifacts_dir)?;
    ensure_dir(&intake_dir)?;

    let report_path = artifacts_dir.join("domain_discovery_report.md");
    let json_path = artifacts_dir.join("domain_candidates.json");

    let report = discovery_report(&candidates);
    write_string(&report_path, &report)?;
    write_string(&json_path, &serde_json::to_string_pretty(&candidates)?)?;

    for candidate in &candidates {
        if should_write_intake(candidate) {
            let path = intake_dir.join(format!("{}.md", candidate.slug));
            write_string(&path, &intake_doc(candidate))?;
        }
    }

    Ok(RunOutput {
        candidates,
        artifacts_dir,
        report_path,
        json_path,
        intake_dir,
    })
}

fn should_write_intake(candidate: &DomainCandidate) -> bool {
    matches!(
        candidate.gate,
        crate::model::GateDecision::FullLifecycle
            | crate::model::GateDecision::FeasibilityOnly
            | crate::model::GateDecision::MonitorOnly
    )
}

#[derive(Debug, Clone, serde::Deserialize)]
struct FeedbackRecord {
    domain: String,
    status: String,
    source_rows: Option<u64>,
    audited_true_positive_rows: Option<u64>,
}

fn load_feedback(path: &Path) -> anyhow::Result<BTreeMap<String, FeedbackRecord>> {
    if !path.exists() {
        return Ok(BTreeMap::new());
    }
    let text = fs::read_to_string(path)
        .with_context(|| format!("failed to read feedback {}", path.display()))?;
    let mut feedback = BTreeMap::new();
    for line in text.lines().filter(|line| !line.trim().is_empty()) {
        let record: FeedbackRecord = serde_json::from_str(line)
            .with_context(|| format!("failed to parse feedback row in {}", path.display()))?;
        feedback.insert(normalize_slug(&record.domain), record);
    }
    Ok(feedback)
}

fn apply_feedback_penalty(
    candidate: &mut DomainCandidate,
    feedback: Option<&FeedbackRecord>,
    config: &Config,
) {
    let Some(record) = feedback else {
        return;
    };
    let source_rows = record.source_rows.unwrap_or(0);
    let true_positive_rows = record.audited_true_positive_rows.unwrap_or(0);
    if source_rows < config.feedback.min_source_rows_for_low_yield {
        return;
    }
    let positive_yield = if source_rows == 0 {
        0.0
    } else {
        true_positive_rows as f64 / source_rows as f64
    };
    if positive_yield > config.feedback.max_positive_yield_for_penalty {
        return;
    }

    candidate.score.sample_size_likelihood = 0;
    candidate.score.parser_audit_feasibility = 0;
    candidate.score.recalc_total();
    if matches!(candidate.gate, GateDecision::FullLifecycle) {
        candidate.gate = GateDecision::FeasibilityOnly;
    }
    candidate.warnings.push(format!(
        "historical feedback: low true-positive yield after prior `{}` run ({} true positives / {} source rows)",
        record.status, true_positive_rows, source_rows
    ));
}

pub fn candidate_from_observations(
    observations: Vec<DomainObservation>,
    slug_filter: Option<&str>,
) -> anyhow::Result<DomainCandidate> {
    anyhow::ensure!(
        !observations.is_empty(),
        "candidate input had no observations"
    );

    let requested_slug = slug_filter.map(normalize_slug);
    let mut by_slug: BTreeMap<String, Vec<DomainObservation>> = BTreeMap::new();

    for mut obs in observations {
        obs.slug = normalize_slug(&obs.slug);
        if obs.slug.is_empty() {
            continue;
        }
        if let Some(wanted) = &requested_slug {
            if &obs.slug != wanted {
                continue;
            }
        }
        by_slug.entry(obs.slug.clone()).or_default().push(obs);
    }

    if let Some(wanted) = &requested_slug {
        anyhow::ensure!(
            by_slug.contains_key(wanted),
            "no observations matched --slug `{}`",
            wanted
        );
    }

    anyhow::ensure!(
        by_slug.len() == 1,
        "input contains {} domains: {}. Use `scan` for multi-domain feeds or pass `--slug <domain>`.",
        by_slug.len(),
        by_slug.keys().cloned().collect::<Vec<_>>().join(", ")
    );

    let (slug, observations) = by_slug.into_iter().next().expect("checked one domain");
    Ok(DomainCandidate::from_observations(slug, observations))
}

pub fn init_project(root: &Path, overwrite: bool) -> anyhow::Result<()> {
    let config_dir = root.join("config");
    let obs_dir = root.join("data/observations");
    let docs_dir = root.join("docs");
    ensure_dir(&config_dir)?;
    ensure_dir(&obs_dir)?;
    ensure_dir(&docs_dir)?;

    write_if_allowed(
        &config_dir.join("domain_finder.toml"),
        SAMPLE_CONFIG,
        overwrite,
    )?;
    write_if_allowed(
        &obs_dir.join("sample_domains.jsonl"),
        SAMPLE_OBSERVATIONS,
        overwrite,
    )?;
    write_if_allowed(
        &docs_dir.join("DOMAIN_RESEARCH_REGISTRY.md"),
        SAMPLE_REGISTRY,
        overwrite,
    )?;
    write_if_allowed(
        &docs_dir.join("DOMAIN_INTAKE_TEMPLATE.md"),
        SAMPLE_INTAKE_TEMPLATE,
        overwrite,
    )?;
    Ok(())
}

fn write_if_allowed(path: &Path, text: &str, overwrite: bool) -> anyhow::Result<()> {
    if path.exists() && !overwrite {
        return Ok(());
    }
    if let Some(parent) = path.parent() {
        ensure_dir(parent)?;
    }
    fs::write(path, text).with_context(|| format!("failed to write {}", path.display()))
}

const SAMPLE_CONFIG: &str = r#"artifacts_dir = "artifacts/domain_finder"
intake_dir = "docs/intakes/generated"

[thresholds]
full_lifecycle = 24
feasibility_only = 18
backlog = 12

[hard_minimums]
public_timestamp_clarity = 2
delayed_digestion_plausibility = 2
materiality_field_clarity = 2
sample_size_likelihood = 2

[registry]
path = "docs/DOMAIN_RESEARCH_REGISTRY.md"
frozen_statuses = ["frozen", "failed", "failed_falsification", "failed_execution", "failed_after_causal_rebuild", "execution_unrealistic", "mapping_insufficient", "parser_not_trusted", "timestamp_insufficient", "context_insufficient"]
monitor_statuses = ["underpowered_monitor"]

[feedback]
path = "artifacts/orchestrator/domain_feedback.jsonl"
min_source_rows_for_low_yield = 50
max_positive_yield_for_penalty = 0.01

[[feeds]]
name = "local_observations"
kind = "jsonl"
path = "data/observations"
"#;

const SAMPLE_OBSERVATIONS: &str = r#"{"slug":"cybersecurity_material_incidents_8k","title":"SEC Item 1.05 Material Cybersecurity Incidents","source_name":"SEC EDGAR","source_kind":"sec_official","official_source":true,"timestamp_quality":"clear","delayed_digest_reasons":["scope and financial impact often evolve through amendments","investors may need to distinguish operational disruption from generic breach"],"hard_negatives":["generic cyber risk language","no-material-impact amendment","vendor vulnerability not tied to issuer","duplicate PR/8-K"],"materiality_fields":["operational_disruption_flag","customer_data_exposure_flag","financial_impact_language","market_cap_before_event"],"mapping_notes":"SEC issuer CIK to ticker mapping is clean","sample_size_hint":43,"liquidity_notes":"mixed public issuers; filter by price and ADV","evidence":["Item 1.05 filings are official but current sample is underpowered"],"tags":["sec","monitor","cyber"]}
{"slug":"bank_regulatory_enforcement","title":"Public Bank Regulatory Enforcement / Consent Orders","source_name":"OCC/FDIC/Federal Reserve","source_kind":"official_agency","official_source":true,"timestamp_quality":"clear","delayed_digest_reasons":["orders can restrict growth, capital, compliance, and operations over time","market may need to digest severity and repeat-offender status"],"hard_negatives":["termination of prior order","minor procedural update","private bank","already-known consent order"],"materiality_fields":["civil_money_penalty_pct_market_cap","asset_size","capital_restriction_flag","bsa_aml_flag"],"mapping_notes":"public bank holding company mapping feasible but prior run was underpowered","sample_size_hint":28,"liquidity_notes":"public banks often tradable; small banks may be illiquid","evidence":["Prior feasibility underpowered but not a signal failure"],"tags":["bank","regulatory","feasibility"]}
{"slug":"fda_warning_letters_public_companies","title":"FDA Warning Letters and Import Alerts for Public Companies","source_name":"FDA","source_kind":"official_agency","official_source":true,"timestamp_quality":"clear","delayed_digest_reasons":["manufacturing and import-alert consequences can unfold over weeks","product/facility impact may require interpretation"],"hard_negatives":["private company","minor labeling issue","already-resolved warning","non-material product line"],"materiality_fields":["affected_product_revenue_exposure","import_alert_flag","repeat_warning_flag","market_cap_before_event"],"mapping_notes":"mapping was insufficient in prior run; start with known public-company universe","sample_size_hint":25,"liquidity_notes":"depends on public-company filter","evidence":["Prior run found many FDA rows but weak SEC ticker mapping"],"tags":["fda","enforcement","mapping-risk"]}
{"slug":"index_rebalance_events","title":"Index Additions / Deletions and Passive Flow Events","source_name":"Index provider announcements","source_kind":"public_index_announcement","official_source":false,"timestamp_quality":"public_but_session_ambiguous","delayed_digest_reasons":["implementation date and passive flow may unfold after announcement","demand impact depends on float and index ownership"],"hard_negatives":["preliminary list","already-known change","tiny float names","duplicate rebalancing notice"],"materiality_fields":["expected_passive_demand_pct_float","index_weight_change","market_cap_before_event"],"mapping_notes":"ticker mapping usually clean if announcements are structured","sample_size_hint":150,"liquidity_notes":"varies by index; liquidity filters required","evidence":["Crowded domain; requires careful feasibility before modeling"],"tags":["passive-flow","index","crowded"]}
"#;

const SAMPLE_REGISTRY: &str = r#"# Domain Research Registry

| domain | status | stage_reached | stop_reason | last_commit | revisit_trigger |
| --- | --- | --- | --- | --- | --- |
| cybersecurity_material_incidents_8k | underpowered_monitor | monitor/readiness | Item 1.05 sample too small | 878db5f | rerun when 80+ reviewed, 60+ material, 30+ OOS |
| insider_purchase_clusters | frozen | causal rebuild | failed after causal rebuild: null-shuffle and concentration | b0923ce | new pre-registered thesis only |
| capital_raise_dilution | frozen | timestamp repair | failed after timestamp/session repair | historical | new thesis only |
"#;

const SAMPLE_INTAKE_TEMPLATE: &str = r#"# Domain Intake Template

## Front-Door Gate

1. What is the official or primary source?
2. What is the first realistic public-awareness timestamp?
3. Why should this still be tradable after next open?
4. What hard negatives prevent lazy labels?
5. What materiality field makes the event economically meaningful?
6. What would make execution unrealistic?
7. What would make the result explanation-only rather than tradable?

## Scoring

Score each dimension 0-3:

- official source quality
- public timestamp clarity
- delayed-digestion plausibility
- hard-negative clarity
- materiality-field clarity
- sample-size likelihood
- ticker/entity mapping feasibility
- liquidity/execution feasibility
- parser/audit feasibility
- fresh-data availability
"#;
