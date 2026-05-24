use crate::model::{DomainCandidate, GateDecision, ScoreCard};
use chrono::Utc;

pub fn discovery_report(candidates: &[DomainCandidate]) -> String {
    let mut out = String::new();
    out.push_str("# Domain Finder Discovery Report\n\n");
    out.push_str(&format!("Generated: `{}`\n\n", Utc::now().to_rfc3339()));
    out.push_str("## Summary\n\n");
    out.push_str("| Rank | Domain | Score | Gate | Registry Status | Warnings |\n");
    out.push_str("| ---: | --- | ---: | --- | --- | --- |\n");
    for (i, c) in candidates.iter().enumerate() {
        out.push_str(&format!(
            "| {} | `{}` | {} | `{}` | {} | {} |\n",
            i + 1,
            c.slug,
            c.score.total,
            c.gate.label(),
            c.registry_status
                .as_ref()
                .map(|entry| format!("`{}`", entry.status))
                .unwrap_or_default(),
            if c.warnings.is_empty() {
                "".to_string()
            } else {
                c.warnings.join("; ")
            }
        ));
    }
    out.push_str("\n## Candidate Details\n\n");
    for c in candidates {
        out.push_str(&candidate_section(c));
    }
    out
}

fn candidate_section(c: &DomainCandidate) -> String {
    let mut out = String::new();
    out.push_str(&format!("### `{}` — {}\n\n", c.slug, c.title));
    out.push_str(&format!("Gate: `{}`  \n", c.gate.label()));
    out.push_str(&format!("Score: `{}/30`  \n", c.score.total));
    if let Some(entry) = &c.registry_status {
        out.push_str(&format!("Registry status: `{}`  \n", entry.status));
        if let Some(stage) = &entry.stage_reached {
            out.push_str(&format!("Registry stage reached: {}  \n", stage));
        }
        if let Some(reason) = &entry.stop_reason {
            out.push_str(&format!("Registry stop reason: {}  \n", reason));
        }
        if let Some(trigger) = &entry.revisit_trigger {
            out.push_str(&format!("Registry revisit trigger: {}  \n", trigger));
        }
    }
    out.push_str("\n#### Scorecard\n\n");
    out.push_str(&score_table(&c.score));
    out.push_str("\n#### Evidence\n\n");
    out.push_str(&format!("- Observations: `{}`\n", c.observations.len()));
    out.push_str(&format!(
        "- Official-source observations: `{}`\n",
        c.official_source_count
    ));
    out.push_str(&format!(
        "- Max sample-size hint: `{}`\n",
        c.max_sample_size_hint
            .map(|n| n.to_string())
            .unwrap_or_else(|| "unknown".to_string())
    ));
    out.push_str(&format!(
        "- Source kinds: {}\n",
        list_or_dash(&c.source_kinds)
    ));
    out.push_str(&format!(
        "- Delayed-digestion reasons: {}\n",
        list_or_dash(&c.delayed_digest_reasons)
    ));
    out.push_str(&format!(
        "- Hard negatives: {}\n",
        list_or_dash(&c.hard_negatives)
    ));
    out.push_str(&format!(
        "- Materiality fields: {}\n",
        list_or_dash(&c.materiality_fields)
    ));
    if !c.warnings.is_empty() {
        out.push_str("\n#### Warnings\n\n");
        for w in &c.warnings {
            out.push_str(&format!("- {}\n", w));
        }
    }
    out.push('\n');
    out
}

