use domain_finder::collectors::{built_in_observations, source_family_count};
use domain_finder::config::Config;
use domain_finder::dashboard::{build_dashboard, DashboardOptions};
use domain_finder::model::{
    DomainCandidate, DomainObservation, GateDecision, RegistryEntry, ScoreCard, TimestampQuality,
};
use domain_finder::operations::{
    current_alerts, diff_candidates, explain_candidate, top_candidates,
};
use domain_finder::orchestrator::{
    approve_job, complete_job, generate_research_prompt, reject_job, run_approved_jobs,
    run_orchestrator_once, CompleteJobOptions, JobStatus, OrchestratorConfig,
    OrchestratorRunOptions,
};
use domain_finder::pipeline::{candidate_from_observations, run_scan};
use domain_finder::probes::{probe_family, ProbeOptions};
use domain_finder::registry::Registry;
use domain_finder::report::intake_doc;
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
fn generated_intake_contains_mre_score_table() {
    let mut candidate = test_candidate(
        "material_customer_contract_loss_8k",
        GateDecision::FullLifecycle,
        25,
        None,
    );
    candidate.score.official_source_quality = 3;
    candidate.score.public_timestamp_clarity = 3;
    candidate.score.delayed_digestion_plausibility = 2;
    candidate.score.hard_negative_clarity = 2;
    candidate.score.materiality_field_clarity = 3;
    candidate.score.sample_size_likelihood = 2;
    candidate.score.ticker_mapping_feasibility = 3;
    candidate.score.liquidity_execution_feasibility = 3;
    candidate.score.parser_audit_feasibility = 2;
    candidate.score.fresh_data_availability = 2;

    let doc = intake_doc(&candidate);

    assert!(doc.contains("| Dimension | Score | Notes |"));
    assert!(doc.contains("| Official source quality | 3 |"));
    assert!(doc.contains("| Public timestamp clarity | 3 |"));
    assert!(doc.contains("| Delayed-digestion plausibility | 2 |"));
    assert!(doc.contains("| Fresh-data availability | 2 |"));
}

#[test]
fn orchestrator_once_queues_only_eligible_jobs_and_is_idempotent() {
    let temp_root = temp_root("domain_finder_orchestrator_once");
    write_orchestrator_fixture(&temp_root);

    let domain_config = Config::default();
    let orchestrator_config = test_orchestrator_config();

    let first = run_orchestrator_once(
        &temp_root,
        &domain_config,
        &orchestrator_config,
        OrchestratorRunOptions {
            dry_run: false,
            offline_probes: true,
            auto_mode: false,
        },
    )
    .unwrap();

    let domains = first
        .new_jobs
        .iter()
        .map(|job| job.domain.as_str())
        .collect::<Vec<_>>();
    assert!(domains.contains(&"material_customer_contract_loss_8k"));
    assert!(domains.contains(&"index_rebalance_events"));
    assert!(!domains.contains(&"insider_purchase_clusters"));
    assert!(!domains.contains(&"cybersecurity_material_incidents_8k"));
    assert_eq!(first.suppressed_blocked_count, 1);
    assert_eq!(first.monitor_only_count, 1);

    let material = first
        .new_jobs
        .iter()
        .find(|job| job.domain == "material_customer_contract_loss_8k")
        .unwrap();
    assert_eq!(material.status, JobStatus::AwaitingApproval);
    assert_eq!(material.scope, "full_lifecycle");

    let feasibility = first
        .new_jobs
        .iter()
        .find(|job| job.domain == "index_rebalance_events")
        .unwrap();
    assert_eq!(feasibility.scope, "source_feasibility_only");

    let second = run_orchestrator_once(
        &temp_root,
        &domain_config,
        &orchestrator_config,
        OrchestratorRunOptions {
            dry_run: false,
            offline_probes: true,
            auto_mode: false,
        },
    )
    .unwrap();
    assert!(second.new_jobs.is_empty());
    assert_eq!(second.existing_jobs.len(), first.new_jobs.len());
    assert!(first.notification_path.exists());

    std::fs::remove_dir_all(&temp_root).unwrap();
}

