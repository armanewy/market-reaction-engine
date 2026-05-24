use domain_finder::collectors::{built_in_observations, source_family_count};
use domain_finder::config::Config;
use domain_finder::dashboard::{build_dashboard, DashboardOptions};
use domain_finder::model::{
    DomainCandidate, DomainObservation, GateDecision, RegistryEntry, ScoreCard, TimestampQuality,
};
use domain_finder::operations::{
    current_alerts, diff_candidates, explain_candidate, top_candidates,
};
use domain_finder::pipeline::candidate_from_observations;
use domain_finder::probes::{probe_family, ProbeOptions};
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
    assert_eq!(insider.last_commit.as_deref(), Some("b0923ce"));
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

#[test]
fn offline_probe_writes_dynamic_observations() {
    let temp_root =
        std::env::temp_dir().join(format!("domain_finder_probe_test_{}", std::process::id()));
    if temp_root.exists() {
        std::fs::remove_dir_all(&temp_root).unwrap();
    }
    std::fs::create_dir_all(&temp_root).unwrap();

    let output = probe_family(
        &temp_root,
        &ProbeOptions {
            family: "sec".to_string(),
            output_dir: None,
            timeout_secs: 1,
            offline: true,
        },
    )
    .unwrap();

    assert!(output.observations.len() >= 5);
    assert!(output.path.exists());
    assert!(output.report_path.exists());
    assert!(output
        .observations
        .iter()
        .all(|obs| obs.tags.iter().any(|tag| tag == "source_probe")));
    assert!(output
        .observations
        .iter()
        .all(|obs| obs.tags.iter().any(|tag| tag == "probe_status:offline")));

    std::fs::remove_dir_all(&temp_root).unwrap();
}

#[test]
fn top_suppresses_registry_blocked_domains() {
    let blocked = test_candidate(
        "insider_purchase_clusters",
        GateDecision::BlockedByRegistry,
        30,
        Some(test_registry("frozen", "new thesis only")),
    );
    let feasibility = test_candidate(
        "fda_import_alerts_public_companies",
        GateDecision::FeasibilityOnly,
        21,
        None,
    );

    let top = top_candidates(&[blocked, feasibility], 10);
    assert_eq!(top.len(), 1);
    assert_eq!(top[0].slug, "fda_import_alerts_public_companies");
}

#[test]
fn explain_includes_hard_minimum_failures() {
    let mut candidate = test_candidate("weak_source", GateDecision::Backlog, 18, None);
    candidate.score.public_timestamp_clarity = 1;
    candidate.score.delayed_digestion_plausibility = 1;
    candidate.score.materiality_field_clarity = 3;
    candidate.score.sample_size_likelihood = 0;

    let explanation = explain_candidate(&candidate);
    assert!(explanation
        .hard_minimum_failures
        .iter()
        .any(|failure| failure.contains("timestamp")));
    assert!(explanation
        .hard_minimum_failures
        .iter()
        .any(|failure| failure.contains("sample-size")));
}

#[test]
fn diff_detects_gate_and_revisit_trigger_changes() {
    let old = test_candidate(
        "cybersecurity_material_incidents_8k",
        GateDecision::Backlog,
        17,
        Some(test_registry("underpowered_monitor", "old trigger")),
    );
    let new = test_candidate(
        "cybersecurity_material_incidents_8k",
        GateDecision::MonitorOnly,
        25,
        Some(test_registry("underpowered_monitor", "new trigger")),
    );

    let diff = diff_candidates(&[old], &[new]);
    assert_eq!(diff.gate_changes.len(), 1);
    assert_eq!(diff.revisit_trigger_changes.len(), 1);
    assert_eq!(
        diff.newly_eligible_for_intake,
        vec!["cybersecurity_material_incidents_8k".to_string()]
    );
}

#[test]
fn alerts_suppress_frozen_and_surface_monitor_trigger() {
    let blocked = test_candidate(
        "capital_raise_dilution",
        GateDecision::BlockedByRegistry,
        27,
        Some(test_registry("frozen", "new thesis only")),
    );
    let monitor = test_candidate(
        "cybersecurity_material_incidents_8k",
        GateDecision::MonitorOnly,
        25,
        Some(test_registry("underpowered_monitor", "80 reviewed rows")),
    );

    let alerts = current_alerts(&[blocked, monitor]);
    assert_eq!(alerts.suppressed_blocked_count, 1);
    assert_eq!(alerts.alerts.len(), 1);
    assert_eq!(alerts.alerts[0].slug, "cybersecurity_material_incidents_8k");
    assert!(alerts.alerts[0]
        .recommended_next_action
        .contains("80 reviewed rows"));
}