fn score_table(s: &ScoreCard) -> String {
    let rows = [
        ("official_source_quality", s.official_source_quality),
        ("public_timestamp_clarity", s.public_timestamp_clarity),
        (
            "delayed_digestion_plausibility",
            s.delayed_digestion_plausibility,
        ),
        ("hard_negative_clarity", s.hard_negative_clarity),
        ("materiality_field_clarity", s.materiality_field_clarity),
        ("sample_size_likelihood", s.sample_size_likelihood),
        ("ticker_mapping_feasibility", s.ticker_mapping_feasibility),
        (
            "liquidity_execution_feasibility",
            s.liquidity_execution_feasibility,
        ),
        ("parser_audit_feasibility", s.parser_audit_feasibility),
        ("fresh_data_availability", s.fresh_data_availability),
    ];
    let mut out = String::from("| Dimension | Score |\n| --- | ---: |\n");
    for (name, val) in rows {
        out.push_str(&format!("| {} | {} |\n", name, val));
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

pub fn intake_doc(c: &DomainCandidate) -> String {
    let mut out = String::new();
    out.push_str(&format!("# Domain Intake: {}\n\n", c.title));
    out.push_str(&format!("Domain slug: `{}`\n\n", c.slug));
    out.push_str("## Current Finder Score\n\n");
    out.push_str(&format!("- Total score: `{}/30`\n", c.score.total));
    out.push_str(&format!("- Finder gate: `{}`\n", c.gate.label()));
    if let Some(entry) = &c.registry_status {
        out.push_str(&format!("- Registry status: `{}`\n", entry.status));
    }
    if let Some(entry) = &c.registry_status {
        out.push_str("\n## Registry History\n\n");
        out.push_str(&format!("- status: `{}`\n", entry.status));
        if let Some(stage) = &entry.stage_reached {
            out.push_str(&format!("- stage_reached: {}\n", stage));
        }
        if let Some(reason) = &entry.stop_reason {
            out.push_str(&format!("- stop_reason: {}\n", reason));
        }
        if let Some(trigger) = &entry.revisit_trigger {
            out.push_str(&format!("- revisit_trigger: {}\n", trigger));
        }
        if matches!(c.gate, GateDecision::BlockedByRegistry) {
            out.push_str(
                "\nThis domain is blocked unless the proposed thesis is materially different from the prior frozen or failed thesis.\n",
            );
        } else if matches!(c.gate, GateDecision::MonitorOnly) {
            out.push_str(
                "\nThis domain should be monitored, not modeled, until the revisit trigger is met.\n",
            );
        }
    }
    out.push_str("\n## Front-Door Gate\n\n");
    out.push_str("1. What is the official or primary source?\n\n");
    out.push_str(&format!(
        "   - Finder evidence: {}\n\n",
        list_or_dash(&c.source_kinds)
    ));
    out.push_str("2. What is the first realistic public-awareness timestamp?\n\n");
    out.push_str("3. Why should this still be tradable after next open?\n\n");
    out.push_str(&format!(
        "   - Finder delayed-digestion notes: {}\n\n",
        list_or_dash(&c.delayed_digest_reasons)
    ));
    out.push_str("4. What hard negatives prevent lazy labels?\n\n");
    out.push_str(&format!(
        "   - Finder hard negatives: {}\n\n",
        list_or_dash(&c.hard_negatives)
    ));
    out.push_str("5. What materiality field makes the event economically meaningful?\n\n");
    out.push_str(&format!(
        "   - Finder materiality fields: {}\n\n",
        list_or_dash(&c.materiality_fields)
    ));
    out.push_str("6. What would make execution unrealistic?\n\n");
    out.push_str("7. What would make the result explanation-only rather than tradable?\n\n");
    out.push_str("## Required Feasibility Outputs\n\n");
    out.push_str("- Estimated source rows\n- Estimated public-company mapped rows\n- Estimated primary event rows\n- Timestamp quality assessment\n- Hard-negative examples\n- Materiality coverage estimate\n- Liquidity/execution risk\n- Recommendation: full lifecycle / feasibility only / backlog / skip\n");
    out
}

pub fn decision_counts(candidates: &[DomainCandidate]) -> Vec<(GateDecision, usize)> {
    let order = [
        GateDecision::FullLifecycle,
        GateDecision::FeasibilityOnly,
        GateDecision::Backlog,
        GateDecision::Skip,
        GateDecision::MonitorOnly,
        GateDecision::BlockedByRegistry,
    ];
    order
        .iter()
        .map(|g| (*g, candidates.iter().filter(|c| c.gate == *g).count()))
        .collect()
}