#[test]
fn approve_and_research_prompt_follow_human_gate() {
    let temp_root = temp_root("domain_finder_orchestrator_prompt");
    write_orchestrator_fixture(&temp_root);

    let domain_config = Config::default();
    let orchestrator_config = test_orchestrator_config();
    run_orchestrator_once(
        &temp_root,
        &domain_config,
        &orchestrator_config,
        OrchestratorRunOptions {
            dry_run: false,
            offline_probes: true,
            auto_mode: false,
        },
    )
    .unwrap();

    let err = generate_research_prompt(
        &temp_root,
        &orchestrator_config,
        "material_customer_contract_loss_8k",
        None,
    )
    .unwrap_err();
    assert!(err.to_string().contains("approve it before"));

    let approved = approve_job(
        &temp_root,
        &orchestrator_config,
        "material_customer_contract_loss_8k",
    )
    .unwrap();
    assert_eq!(approved.status, JobStatus::Approved);

    let prompted = generate_research_prompt(
        &temp_root,
        &orchestrator_config,
        "material_customer_contract_loss_8k",
        None,
    )
    .unwrap();
    assert_eq!(prompted.status, JobStatus::PromptGenerated);
    let prompt_path = prompted.prompt_path.as_ref().unwrap();
    let prompt = std::fs::read_to_string(prompt_path).unwrap();
    assert!(prompt.contains("Do not model until readiness gates pass."));
    assert!(prompt.contains("Domain Intake: Material Customer / Contract Loss 8-K"));
    assert!(prompt.contains("artifacts/material_customer_contract_loss_8k_domain_final_report.md"));

    std::fs::remove_dir_all(&temp_root).unwrap();
}

#[test]
fn reject_job_marks_terminal_reason_and_blocks_prompt() {
    let temp_root = temp_root("domain_finder_orchestrator_reject");
    write_orchestrator_fixture(&temp_root);

    let domain_config = Config::default();
    let orchestrator_config = test_orchestrator_config();
    run_orchestrator_once(
        &temp_root,
        &domain_config,
        &orchestrator_config,
        OrchestratorRunOptions {
            dry_run: false,
            offline_probes: true,
            auto_mode: false,
        },
    )
    .unwrap();

    let rejected = reject_job(
        &temp_root,
        &orchestrator_config,
        "index_rebalance_events",
        Some("not first priority"),
    )
    .unwrap();
    assert_eq!(rejected.status, JobStatus::Rejected);
    assert_eq!(
        rejected.terminal_reason.as_deref(),
        Some("not first priority")
    );

    let err = generate_research_prompt(
        &temp_root,
        &orchestrator_config,
        "index_rebalance_events",
        None,
    )
    .unwrap_err();
    assert!(err.to_string().contains("approve it before"));

    std::fs::remove_dir_all(&temp_root).unwrap();
}

