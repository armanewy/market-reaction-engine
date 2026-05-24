use crate::model::{DomainCandidate, GateDecision, ScoreCard};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::Path;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TopEntry {
    pub rank: usize,
    pub slug: String,
    pub title: String,
    pub score: u8,
    pub gate: GateDecision,
    pub registry_status: Option<String>,
    pub positive_factors: Vec<String>,
    pub blockers: Vec<String>,
    pub recommended_next_action: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExplainOutput {
    pub slug: String,
    pub title: String,
    pub score: ScoreCard,
    pub gate: GateDecision,
    pub registry_status: Option<String>,
    pub registry_stop_reason: Option<String>,
    pub registry_revisit_trigger: Option<String>,
    pub hard_minimum_failures: Vec<String>,
    pub warnings: Vec<String>,
    pub observations: usize,
    pub source_kinds: Vec<String>,
    pub hard_negatives: Vec<String>,
    pub materiality_fields: Vec<String>,
    pub delayed_digest_reasons: Vec<String>,
    pub recommended_next_action: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DiffOutput {
    pub new_domains: Vec<String>,
    pub removed_domains: Vec<String>,
    pub score_changes: Vec<ScoreChange>,
    pub gate_changes: Vec<GateChange>,
    pub registry_changes: Vec<RegistryChange>,
    pub revisit_trigger_changes: Vec<RevisitTriggerChange>,
    pub newly_eligible_for_intake: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ScoreChange {
    pub slug: String,
    pub old_score: u8,
    pub new_score: u8,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GateChange {
    pub slug: String,
    pub old_gate: GateDecision,
    pub new_gate: GateDecision,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RegistryChange {
    pub slug: String,
    pub old_status: Option<String>,
    pub new_status: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RevisitTriggerChange {
    pub slug: String,
    pub old_trigger: Option<String>,
    pub new_trigger: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AlertOutput {
    pub alerts: Vec<DomainAlert>,
    pub suppressed_blocked_count: usize,
    pub monitor_only_count: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DomainAlert {
    pub slug: String,
    pub gate: GateDecision,
    pub score: u8,
    pub severity: String,
    pub message: String,
    pub recommended_next_action: String,
}

pub fn top_candidates(candidates: &[DomainCandidate], limit: usize) -> Vec<TopEntry> {
    let mut selected = candidates
        .iter()
        .filter(|candidate| {
            !matches!(
                candidate.gate,
                GateDecision::BlockedByRegistry | GateDecision::Skip
            )
        })
        .cloned()
        .collect::<Vec<_>>();
    selected.sort_by(|a, b| {
        gate_rank(a.gate)
            .cmp(&gate_rank(b.gate))
            .then_with(|| b.score.total.cmp(&a.score.total))
            .then_with(|| a.slug.cmp(&b.slug))
    });

    selected
        .iter()
        .take(limit)
        .enumerate()
        .map(|(idx, candidate)| TopEntry {
            rank: idx + 1,
            slug: candidate.slug.clone(),
            title: candidate.title.clone(),
            score: candidate.score.total,
            gate: candidate.gate,
            registry_status: candidate
                .registry_status
                .as_ref()
                .map(|entry| entry.status.clone()),
            positive_factors: positive_factors(candidate),
            blockers: blockers(candidate),
            recommended_next_action: recommended_next_action(candidate),
        })
        .collect()
}

pub fn explain_candidate(candidate: &DomainCandidate) -> ExplainOutput {
    ExplainOutput {
        slug: candidate.slug.clone(),
        title: candidate.title.clone(),
        score: candidate.score.clone(),
        gate: candidate.gate,
        registry_status: candidate
            .registry_status
            .as_ref()
            .map(|entry| entry.status.clone()),
        registry_stop_reason: candidate
            .registry_status
            .as_ref()
            .and_then(|entry| entry.stop_reason.clone()),
        registry_revisit_trigger: candidate
            .registry_status
            .as_ref()
            .and_then(|entry| entry.revisit_trigger.clone()),
        hard_minimum_failures: hard_minimum_failures(candidate),
        warnings: candidate.warnings.clone(),
        observations: candidate.observations.len(),
        source_kinds: candidate.source_kinds.clone(),
        hard_negatives: candidate.hard_negatives.clone(),
        materiality_fields: candidate.materiality_fields.clone(),
        delayed_digest_reasons: candidate.delayed_digest_reasons.clone(),
        recommended_next_action: recommended_next_action(candidate),
    }
}

pub fn diff_candidates(old: &[DomainCandidate], new: &[DomainCandidate]) -> DiffOutput {
    let old_by_slug = by_slug(old);
    let new_by_slug = by_slug(new);

    let old_slugs = old_by_slug.keys().cloned().collect::<BTreeSet<_>>();
    let new_slugs = new_by_slug.keys().cloned().collect::<BTreeSet<_>>();

    let new_domains = new_slugs
        .difference(&old_slugs)
        .cloned()
        .collect::<Vec<_>>();
    let removed_domains = old_slugs
        .difference(&new_slugs)
        .cloned()
        .collect::<Vec<_>>();

    let mut score_changes = Vec::new();
    let mut gate_changes = Vec::new();
    let mut registry_changes = Vec::new();
    let mut revisit_trigger_changes = Vec::new();
    let mut newly_eligible_for_intake = Vec::new();

    for slug in old_slugs.intersection(&new_slugs) {
        let old_candidate = old_by_slug[slug];
        let new_candidate = new_by_slug[slug];

        if old_candidate.score.total != new_candidate.score.total {
            score_changes.push(ScoreChange {
                slug: slug.clone(),
                old_score: old_candidate.score.total,
                new_score: new_candidate.score.total,
            });
        }

        if old_candidate.gate != new_candidate.gate {
            gate_changes.push(GateChange {
                slug: slug.clone(),
                old_gate: old_candidate.gate,
                new_gate: new_candidate.gate,
            });
            if !is_intake_eligible(old_candidate.gate) && is_intake_eligible(new_candidate.gate) {
                newly_eligible_for_intake.push(slug.clone());
            }
        }

        let old_status = registry_status(old_candidate);
        let new_status = registry_status(new_candidate);
        if old_status != new_status {
            registry_changes.push(RegistryChange {
                slug: slug.clone(),
                old_status,
                new_status,
            });
        }

        let old_trigger = revisit_trigger(old_candidate);
        let new_trigger = revisit_trigger(new_candidate);
        if old_trigger != new_trigger {
            revisit_trigger_changes.push(RevisitTriggerChange {
                slug: slug.clone(),
                old_trigger,
                new_trigger,
            });
        }
    }

    for slug in &new_domains {
        if let Some(candidate) = new_by_slug.get(slug) {
            if is_intake_eligible(candidate.gate) {
                newly_eligible_for_intake.push(slug.clone());
            }
        }
    }

    DiffOutput {
        new_domains,
        removed_domains,
        score_changes,
        gate_changes,
        registry_changes,
        revisit_trigger_changes,
        newly_eligible_for_intake,
    }
}

pub fn current_alerts(candidates: &[DomainCandidate]) -> AlertOutput {
    let mut alerts = Vec::new();
    let mut suppressed_blocked_count = 0usize;
    let mut monitor_only_count = 0usize;

    for candidate in candidates {
        match candidate.gate {
            GateDecision::FullLifecycle => alerts.push(DomainAlert {
                slug: candidate.slug.clone(),
                gate: candidate.gate,
                score: candidate.score.total,
                severity: "review".to_string(),
                message: "domain clears full-lifecycle intake score".to_string(),
                recommended_next_action: recommended_next_action(candidate),
            }),
            GateDecision::FeasibilityOnly => alerts.push(DomainAlert {
                slug: candidate.slug.clone(),
                gate: candidate.gate,
                score: candidate.score.total,
                severity: "feasibility".to_string(),
                message: "domain should receive feasibility review only".to_string(),
                recommended_next_action: recommended_next_action(candidate),
            }),
            GateDecision::MonitorOnly => {
                monitor_only_count += 1;
                alerts.push(DomainAlert {
                    slug: candidate.slug.clone(),
                    gate: candidate.gate,
                    score: candidate.score.total,
                    severity: "monitor".to_string(),
                    message:
                        "domain remains monitor-only until its registry revisit trigger is met"
                            .to_string(),
                    recommended_next_action: recommended_next_action(candidate),
                });
            }
            GateDecision::BlockedByRegistry => suppressed_blocked_count += 1,
            GateDecision::Backlog | GateDecision::Skip => {}
        }
    }

    alerts.sort_by(|a, b| {
        gate_rank(a.gate)
            .cmp(&gate_rank(b.gate))
            .then_with(|| b.score.cmp(&a.score))
            .then_with(|| a.slug.cmp(&b.slug))
    });

    AlertOutput {
        alerts,
        suppressed_blocked_count,
        monitor_only_count,
    }
}

pub fn load_candidates(path: &Path) -> anyhow::Result<Vec<DomainCandidate>> {
    let text = fs::read_to_string(path)
        .map_err(|err| anyhow::anyhow!("failed to read {}: {}", path.display(), err))?;
    serde_json::from_str(&text).map_err(|err| {
        anyhow::anyhow!("failed to parse candidate JSON {}: {}", path.display(), err)
    })
}

pub fn top_report(entries: &[TopEntry]) -> String {
    let mut out = String::new();
    out.push_str(
        "| Rank | Domain | Score | Gate | Registry | Positive Factors | Blockers | Next Action |\n",
    );
    out.push_str("| ---: | --- | ---: | --- | --- | --- | --- | --- |\n");
    for entry in entries {
        out.push_str(&format!(
            "| {} | `{}` | {} | `{}` | {} | {} | {} | {} |\n",
            entry.rank,
            entry.slug,
            entry.score,
            entry.gate.label(),
            entry
                .registry_status
                .as_ref()
                .map(|s| format!("`{}`", s))
                .unwrap_or_else(|| "-".to_string()),
            list_or_dash(&entry.positive_factors),
            list_or_dash(&entry.blockers),
            entry.recommended_next_action
        ));
    }
    out
}

pub fn explain_report(explain: &ExplainOutput) -> String {
    let mut out = String::new();
    out.push_str(&format!("# Domain Explanation: `{}`\n\n", explain.slug));
    out.push_str(&format!("- title: {}\n", explain.title));
    out.push_str(&format!("- score: `{}/30`\n", explain.score.total));
    out.push_str(&format!("- gate: `{}`\n", explain.gate.label()));
    out.push_str(&format!(
        "- registry_status: {}\n",
        explain
            .registry_status
            .as_ref()
            .map(|s| format!("`{}`", s))
            .unwrap_or_else(|| "-".to_string())
    ));
    if let Some(reason) = &explain.registry_stop_reason {
        out.push_str(&format!("- registry_stop_reason: {}\n", reason));
    }
    if let Some(trigger) = &explain.registry_revisit_trigger {
        out.push_str(&format!("- registry_revisit_trigger: {}\n", trigger));
    }
    out.push_str(&format!(
        "- recommended_next_action: {}\n\n",
        explain.recommended_next_action
    ));
    out.push_str("## Scorecard\n\n");
    out.push_str(&scorecard_markdown(&explain.score));
    out.push_str("\n## Hard Minimum Failures\n\n");
    if explain.hard_minimum_failures.is_empty() {
        out.push_str("- none\n");
    } else {
        for failure in &explain.hard_minimum_failures {
            out.push_str(&format!("- {}\n", failure));
        }
    }
    out.push_str("\n## Warnings\n\n");
    if explain.warnings.is_empty() {
        out.push_str("- none\n");
    } else {
        for warning in &explain.warnings {
            out.push_str(&format!("- {}\n", warning));
        }
    }
    out.push_str("\n## Evidence\n\n");
    out.push_str(&format!("- observations: `{}`\n", explain.observations));
    out.push_str(&format!(
        "- source_kinds: {}\n",
        list_or_dash(&explain.source_kinds)
    ));
    out.push_str(&format!(
        "- delayed_digest_reasons: {}\n",
        list_or_dash(&explain.delayed_digest_reasons)
    ));
    out.push_str(&format!(
        "- hard_negatives: {}\n",
        list_or_dash(&explain.hard_negatives)
    ));
    out.push_str(&format!(
        "- materiality_fields: {}\n",
        list_or_dash(&explain.materiality_fields)
    ));
    out
}

pub fn diff_report(diff: &DiffOutput) -> String {
    let mut out = String::new();
    out.push_str("# Domain Finder Diff\n\n");
    section_list(&mut out, "New Domains", &diff.new_domains);
    section_list(&mut out, "Removed Domains", &diff.removed_domains);
    out.push_str("## Score Changes\n\n");
    if diff.score_changes.is_empty() {
        out.push_str("- none\n\n");
    } else {
        for change in &diff.score_changes {
            out.push_str(&format!(
                "- `{}`: {} -> {}\n",
                change.slug, change.old_score, change.new_score
            ));
        }
        out.push('\n');
    }
    out.push_str("## Gate Changes\n\n");
    if diff.gate_changes.is_empty() {
        out.push_str("- none\n\n");
    } else {
        for change in &diff.gate_changes {
            out.push_str(&format!(
                "- `{}`: `{}` -> `{}`\n",
                change.slug,
                change.old_gate.label(),
                change.new_gate.label()
            ));
        }
        out.push('\n');
    }
    out.push_str("## Registry Changes\n\n");
    if diff.registry_changes.is_empty() {
        out.push_str("- none\n\n");
    } else {
        for change in &diff.registry_changes {
            out.push_str(&format!(
                "- `{}`: {} -> {}\n",
                change.slug,
                option_or_dash(&change.old_status),
                option_or_dash(&change.new_status)
            ));
        }
        out.push('\n');
    }
    out.push_str("## Revisit Trigger Changes\n\n");
    if diff.revisit_trigger_changes.is_empty() {
        out.push_str("- none\n\n");
    } else {
        for change in &diff.revisit_trigger_changes {
            out.push_str(&format!(
                "- `{}`: {} -> {}\n",
                change.slug,
                option_or_dash(&change.old_trigger),
                option_or_dash(&change.new_trigger)
            ));
        }
        out.push('\n');
    }
    section_list(
        &mut out,
        "Newly Eligible For Intake",
        &diff.newly_eligible_for_intake,
    );
    out
}

pub fn alerts_report(alerts: &AlertOutput) -> String {
    let mut out = String::new();
    out.push_str("# Domain Finder Alerts\n\n");
    out.push_str(&format!(
        "- suppressed blocked domains: `{}`\n",
        alerts.suppressed_blocked_count
    ));
    out.push_str(&format!(
        "- monitor-only domains: `{}`\n\n",
        alerts.monitor_only_count
    ));
    if alerts.alerts.is_empty() {
        out.push_str("No actionable alerts.\n");
        return out;
    }
    out.push_str("| Domain | Severity | Score | Gate | Next Action |\n");
    out.push_str("| --- | --- | ---: | --- | --- |\n");
    for alert in &alerts.alerts {
        out.push_str(&format!(
            "| `{}` | `{}` | {} | `{}` | {} |\n",
            alert.slug,
            alert.severity,
            alert.score,
            alert.gate.label(),
            alert.recommended_next_action
        ));
    }
    out
}

fn by_slug(candidates: &[DomainCandidate]) -> BTreeMap<String, &DomainCandidate> {
    candidates
        .iter()
        .map(|candidate| (candidate.slug.clone(), candidate))
        .collect()
}

fn is_intake_eligible(gate: GateDecision) -> bool {
    matches!(
        gate,
        GateDecision::FullLifecycle | GateDecision::FeasibilityOnly | GateDecision::MonitorOnly
    )
}

fn gate_rank(gate: GateDecision) -> u8 {
    match gate {
        GateDecision::FullLifecycle => 0,
        GateDecision::FeasibilityOnly => 1,
        GateDecision::MonitorOnly => 2,
        GateDecision::Backlog => 3,
        GateDecision::Skip => 4,
        GateDecision::BlockedByRegistry => 5,
    }
}

fn registry_status(candidate: &DomainCandidate) -> Option<String> {
    candidate
        .registry_status
        .as_ref()
        .map(|entry| entry.status.clone())
}

fn revisit_trigger(candidate: &DomainCandidate) -> Option<String> {
    candidate
        .registry_status
        .as_ref()
        .and_then(|entry| entry.revisit_trigger.clone())
}

fn positive_factors(candidate: &DomainCandidate) -> Vec<String> {
    let mut factors = Vec::new();
    if candidate.score.official_source_quality >= 3 {
        factors.push("official source".to_string());
    }
    if candidate.score.public_timestamp_clarity >= 3 {
        factors.push("clear public timestamp".to_string());
    }
    if candidate.score.delayed_digestion_plausibility >= 2 {
        factors.push("delayed-digestion rationale".to_string());
    }
    if candidate.score.materiality_field_clarity >= 2 {
        factors.push("materiality fields present".to_string());
    }
    if candidate.score.ticker_mapping_feasibility >= 2 {
        factors.push("mapping appears feasible".to_string());
    }
    factors
}

fn blockers(candidate: &DomainCandidate) -> Vec<String> {
    let mut blockers = hard_minimum_failures(candidate);
    if matches!(candidate.gate, GateDecision::BlockedByRegistry) {
        blockers.push("blocked by registry".to_string());
    }
    if let Some(entry) = &candidate.registry_status {
        if let Some(reason) = &entry.stop_reason {
            blockers.push(reason.clone());
        }
    }
    blockers
}

fn hard_minimum_failures(candidate: &DomainCandidate) -> Vec<String> {
    let mut failures = Vec::new();
    if candidate.score.public_timestamp_clarity < 2 {
        failures.push("public timestamp clarity below hard minimum".to_string());
    }
    if candidate.score.delayed_digestion_plausibility < 2 {
        failures.push("delayed-digestion plausibility below hard minimum".to_string());
    }
    if candidate.score.materiality_field_clarity < 2 {
        failures.push("materiality-field clarity below hard minimum".to_string());
    }
    if candidate.score.sample_size_likelihood < 2 {
        failures.push("sample-size likelihood below hard minimum".to_string());
    }
    failures
}

fn recommended_next_action(candidate: &DomainCandidate) -> String {
    match candidate.gate {
        GateDecision::FullLifecycle => {
            "review intake, then consider full MRE lifecycle".to_string()
        }
        GateDecision::FeasibilityOnly => "source feasibility only; do not model".to_string(),
        GateDecision::MonitorOnly => candidate
            .registry_status
            .as_ref()
            .and_then(|entry| entry.revisit_trigger.clone())
            .map(|trigger| format!("monitor only until trigger is met: {}", trigger))
            .unwrap_or_else(|| "monitor only; do not model yet".to_string()),
        GateDecision::Backlog => "keep in backlog until hard blockers improve".to_string(),
        GateDecision::Skip => "skip unless source quality materially changes".to_string(),
        GateDecision::BlockedByRegistry => "suppress; registry blocks this thesis".to_string(),
    }
}

fn scorecard_markdown(score: &ScoreCard) -> String {
    let rows = [
        ("official_source_quality", score.official_source_quality),
        ("public_timestamp_clarity", score.public_timestamp_clarity),
        (
            "delayed_digestion_plausibility",
            score.delayed_digestion_plausibility,
        ),
        ("hard_negative_clarity", score.hard_negative_clarity),
        ("materiality_field_clarity", score.materiality_field_clarity),
        ("sample_size_likelihood", score.sample_size_likelihood),
        (
            "ticker_mapping_feasibility",
            score.ticker_mapping_feasibility,
        ),
        (
            "liquidity_execution_feasibility",
            score.liquidity_execution_feasibility,
        ),
        ("parser_audit_feasibility", score.parser_audit_feasibility),
        ("fresh_data_availability", score.fresh_data_availability),
    ];
    let mut out = String::from("| Dimension | Score |\n| --- | ---: |\n");
    for (dimension, value) in rows {
        out.push_str(&format!("| {} | {} |\n", dimension, value));
    }
    out
}

fn list_or_dash(items: &[String]) -> String {
    if items.is_empty() {
        "-".to_string()
    } else {
        items.join("; ")
    }
}

fn section_list(out: &mut String, title: &str, items: &[String]) {
    out.push_str(&format!("## {}\n\n", title));
    if items.is_empty() {
        out.push_str("- none\n\n");
    } else {
        for item in items {
            out.push_str(&format!("- `{}`\n", item));
        }
        out.push('\n');
    }
}

fn option_or_dash(value: &Option<String>) -> String {
    value.clone().unwrap_or_else(|| "-".to_string())
}
