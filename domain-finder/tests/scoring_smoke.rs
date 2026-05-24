use domain_finder::collectors::{built_in_observations, source_family_count};
use domain_finder::config::Config;
use domain_finder::model::{DomainCandidate, DomainObservation, GateDecision, TimestampQuality};
use domain_finder::pipeline::candidate_from_observations;
use domain_finder::registry::Registry;
use domain_finder::scoring::score_candidate;

#[test]
fn high_quality_domain_gets_full_lifecycle_gate() {
    let obs = DomainObservation {
        slug: "bank_reg_orders".to_string(),
        title: "Bank regulatory orders".to_string(),
        source_name: "OCC".to_string(),
        source_kind: "official_agency".to_string(),
        source_url: None,
        official_source: true,
        timestamp_quality: TimestampQuality::Clear,
        delayed_digest_reasons: vec![
            "regulatory consequences unfold over weeks".to_string(),
            "severity requires reading order text".to_string(),
        ],
        hard_negatives: vec![
            "order termination".to_string(),
            "procedural update".to_string(),
            "private bank".to_string(),
            "already-known action".to_string(),
        ],
        materiality_fields: vec![
            "civil_penalty_pct_market_cap".to_string(),
            "capital_restriction_flag".to_string(),
        ],
        mapping_notes: Some("clean ticker mapping for public banks".to_string()),
        sample_size_hint: Some(200),
        liquidity_notes: Some("public banks with liquidity filters".to_string()),
        evidence: vec![
            "official enforcement actions".to_string(),
            "timestamped orders".to_string(),
            "public issuers".to_string(),
        ],
        tags: vec![],
        observed_at: None,
        proposed_by: None,
    };
    let candidate = DomainCandidate::from_observations("bank_reg_orders".to_string(), vec![obs]);
    let scored = score_candidate(candidate, &Config::default());
    assert_eq!(scored.gate, GateDecision::FullLifecycle);
    assert!(scored.score.total >= 24);
}

#[test]
fn weak_timestamp_caps_to_feasibility_or_backlog() {
    let obs = DomainObservation {
        slug: "vague_news".to_string(),
        title: "Vague news".to_string(),
        official_source: false,
        timestamp_quality: TimestampQuality::Fuzzy,
        delayed_digest_reasons: vec!["maybe complicated".to_string(), "maybe delayed".to_string()],
        hard_negatives: vec![
            "rumor".to_string(),
            "duplicate".to_string(),
            "soft update".to_string(),
        ],
        materiality_fields: vec!["unknown materiality".to_string(), "market cap".to_string()],
        sample_size_hint: Some(500),
        ..DomainObservation::default()
    };
    let candidate = DomainCandidate::from_observations("vague_news".to_string(), vec![obs]);
    let scored = score_candidate(candidate, &Config::default());
    assert_ne!(scored.gate, GateDecision::FullLifecycle);
    assert!(scored.warnings.iter().any(|w| w.contains("timestamp")));
}

#[test]
fn mixed_slug_input_requires_slug_filter() {
    let observations = vec![
        DomainObservation {
            slug: "alpha".to_string(),
            title: "Alpha".to_string(),
            ..DomainObservation::default()
        },
        DomainObservation {
            slug: "beta".to_string(),
            title: "Beta".to_string(),
            ..DomainObservation::default()
        },
    ];

    let err = candidate_from_observations(observations, None).unwrap_err();
    assert!(err.to_string().contains("contains 2 domains"));
}

#[test]
fn mixed_slug_input_can_select_slug() {
    let observations = vec![
        DomainObservation {
            slug: "alpha".to_string(),
            title: "Alpha".to_string(),
            ..DomainObservation::default()
        },
        DomainObservation {
            slug: "beta".to_string(),
            title: "Beta".to_string(),
            ..DomainObservation::default()
        },
    ];

    let candidate = candidate_from_observations(observations, Some("beta")).unwrap();
    assert_eq!(candidate.slug, "beta");
    assert_eq!(candidate.observations.len(), 1);
}

#[test]
fn registry_parses_wide_table_by_header_names() {
    let text = r#"
| domain | status | stage_reached | stop_reason | commit | revisit_trigger |
| --- | --- | --- | --- | --- | --- |
| insider_purchase_clusters | frozen | causal rebuild | failed null-shuffle and concentration | b0923ce | new thesis only |
| cybersecurity_material_incidents_8k | underpowered_monitor | readiness | too few rows | 878db5f | 80 reviewed rows |
| bank_regulatory_enforcement | underpowered_feasibility | feasibility | low public-bank rows | cb53eba | source expansion |
"#;

    let registry = Registry::parse_markdown(text);
    let insider = registry.get("insider_purchase_clusters").unwrap();
    assert_eq!(insider.status, "frozen");
    assert_eq!(insider.stage_reached.as_deref(), Some("causal rebuild"));
    assert_eq!(
        insider.stop_reason.as_deref(),
        Some("failed null-shuffle and concentration")
    );
    assert_eq!(insider.revisit_trigger.as_deref(), Some("new thesis only"));

    let cyber = registry.get("cybersecurity_material_incidents_8k").unwrap();
    assert_eq!(cyber.status, "underpowered_monitor");

    let bank = registry.get("bank_regulatory_enforcement").unwrap();
    assert_eq!(bank.status, "underpowered_feasibility");
}

#[test]
fn registry_parses_reordered_columns() {
    let text = r#"
| status | revisit_trigger | domain | stop_reason |
| --- | --- | --- | --- |
| frozen | new thesis only | insider_purchase_clusters | failed causal rebuild |
"#;

    let registry = Registry::parse_markdown(text);
    let entry = registry.get("insider_purchase_clusters").unwrap();
    assert_eq!(entry.status, "frozen");
    assert_eq!(entry.stop_reason.as_deref(), Some("failed causal rebuild"));
    assert_eq!(entry.revisit_trigger.as_deref(), Some("new thesis only"));
}

#[test]
fn built_in_collectors_cover_multiple_source_families() {
    let observations = built_in_observations(None).unwrap();
    assert!(observations.len() >= 20);
    assert!(source_family_count(&observations) >= 3);
    assert!(observations.iter().all(|obs| obs.source_url.is_some()));
}

#[test]
fn built_in_collectors_can_select_one_family() {
    let observations = built_in_observations(Some("fda")).unwrap();
    assert!(observations.len() >= 3);
    assert!(observations
        .iter()
        .all(|obs| obs.tags.iter().any(|tag| tag == "collector:fda")));
}