#[test]
fn complete_job_marks_completed_and_appends_feedback() {
    let temp_root = temp_root("domain_finder_orchestrator_complete");
    write_orchestrator_fixture(&temp_root);

    let domain_config = Config::default();
    let orchestrator_config = test_orchestrator_config();
    run_orchestrator_once(
        &temp_root,
        &domain_config,
        &orchestrator_config,
        OrchestratorRunOptions {
            dry_run: false,
            offline_probes: true,
            auto_mode: false,
        },
    )
    .unwrap();
    approve_job(
        &temp_root,
        &orchestrator_config,
        "material_customer_contract_loss_8k",
    )
    .unwrap();
    generate_research_prompt(
        &temp_root,
        &orchestrator_config,
        "material_customer_contract_loss_8k",
        None,
    )
    .unwrap();

    let report =
        temp_root.join("artifacts/material_customer_contract_loss_8k_domain_final_report.md");
    let registry_update =
        temp_root.join("artifacts/material_customer_contract_loss_8k_registry_update.json");
    std::fs::create_dir_all(report.parent().unwrap()).unwrap();
    std::fs::write(&report, "# Final report\n").unwrap();
    std::fs::write(
        &registry_update,
        r#"{
  "domain": "material_customer_contract_loss_8k",
  "status": "parser not trusted",
  "stage_reached": "parser/readiness",
  "stop_reason": "no audited positives"
}"#,
    )
    .unwrap();
    let summary_dir = temp_root.join("data/events/material_customer_contract_loss_8k");
    std::fs::create_dir_all(&summary_dir).unwrap();
    std::fs::write(
        summary_dir.join("run_summary.json"),
        r#"{
  "source_rows": 191,
  "parsed_rows": 191,
  "event_type_counts": {
    "material_customer_loss": 1,
    "contract_termination": 0
  }
}"#,
    )
    .unwrap();

    let (job, feedback) = complete_job(
        &temp_root,
        &orchestrator_config,
        "material_customer_contract_loss_8k",
        CompleteJobOptions {
            final_status: "parser_not_trusted".to_string(),
            report_path: report.clone(),
            registry_update_path: registry_update.clone(),
            audited_true_positive_rows: Some(0),
            reviewed_usable_rows: Some(0),
            likely_oos: Some(0),
            ..CompleteJobOptions::default()
        },
    )
    .unwrap();

    assert_eq!(job.status, JobStatus::Completed);
    assert_eq!(job.final_status.as_deref(), Some("parser_not_trusted"));
    assert_eq!(feedback.source_rows, Some(191));
    assert_eq!(feedback.machine_positive_rows, Some(1));
    assert_eq!(feedback.audited_true_positive_rows, Some(0));
    assert_eq!(
        feedback.stop_reason.as_deref(),
        Some("no audited positives")
    );

    let feedback_path = temp_root.join("artifacts/orchestrator/domain_feedback.jsonl");
    let feedback_text = std::fs::read_to_string(feedback_path).unwrap();
    assert!(feedback_text.contains("\"domain\":\"material_customer_contract_loss_8k\""));
    assert!(feedback_text.contains("\"audited_true_positive_rows\":0"));

    std::fs::remove_dir_all(&temp_root).unwrap();
}

#[test]
fn auto_mode_auto_approves_one_registry_clear_candidate() {
    let temp_root = temp_root("domain_finder_orchestrator_auto");
    write_orchestrator_fixture(&temp_root);

    let domain_config = Config::default();
    let mut orchestrator_config = test_orchestrator_config();
    orchestrator_config.approval.auto_approve = true;
    orchestrator_config.approval.max_new_jobs_per_run = 1;
    orchestrator_config.approval.max_active_jobs = 1;
    orchestrator_config.limits.max_active_jobs = 1;

    let output = run_orchestrator_once(
        &temp_root,
        &domain_config,
        &orchestrator_config,
        OrchestratorRunOptions {
            dry_run: false,
            offline_probes: true,
            auto_mode: true,
        },
    )
    .unwrap();

    assert_eq!(output.new_jobs.len(), 1);
    let job = &output.new_jobs[0];
    assert_eq!(job.domain, "material_customer_contract_loss_8k");
    assert_eq!(job.status, JobStatus::PromptGenerated);
    assert!(job.prompt_path.is_some());

    let run_again = run_orchestrator_once(
        &temp_root,
        &domain_config,
        &orchestrator_config,
        OrchestratorRunOptions {
            dry_run: false,
            offline_probes: true,
            auto_mode: true,
        },
    )
    .unwrap();
    assert!(run_again.new_jobs.is_empty());

    std::fs::remove_dir_all(&temp_root).unwrap();
}

