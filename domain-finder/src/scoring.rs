use crate::config::{Config, HardMinimums};
use crate::model::{DomainCandidate, GateDecision, ScoreCard, TimestampQuality};
use std::collections::HashSet;

pub fn score_candidate(mut candidate: DomainCandidate, config: &Config) -> DomainCandidate {
    let mut score = ScoreCard {
        official_source_quality: score_official_source(&candidate),
        public_timestamp_clarity: score_timestamp(&candidate),
        delayed_digestion_plausibility: score_count(
            candidate.delayed_digest_reasons.len(),
            1,
            2,
            4,
        ),
        hard_negative_clarity: score_count(candidate.hard_negatives.len(), 1, 3, 6),
        materiality_field_clarity: score_count(candidate.materiality_fields.len(), 1, 2, 4),
        sample_size_likelihood: score_sample_size(candidate.max_sample_size_hint),
        ticker_mapping_feasibility: score_mapping(&candidate),
        liquidity_execution_feasibility: score_liquidity(&candidate),
        parser_audit_feasibility: score_parser(&candidate),
        fresh_data_availability: score_fresh_data(&candidate),
        total: 0,
    };
    score.recalc_total();

    candidate.score = score;
    candidate.gate = decide_gate(&candidate, config);
    candidate
        .warnings
        .extend(build_warnings(&candidate, &config.hard_minimums));
    candidate
}

fn score_official_source(c: &DomainCandidate) -> u8 {
    if c.observations.is_empty() {
        0
    } else if c.official_source_count == c.observations.len() {
        3
    } else if c.official_source_count > 0 {
        2
    } else if c.source_kinds.iter().any(|s| is_likely_primary_source(s)) {
        1
    } else {
        0
    }
}

fn score_timestamp(c: &DomainCandidate) -> u8 {
    let mut clear = 0;
    let mut public_ambiguous = 0;
    let mut record_only = 0;
    for obs in &c.observations {
        match obs.timestamp_quality {
            TimestampQuality::Clear => clear += 1,
            TimestampQuality::PublicButSessionAmbiguous => public_ambiguous += 1,
            TimestampQuality::RecordOnly => record_only += 1,
            TimestampQuality::Fuzzy | TimestampQuality::Unknown => {}
        }
    }
    if clear > 0 && clear >= public_ambiguous + record_only {
        3
    } else if clear > 0 || public_ambiguous > 0 {
        2
    } else if record_only > 0 {
        1
    } else {
        0
    }
}

fn score_count(n: usize, low: usize, mid: usize, high: usize) -> u8 {
    if n >= high {
        3
    } else if n >= mid {
        2
    } else if n >= low {
        1
    } else {
        0
    }
}

fn score_sample_size(max_hint: Option<u32>) -> u8 {
    match max_hint.unwrap_or(0) {
        n if n >= 200 => 3,
        n if n >= 80 => 2,
        n if n >= 30 => 1,
        _ => 0,
    }
}

fn score_mapping(c: &DomainCandidate) -> u8 {
    let text = c
        .observations
        .iter()
        .filter_map(|o| o.mapping_notes.as_ref())
        .map(|s| s.to_lowercase())
        .collect::<Vec<_>>()
        .join(" ");

    if text.trim().is_empty() {
        return 1;
    }
    if text.contains("insufficient")
        || text.contains("ambiguous")
        || text.contains("unmapped")
        || text.contains("mapping-risk")
        || text.contains("mapping risk")
    {
        return 0;
    }
    if text.contains("clean")
        || text.contains("exact")
        || text.contains("high confidence")
        || text.contains("cik")
        || text.contains("issuer")
    {
        3
    } else if text.contains("manual")
        || text.contains("alias")
        || text.contains("subsidiary")
        || text.contains("feasible")
    {
        2
    } else {
        1
    }
}