#[test]
fn dashboard_build_classifies_canonical_registry_state() {
    let temp_root = std::env::temp_dir().join(format!(
        "domain_finder_dashboard_test_{}",
        std::process::id()
    ));
    if temp_root.exists() {
        std::fs::remove_dir_all(&temp_root).unwrap();
    }
    std::fs::create_dir_all(temp_root.join("docs")).unwrap();
    std::fs::write(
        temp_root.join("docs/DOMAIN_RESEARCH_REGISTRY.md"),
        r#"
| Domain | Status | Stage Reached | Stop Reason | Last Known Commit | Revisit Trigger |
| --- | --- | --- | --- | --- | --- |
| `cybersecurity_material_incidents_8k` | underpowered_monitor | monitor/readiness | Item 1.05 sample too small; 43 reviewed usable rows, 37 model-eligible rows, 0 likely OOS predictions | `878db5f` | Rerun when row gates pass. |
| `insider_purchase_clusters` | frozen | causal-feature rebuild/final audit | Failed empirical gate after leakage repair: feature leakage false after rebuild, null-shuffle h10 p-value 0.7143, liquid subset tickers 14, top-5 liquid ticker contribution 86.7397% | `b0923ce` | New pre-registered thesis only. |
| `bank_regulatory_enforcement` | underpowered_feasibility | source/corpus/readiness | Public-bank adverse corpus was too small: 28 reviewed usable rows and 0 likely OOS predictions | `cb53eba` | Source expansion required. |
"#,
    )
    .unwrap();

    let output = build_dashboard(&DashboardOptions {
        root: temp_root.clone(),
        out_dir: "artifacts/domain_finder/dashboard".into(),
        registry_path: None,
        candidates_path: None,
    })
    .unwrap();

    let cyber = output
        .state
        .domains
        .iter()
        .find(|domain| domain.slug == "cybersecurity_material_incidents_8k")
        .unwrap();
    assert_eq!(cyber.category, "monitor");

    let insider = output
        .state
        .domains
        .iter()
        .find(|domain| domain.slug == "insider_purchase_clusters")
        .unwrap();
    assert_eq!(insider.category, "frozen");
    assert_eq!(
        insider.key_metrics.get("null_shuffle_h10_p_value"),
        Some(&"0.7143".to_string())
    );

    let bank = output
        .state
        .domains
        .iter()
        .find(|domain| domain.slug == "bank_regulatory_enforcement")
        .unwrap();
    assert_eq!(bank.category, "feasibility");

    assert_eq!(output.state.summary.graduated_signals, 0);
    assert_eq!(output.state.summary.live_candidates, 0);
    assert_eq!(output.state.summary.monitors, 1);

    let html = std::fs::read_to_string(&output.index_path).unwrap();
    assert!(html.contains("Graduated Signals"));
    assert!(html.contains("insider_purchase_clusters"));

    let state_json = std::fs::read_to_string(&output.state_path).unwrap();
    let parsed: serde_json::Value = serde_json::from_str(&state_json).unwrap();
    assert_eq!(parsed["summary"]["monitors"], 1);

    std::fs::remove_dir_all(&temp_root).unwrap();
}

fn test_candidate(
    slug: &str,
    gate: GateDecision,
    total: u8,
    registry_status: Option<RegistryEntry>,
) -> DomainCandidate {
    DomainCandidate {
        slug: slug.to_string(),
        title: slug.to_string(),
        score: ScoreCard {
            total,
            public_timestamp_clarity: 3,
            delayed_digestion_plausibility: 3,
            materiality_field_clarity: 3,
            sample_size_likelihood: 3,
            ..ScoreCard::default()
        },
        gate,
        registry_status,
        observations: vec![DomainObservation {
            slug: slug.to_string(),
            title: slug.to_string(),
            ..DomainObservation::default()
        }],
        ..DomainCandidate::default()
    }
}

fn test_registry(status: &str, revisit_trigger: &str) -> RegistryEntry {
    RegistryEntry {
        domain: "test".to_string(),
        status: status.to_string(),
        stage_reached: Some("test".to_string()),
        stop_reason: Some("test stop".to_string()),
        last_commit: Some("test commit".to_string()),
        revisit_trigger: Some(revisit_trigger.to_string()),
    }
}