#[test]
fn run_approved_generates_prompt_without_launching_manual_runner() {
    let temp_root = temp_root("domain_finder_run_approved");
    write_orchestrator_fixture(&temp_root);

    let domain_config = Config::default();
    let orchestrator_config = test_orchestrator_config();
    run_orchestrator_once(
        &temp_root,
        &domain_config,
        &orchestrator_config,
        OrchestratorRunOptions {
            dry_run: false,
            offline_probes: true,
            auto_mode: false,
        },
    )
    .unwrap();
    approve_job(
        &temp_root,
        &orchestrator_config,
        "material_customer_contract_loss_8k",
    )
    .unwrap();

    let jobs = run_approved_jobs(&temp_root, &orchestrator_config).unwrap();
    assert_eq!(jobs.len(), 1);
    assert_eq!(jobs[0].status, JobStatus::PromptGenerated);
    assert!(jobs[0].prompt_path.is_some());

    std::fs::remove_dir_all(&temp_root).unwrap();
}

#[test]
fn safe_registry_update_auto_applies_but_candidate_signal_does_not() {
    let temp_root = temp_root("domain_finder_safe_registry_update");
    write_orchestrator_fixture(&temp_root);

    let domain_config = Config::default();
    let mut orchestrator_config = test_orchestrator_config();
    orchestrator_config
        .registry_updates
        .auto_apply_safe_terminal_statuses = true;

    run_orchestrator_once(
        &temp_root,
        &domain_config,
        &orchestrator_config,
        OrchestratorRunOptions {
            dry_run: false,
            offline_probes: true,
            auto_mode: false,
        },
    )
    .unwrap();

    let report =
        temp_root.join("artifacts/material_customer_contract_loss_8k_domain_final_report.md");
    let registry_update =
        temp_root.join("artifacts/material_customer_contract_loss_8k_registry_update.json");
    std::fs::create_dir_all(report.parent().unwrap()).unwrap();
    std::fs::write(&report, "# Final report\n").unwrap();
    std::fs::write(
        &registry_update,
        r#"{
  "domain": "material_customer_contract_loss_8k",
  "status": "parser_not_trusted",
  "stage_reached": "parser/readiness",
  "stop_reason": "no audited positives"
}"#,
    )
    .unwrap();
    complete_job(
        &temp_root,
        &orchestrator_config,
        "material_customer_contract_loss_8k",
        CompleteJobOptions {
            final_status: "parser_not_trusted".to_string(),
            report_path: report,
            registry_update_path: registry_update,
            ..CompleteJobOptions::default()
        },
    )
    .unwrap();

    let registry_text =
        std::fs::read_to_string(temp_root.join("docs/DOMAIN_RESEARCH_REGISTRY.md")).unwrap();
    assert!(registry_text.contains("## Automated Registry Updates"));
    assert!(registry_text.contains("material_customer_contract_loss_8k | parser_not_trusted"));

    approve_job(&temp_root, &orchestrator_config, "index_rebalance_events").unwrap();
    generate_research_prompt(
        &temp_root,
        &orchestrator_config,
        "index_rebalance_events",
        None,
    )
    .unwrap();
    let signal_report = temp_root.join("artifacts/index_rebalance_events_domain_final_report.md");
    let signal_update = temp_root.join("artifacts/index_rebalance_events_registry_update.json");
    std::fs::write(&signal_report, "# Signal report\n").unwrap();
    std::fs::write(
        &signal_update,
        r#"{
  "domain": "index_rebalance_events",
  "status": "candidate_paper_signal",
  "stage_reached": "final_audit",
  "stop_reason": "paper signal requires human review"
}"#,
    )
    .unwrap();
    complete_job(
        &temp_root,
        &orchestrator_config,
        "index_rebalance_events",
        CompleteJobOptions {
            final_status: "candidate_paper_signal".to_string(),
            report_path: signal_report,
            registry_update_path: signal_update,
            ..CompleteJobOptions::default()
        },
    )
    .unwrap();

    let registry_text =
        std::fs::read_to_string(temp_root.join("docs/DOMAIN_RESEARCH_REGISTRY.md")).unwrap();
    assert!(!registry_text.contains("index_rebalance_events | candidate_paper_signal"));

    std::fs::remove_dir_all(&temp_root).unwrap();
}