fn score_liquidity(c: &DomainCandidate) -> u8 {
    let text = c
        .observations
        .iter()
        .filter_map(|o| o.liquidity_notes.as_ref())
        .map(|s| s.to_lowercase())
        .collect::<Vec<_>>()
        .join(" ");
    if text.contains("liquid") || text.contains("large cap") || text.contains("adv") {
        3
    } else if text.contains("mixed") || text.contains("filter") {
        2
    } else if text.contains("illiquid") || text.contains("halt") || text.contains("penny") {
        0
    } else {
        1
    }
}

fn score_parser(c: &DomainCandidate) -> u8 {
    let hard = c.hard_negatives.len();
    let evidence = c.evidence_count;
    if hard >= 5 && evidence >= 3 {
        3
    } else if hard >= 3 {
        2
    } else if hard >= 1 {
        1
    } else {
        0
    }
}

fn score_fresh_data(c: &DomainCandidate) -> u8 {
    let unique_sources: HashSet<&str> = c
        .observations
        .iter()
        .map(|o| o.source_name.as_str())
        .collect();
    let sample = c.max_sample_size_hint.unwrap_or(0);
    if unique_sources.len() >= 2 && sample >= 200 {
        3
    } else if sample >= 80 || c.observations.len() >= 3 {
        2
    } else if sample >= 30 || c.observations.len() >= 2 {
        1
    } else {
        0
    }
}

fn is_likely_primary_source(s: &str) -> bool {
    let s = s.to_lowercase();
    [
        "sec", "fda", "nhtsa", "occ", "fdic", "federal", "court", "agency", "official",
    ]
    .iter()
    .any(|needle| s.contains(needle))
}

fn decide_gate(c: &DomainCandidate, config: &Config) -> GateDecision {
    if let Some(registry) = &c.registry_status {
        let status = normalize_status(&registry.status);
        if config
            .registry
            .monitor_statuses
            .iter()
            .any(|s| status.contains(&normalize_status(s)))
        {
            return GateDecision::MonitorOnly;
        }
        if config
            .registry
            .frozen_statuses
            .iter()
            .any(|s| status.contains(&normalize_status(s)))
        {
            return GateDecision::BlockedByRegistry;
        }
    }

    if fails_hard_minimums(c, &config.hard_minimums) {
        return if c.score.total >= config.thresholds.feasibility_only {
            GateDecision::FeasibilityOnly
        } else if c.score.total >= config.thresholds.backlog {
            GateDecision::Backlog
        } else {
            GateDecision::Skip
        };
    }

    if c.score.total >= config.thresholds.full_lifecycle {
        GateDecision::FullLifecycle
    } else if c.score.total >= config.thresholds.feasibility_only {
        GateDecision::FeasibilityOnly
    } else if c.score.total >= config.thresholds.backlog {
        GateDecision::Backlog
    } else {
        GateDecision::Skip
    }
}

fn fails_hard_minimums(c: &DomainCandidate, mins: &HardMinimums) -> bool {
    c.score.public_timestamp_clarity < mins.public_timestamp_clarity
        || c.score.delayed_digestion_plausibility < mins.delayed_digestion_plausibility
        || c.score.materiality_field_clarity < mins.materiality_field_clarity
        || c.score.sample_size_likelihood < mins.sample_size_likelihood
}

fn build_warnings(c: &DomainCandidate, mins: &HardMinimums) -> Vec<String> {
    let mut warnings = Vec::new();
    if c.score.public_timestamp_clarity < mins.public_timestamp_clarity {
        warnings.push("public timestamp clarity below hard minimum".to_string());
    }
    if c.score.delayed_digestion_plausibility < mins.delayed_digestion_plausibility {
        warnings.push("delayed-digestion plausibility below hard minimum".to_string());
    }
    if c.score.materiality_field_clarity < mins.materiality_field_clarity {
        warnings.push("materiality-field clarity below hard minimum".to_string());
    }
    if c.score.sample_size_likelihood < mins.sample_size_likelihood {
        warnings.push("sample-size likelihood below hard minimum".to_string());
    }
    if c.registry_status.is_some() {
        warnings.push(
            "candidate already appears in domain registry; respect registry status".to_string(),
        );
    }
    warnings
}

fn normalize_status(status: &str) -> String {
    status.trim().to_ascii_lowercase().replace([' ', '-'], "_")
}