#[test]
fn low_true_positive_feedback_downranks_same_domain() {
    let temp_root = temp_root("domain_finder_feedback_penalty");
    write_orchestrator_fixture(&temp_root);
    std::fs::create_dir_all(temp_root.join("artifacts/orchestrator")).unwrap();
    std::fs::write(
        temp_root.join("artifacts/orchestrator/domain_feedback.jsonl"),
        r#"{"domain":"material_customer_contract_loss_8k","status":"parser_not_trusted","stage_reached":"parser/readiness","source_rows":191,"parsed_rows":191,"machine_positive_rows":1,"audited_true_positive_rows":0,"reviewed_usable_rows":0,"likely_oos":0,"stop_reason":"no audited positives","report_path":"report.md","registry_update_path":"update.json","timestamp":"2026-05-24T00:00:00Z"}"#,
    )
    .unwrap();

    let output = run_scan(&temp_root, &Config::default()).unwrap();
    let candidate = output
        .candidates
        .iter()
        .find(|candidate| candidate.slug == "material_customer_contract_loss_8k")
        .unwrap();
    assert_ne!(candidate.gate, GateDecision::FullLifecycle);
    assert!(candidate
        .warnings
        .iter()
        .any(|warning| warning.contains("low true-positive yield")));

    std::fs::remove_dir_all(&temp_root).unwrap();
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
    let jobs_dir = temp_root.join("artifacts/orchestrator/jobs");
    std::fs::create_dir_all(&jobs_dir).unwrap();
    std::fs::write(
        jobs_dir.join("ferc_utility_enforcement_actions.json"),
        r#"{
  "domain": "ferc_utility_enforcement_actions",
  "title": "FERC Utility Enforcement Actions",
  "status": "awaiting_approval",
  "score": 24,
  "decision": "full_lifecycle",
  "scope": "full_lifecycle",
  "intake_path": "docs/intakes/generated/ferc_utility_enforcement_actions.md",
  "prompt_path": null,
  "created_at": "2026-05-24T19:33:32Z",
  "updated_at": "2026-05-24T19:33:32Z",
  "next_action": "review intake and approve research run",
  "registry_status": null,
  "registry_stop_reason": null,
  "registry_revisit_trigger": null
}"#,
    )
    .unwrap();
    let notifications_dir = temp_root.join("artifacts/orchestrator/notifications");
    std::fs::create_dir_all(&notifications_dir).unwrap();
    std::fs::write(
        notifications_dir.join("latest.md"),
        "# Domain Finder Orchestrator Notification\n\n- new jobs queued: `1`\n",
    )
    .unwrap();
    let history_dir = temp_root.join("artifacts/orchestrator/history");
    std::fs::create_dir_all(&history_dir).unwrap();
    std::fs::write(history_dir.join("20260524T193332Z_jobs.json"), "{}").unwrap();

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
    assert_eq!(output.state.orchestrator.awaiting_approval_jobs, 1);
    assert_eq!(output.state.orchestrator.history_count, 1);
    assert_eq!(
        output.state.orchestrator.jobs[0].domain,
        "ferc_utility_enforcement_actions"
    );

    let html = std::fs::read_to_string(&output.index_path).unwrap();
    assert!(html.contains("Graduated Signals"));
    assert!(html.contains("insider_purchase_clusters"));
    assert!(html.contains("Orchestrator"));
    assert!(html.contains("ferc_utility_enforcement_actions"));
    assert!(html.contains("notification-card"));
    assert!(html.contains("<h3>Domain Finder Orchestrator Notification</h3>"));
    assert!(html.contains("<li>new jobs queued: <code>1</code></li>"));

    let state_json = std::fs::read_to_string(&output.state_path).unwrap();
    let parsed: serde_json::Value = serde_json::from_str(&state_json).unwrap();
    assert_eq!(parsed["summary"]["monitors"], 1);
    assert_eq!(parsed["orchestrator"]["awaiting_approval_jobs"], 1);

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

fn temp_root(prefix: &str) -> std::path::PathBuf {
    let root = std::env::temp_dir().join(format!("{}_{}", prefix, std::process::id()));
    if root.exists() {
        std::fs::remove_dir_all(&root).unwrap();
    }
    std::fs::create_dir_all(root.join("data/observations")).unwrap();
    std::fs::create_dir_all(root.join("docs")).unwrap();
    root
}

fn write_orchestrator_fixture(root: &std::path::Path) {
    std::fs::write(
        root.join("docs/DOMAIN_RESEARCH_REGISTRY.md"),
        r#"
| domain | status | stage_reached | stop_reason | commit | revisit_trigger |
| --- | --- | --- | --- | --- | --- |
| insider_purchase_clusters | frozen | causal rebuild | failed after causal rebuild | b0923ce | new thesis only |
| cybersecurity_material_incidents_8k | underpowered_monitor | monitor | too few rows | 878db5f | 80 reviewed rows |
"#,
    )
    .unwrap();

    let observations = [
        orchestrator_observation("material_customer_contract_loss_8k", true, 120),
        orchestrator_observation("insider_purchase_clusters", true, 200),
        orchestrator_observation("cybersecurity_material_incidents_8k", true, 120),
        orchestrator_observation("index_rebalance_events", false, 150),
    ];
    let jsonl = observations
        .iter()
        .map(|obs| serde_json::to_string(obs).unwrap())
        .collect::<Vec<_>>()
        .join("\n");
    std::fs::write(root.join("data/observations/domains.jsonl"), jsonl).unwrap();
}

fn orchestrator_observation(
    slug: &str,
    official_source: bool,
    sample_size_hint: u32,
) -> DomainObservation {
    DomainObservation {
        slug: slug.to_string(),
        title: match slug {
            "material_customer_contract_loss_8k" => "Material Customer / Contract Loss 8-K",
            "insider_purchase_clusters" => "Form 4 Insider Purchase Clusters",
            "cybersecurity_material_incidents_8k" => {
                "SEC Item 1.05 Material Cybersecurity Incidents"
            }
            "index_rebalance_events" => "Index Rebalance Events",
            _ => slug,
        }
        .to_string(),
        source_name: if official_source {
            "SEC EDGAR"
        } else {
            "Index provider"
        }
        .to_string(),
        source_kind: if official_source {
            "sec_official"
        } else {
            "public_index_announcement"
        }
        .to_string(),
        official_source,
        timestamp_quality: TimestampQuality::Clear,
        delayed_digest_reasons: vec![
            "financial impact requires calculation".to_string(),
            "market may digest follow-up details over several sessions".to_string(),
        ],
        hard_negatives: vec![
            "routine update".to_string(),
            "already-known event".to_string(),
            "duplicate disclosure".to_string(),
            "immaterial event".to_string(),
        ],
        materiality_fields: vec![
            "impact_pct_market_cap".to_string(),
            "market_cap_before_event".to_string(),
            "revenue_exposure".to_string(),
        ],
        mapping_notes: Some("clean issuer or ticker mapping".to_string()),
        sample_size_hint: Some(sample_size_hint),
        liquidity_notes: Some("liquidity filters required".to_string()),
        evidence: vec![
            "source-backed observation".to_string(),
            "timestamped source".to_string(),
            "public companies".to_string(),
        ],
        ..DomainObservation::default()
    }
}

fn test_orchestrator_config() -> OrchestratorConfig {
    let mut config = OrchestratorConfig::default();
    config.paths.mre_root = ".".to_string();
    config.automation.run_collectors = false;
    config.automation.run_probes = false;
    config.loop_config.max_new_jobs_per_run = 10;
    config.limits.max_active_jobs = 10;
    config
}
