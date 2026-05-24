use crate::collectors::collect_to_generated_dir;
use crate::config::Config;
use crate::dashboard::{build_dashboard, DashboardOptions};
use crate::io::{ensure_dir, rel, write_string};
use crate::model::{DomainCandidate, GateDecision};
use crate::pipeline::run_scan;
use crate::probes::{probe_family, ProbeOptions};
use crate::report::intake_doc;
use anyhow::Context;
use chrono::{DateTime, Duration, Utc};
use serde::{Deserialize, Serialize};
use std::fs;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::Command;

const PROBE_FAMILIES: [&str; 5] = ["sec", "agency", "fda", "litigation", "index"];

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct OrchestratorConfig {
    #[serde(default)]
    pub paths: OrchestratorPaths,
    #[serde(default, rename = "loop")]
    pub loop_config: OrchestratorLoop,
    #[serde(default)]
    pub thresholds: OrchestratorThresholds,
    #[serde(default)]
    pub automation: OrchestratorAutomation,
    #[serde(default)]
    pub notifications: OrchestratorNotifications,
    #[serde(default)]
    pub approval: ApprovalPolicy,
    #[serde(default)]
    pub runner: RunnerConfig,
    #[serde(default)]
    pub registry_updates: RegistryUpdateConfig,
    #[serde(default)]
    pub limits: OrchestratorLimits,
    #[serde(default)]
    pub review: ReviewPolicy,
}

impl OrchestratorConfig {
    pub fn load(path: &Path) -> anyhow::Result<Self> {
        let text = fs::read_to_string(path)
            .with_context(|| format!("failed to read orchestrator config {}", path.display()))?;
        toml::from_str(&text)
            .with_context(|| format!("failed to parse orchestrator config {}", path.display()))
    }

    pub fn default_path(root: &Path) -> PathBuf {
        root.join("config/orchestrator.toml")
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrchestratorPaths {
    #[serde(default = "default_mre_root")]
    pub mre_root: String,
    #[serde(default = "default_domain_finder_root")]
    pub domain_finder_root: String,
    #[serde(default = "default_jobs_dir")]
    pub jobs_dir: String,
    #[serde(default = "default_notifications_dir")]
    pub notifications_dir: String,
    #[serde(default = "default_prompts_dir")]
    pub prompts_dir: String,
    #[serde(default = "default_feedback_path")]
    pub feedback_path: String,
    #[serde(default = "default_history_dir")]
    pub history_dir: String,
    #[serde(default = "default_dashboard_out_dir")]
    pub dashboard_out_dir: String,
    #[serde(default = "default_reviews_dir")]
    pub reviews_dir: String,
}

impl Default for OrchestratorPaths {
    fn default() -> Self {
        Self {
            mre_root: default_mre_root(),
            domain_finder_root: default_domain_finder_root(),
            jobs_dir: default_jobs_dir(),
            notifications_dir: default_notifications_dir(),
            prompts_dir: default_prompts_dir(),
            feedback_path: default_feedback_path(),
            history_dir: default_history_dir(),
            dashboard_out_dir: default_dashboard_out_dir(),
            reviews_dir: default_reviews_dir(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrchestratorLoop {
    #[serde(default = "default_interval_secs")]
    pub interval_secs: u64,
    #[serde(default = "default_max_new_jobs")]
    pub max_new_jobs_per_run: usize,
    #[serde(default = "default_require_human_approval")]
    pub require_human_approval: bool,
    #[serde(default = "default_stale_after_hours")]
    pub stale_after_hours: i64,
}

impl Default for OrchestratorLoop {
    fn default() -> Self {
        Self {
            interval_secs: default_interval_secs(),
            max_new_jobs_per_run: default_max_new_jobs(),
            require_human_approval: default_require_human_approval(),
            stale_after_hours: default_stale_after_hours(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrchestratorThresholds {
    #[serde(default = "default_full_lifecycle_score")]
    pub full_lifecycle_score: u8,
    #[serde(default = "default_feasibility_score")]
    pub feasibility_score: u8,
}

impl Default for OrchestratorThresholds {
    fn default() -> Self {
        Self {
            full_lifecycle_score: default_full_lifecycle_score(),
            feasibility_score: default_feasibility_score(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrchestratorAutomation {
    #[serde(default = "default_true")]
    pub auto_generate_intakes: bool,
    #[serde(default)]
    pub auto_approve_full_lifecycle: bool,
    #[serde(default)]
    pub auto_run_agents: bool,
    #[serde(default)]
    pub auto_update_registry: bool,
    #[serde(default = "default_true")]
    pub run_collectors: bool,
    #[serde(default = "default_true")]
    pub run_probes: bool,
}

impl Default for OrchestratorAutomation {
    fn default() -> Self {
        Self {
            auto_generate_intakes: true,
            auto_approve_full_lifecycle: false,
            auto_run_agents: false,
            auto_update_registry: false,
            run_collectors: true,
            run_probes: true,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrchestratorNotifications {
    #[serde(default = "default_notification_mode")]
    pub mode: String,
    #[serde(default = "default_notify_on")]
    pub notify_on: Vec<String>,
    #[serde(default = "default_true")]
    pub suppress_routine_failures: bool,
}

impl Default for OrchestratorNotifications {
    fn default() -> Self {
        Self {
            mode: default_notification_mode(),
            notify_on: default_notify_on(),
            suppress_routine_failures: true,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ApprovalPolicy {
    #[serde(default)]
    pub auto_approve: bool,
    #[serde(default = "default_full_lifecycle_score")]
    pub min_full_lifecycle_score: u8,
    #[serde(default = "default_feasibility_score")]
    pub min_feasibility_score: u8,
    #[serde(default = "default_true")]
    pub require_registry_clear: bool,
    #[serde(default = "default_true")]
    pub allow_full_lifecycle: bool,
    #[serde(default = "default_true")]
    pub allow_feasibility_only: bool,
    #[serde(default = "default_one_usize")]
    pub max_new_jobs_per_run: usize,
    #[serde(default = "default_one_usize")]
    pub max_active_jobs: usize,
}

impl Default for ApprovalPolicy {
    fn default() -> Self {
        Self {
            auto_approve: false,
            min_full_lifecycle_score: default_full_lifecycle_score(),
            min_feasibility_score: default_feasibility_score(),
            require_registry_clear: true,
            allow_full_lifecycle: true,
            allow_feasibility_only: true,
            max_new_jobs_per_run: 1,
            max_active_jobs: 1,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RunnerConfig {
    #[serde(default = "default_runner_mode")]
    pub mode: String,
    #[serde(default)]
    pub command: String,
    #[serde(default)]
    pub args: Vec<String>,
}

impl Default for RunnerConfig {
    fn default() -> Self {
        Self {
            mode: default_runner_mode(),
            command: String::new(),
            args: Vec::new(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RegistryUpdateConfig {
    #[serde(default)]
    pub auto_apply_safe_terminal_statuses: bool,
    #[serde(default = "default_true")]
    pub require_valid_json: bool,
    #[serde(default = "default_true")]
    pub require_final_report: bool,
    #[serde(default)]
    pub auto_apply_candidate_paper_signal: bool,
    #[serde(default = "default_safe_registry_statuses")]
    pub safe_statuses: Vec<String>,
    #[serde(default = "default_notify_only_statuses")]
    pub notify_only_statuses: Vec<String>,
}

impl Default for RegistryUpdateConfig {
    fn default() -> Self {
        Self {
            auto_apply_safe_terminal_statuses: false,
            require_valid_json: true,
            require_final_report: true,
            auto_apply_candidate_paper_signal: false,
            safe_statuses: default_safe_registry_statuses(),
            notify_only_statuses: default_notify_only_statuses(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrchestratorLimits {
    #[serde(default = "default_one_usize")]
    pub max_active_jobs: usize,
    #[serde(default = "default_one_usize")]
    pub max_new_jobs_per_day: usize,
    #[serde(default = "default_three_usize")]
    pub max_research_runs_per_week: usize,
    #[serde(default = "default_one_usize")]
    pub max_retries_per_job: usize,
}

impl Default for OrchestratorLimits {
    fn default() -> Self {
        Self {
            max_active_jobs: 1,
            max_new_jobs_per_day: 1,
            max_research_runs_per_week: 3,
            max_retries_per_job: 1,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReviewPolicy {
    #[serde(default = "default_true")]
    pub enabled: bool,
    #[serde(default = "default_true")]
    pub require_registry_clear: bool,
    #[serde(default = "default_true")]
    pub require_live_probe: bool,
    #[serde(default = "default_true")]
    pub reject_static_or_offline_only: bool,
    #[serde(default = "default_full_lifecycle_score")]
    pub min_full_lifecycle_score: u8,
    #[serde(default = "default_feasibility_score")]
    pub min_feasibility_score: u8,
    #[serde(default = "default_two_usize")]
    pub min_delayed_digest_reasons: usize,
    #[serde(default = "default_three_usize")]
    pub min_hard_negatives: usize,
    #[serde(default = "default_two_usize")]
    pub min_materiality_fields: usize,
    #[serde(default = "default_two_u8")]
    pub min_mapping_score: u8,
    #[serde(default = "default_two_u8")]
    pub min_parser_score: u8,
    #[serde(default = "default_two_u8")]
    pub min_sample_score: u8,
    #[serde(default = "default_three_u8")]
    pub min_timestamp_score: u8,
}

impl Default for ReviewPolicy {
    fn default() -> Self {
        Self {
            enabled: true,
            require_registry_clear: true,
            require_live_probe: true,
            reject_static_or_offline_only: true,
            min_full_lifecycle_score: default_full_lifecycle_score(),
            min_feasibility_score: default_feasibility_score(),
            min_delayed_digest_reasons: 2,
            min_hard_negatives: 3,
            min_materiality_fields: 2,
            min_mapping_score: 2,
            min_parser_score: 2,
            min_sample_score: 2,
            min_timestamp_score: 3,
        }
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, Eq, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum JobStatus {
    Discovered,
    IntakeGenerated,
    IntakeScored,
    AwaitingApproval,
    Approved,
    PromptGenerated,
    Running,
    Failed,
    Stale,
    RetryPending,
    Rejected,
    Completed,
    Archived,
}

impl JobStatus {
    pub fn label(self) -> &'static str {
        match self {
            JobStatus::Discovered => "discovered",
            JobStatus::IntakeGenerated => "intake_generated",
            JobStatus::IntakeScored => "intake_scored",
            JobStatus::AwaitingApproval => "awaiting_approval",
            JobStatus::Approved => "approved",
            JobStatus::PromptGenerated => "prompt_generated",
            JobStatus::Running => "running",
            JobStatus::Failed => "failed",
            JobStatus::Stale => "stale",
            JobStatus::RetryPending => "retry_pending",
            JobStatus::Rejected => "rejected",
            JobStatus::Completed => "completed",
            JobStatus::Archived => "archived",
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrchestratorJob {
    pub domain: String,
    pub title: String,
    pub status: JobStatus,
    pub score: u8,
    pub decision: GateDecision,
    pub scope: String,
    pub intake_path: String,
    pub prompt_path: Option<String>,
    pub created_at: String,
    pub updated_at: String,
    pub next_action: String,
    #[serde(default)]
    pub terminal_reason: Option<String>,
    #[serde(default)]
    pub final_status: Option<String>,
    #[serde(default)]
    pub report_path: Option<String>,
    #[serde(default)]
    pub registry_update_path: Option<String>,
    pub registry_status: Option<String>,
    pub registry_stop_reason: Option<String>,
    pub registry_revisit_trigger: Option<String>,
}

#[derive(Debug, Clone, Default)]
pub struct CompleteJobOptions {
    pub final_status: String,
    pub report_path: PathBuf,
    pub registry_update_path: PathBuf,
    pub reason: Option<String>,
    pub source_rows: Option<u64>,
    pub parsed_rows: Option<u64>,
    pub machine_positive_rows: Option<u64>,
    pub audited_true_positive_rows: Option<u64>,
    pub reviewed_usable_rows: Option<u64>,
    pub likely_oos: Option<u64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DomainFeedback {
    pub domain: String,
    pub status: String,
    pub stage_reached: Option<String>,
    pub source_rows: Option<u64>,
    pub parsed_rows: Option<u64>,
    pub machine_positive_rows: Option<u64>,
    pub audited_true_positive_rows: Option<u64>,
    pub reviewed_usable_rows: Option<u64>,
    pub likely_oos: Option<u64>,
    pub stop_reason: Option<String>,
    pub report_path: String,
    pub registry_update_path: String,
    pub timestamp: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReviewJobsOutput {
    pub reviewed_at: String,
    pub reviews: Vec<JobReview>,
    pub approved: Vec<OrchestratorJob>,
    pub rejected: Vec<OrchestratorJob>,
    pub prompts_generated: Vec<OrchestratorJob>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JobReview {
    pub domain: String,
    pub decision: String,
    pub confidence: String,
    pub job_status_before: String,
    pub job_status_after: Option<String>,
    pub score: Option<u8>,
    pub gate: Option<String>,
    pub reasons: Vec<String>,
    pub required_next_step: String,
    pub reviewed_at: String,
}

#[derive(Debug, Clone, Copy, Default)]
pub struct ReviewJobsOptions {
    pub dry_run: bool,
    pub run_approved: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrchestratorRunOutput {
    pub candidates_seen: usize,
    pub new_jobs: Vec<OrchestratorJob>,
    pub existing_jobs: Vec<OrchestratorJob>,
    pub suppressed_blocked_count: usize,
    pub monitor_only_count: usize,
    pub notification_path: PathBuf,
    pub jobs_dir: PathBuf,
}

#[derive(Debug, Clone, Copy, Default)]
pub struct OrchestratorRunOptions {
    pub dry_run: bool,
    pub offline_probes: bool,
    pub auto_mode: bool,
}

pub fn run_orchestrator_once(
    root: &Path,
    domain_config: &Config,
    orchestrator_config: &OrchestratorConfig,
    options: OrchestratorRunOptions,
) -> anyhow::Result<OrchestratorRunOutput> {
    let paths = ResolvedPaths::new(root, orchestrator_config);
    ensure_orchestrator_dirs(&paths)?;

    if orchestrator_config.automation.run_collectors && !options.dry_run {
        collect_to_generated_dir(root, None, None)?;
    }

    if orchestrator_config.automation.run_probes && !options.dry_run {
        for family in PROBE_FAMILIES {
            probe_family(
                root,
                &ProbeOptions {
                    family: family.to_string(),
                    output_dir: None,
                    timeout_secs: 10,
                    offline: options.offline_probes,
                },
            )?;
        }
    }

    if !options.dry_run {
        mark_stale_jobs(root, orchestrator_config)?;
        ingest_completion_artifacts(root, orchestrator_config)?;
    }

    let scan = run_scan(root, domain_config)?;

    let existing_jobs = load_jobs(&paths.jobs_dir)?;
    let mut active_jobs = active_job_count(&existing_jobs);
    let mut existing_domains = existing_jobs
        .iter()
        .map(|job| job.domain.clone())
        .collect::<Vec<_>>();
    existing_domains.sort();
    existing_domains.dedup();

    let mut new_jobs = Vec::new();
    let mut suppressed_blocked_count = 0usize;
    let mut monitor_only_count = 0usize;

    for candidate in &scan.candidates {
        match candidate.gate {
            GateDecision::BlockedByRegistry => {
                suppressed_blocked_count += 1;
                continue;
            }
            GateDecision::MonitorOnly => {
                monitor_only_count += 1;
                continue;
            }
            GateDecision::FullLifecycle | GateDecision::FeasibilityOnly => {}
            GateDecision::Backlog | GateDecision::Skip => continue,
        }

        let max_active_jobs = effective_max_active_jobs(orchestrator_config, options.auto_mode);
        if active_jobs >= max_active_jobs {
            continue;
        }
        if !passes_orchestrator_thresholds(candidate, orchestrator_config) {
            continue;
        }
        if options.auto_mode && !passes_auto_approval(candidate, orchestrator_config) {
            continue;
        }
        if existing_domains
            .iter()
            .any(|domain| domain == &candidate.slug)
        {
            continue;
        }
        if new_jobs.len() >= effective_max_new_jobs(orchestrator_config, options.auto_mode) {
            break;
        }

        let intake_path = paths
            .mre_root
            .join("docs/intakes/generated")
            .join(format!("{}.md", candidate.slug));
        if orchestrator_config.automation.auto_generate_intakes && !options.dry_run {
            write_string(&intake_path, &intake_doc(candidate))?;
        }

        let mut job = job_from_candidate(candidate, &intake_path);
        if should_auto_approve_job(candidate, orchestrator_config, options.auto_mode) {
            job.status = JobStatus::Approved;
            job.next_action = "generate research prompt".to_string();
        }

        if !options.dry_run {
            write_job(&paths.jobs_dir, &job)?;
            if matches!(job.status, JobStatus::Approved) {
                job = generate_research_prompt(root, orchestrator_config, &job.domain, None)?;
                if orchestrator_config.automation.auto_run_agents {
                    job = run_one_prompted_job(root, orchestrator_config, &job.domain)?;
                }
            }
        }
        existing_domains.push(job.domain.clone());
        if !is_terminal_status(job.status) {
            active_jobs += 1;
        }
        new_jobs.push(job);
    }

    let current_jobs = load_jobs(&paths.jobs_dir)?;
    let notification = notification_markdown(
        &new_jobs,
        &current_jobs,
        suppressed_blocked_count,
        monitor_only_count,
    );
    let notification_path = paths.notifications_dir.join("latest.md");
    if !options.dry_run {
        write_string(&notification_path, &notification)?;
        write_history_snapshot(&paths, &current_jobs)?;
        write_notification_digest(&paths, &current_jobs)?;
        refresh_dashboard(root, orchestrator_config);
    }

    Ok(OrchestratorRunOutput {
        candidates_seen: scan.candidates.len(),
        new_jobs,
        existing_jobs,
        suppressed_blocked_count,
        monitor_only_count,
        notification_path,
        jobs_dir: paths.jobs_dir,
    })
}

pub fn review_jobs(
    root: &Path,
    domain_config: &Config,
    config: &OrchestratorConfig,
    options: ReviewJobsOptions,
) -> anyhow::Result<ReviewJobsOutput> {
    let paths = ResolvedPaths::new(root, config);
    ensure_orchestrator_dirs(&paths)?;

    let scan = run_scan(root, domain_config)?;
    let reviewed_at = Utc::now().to_rfc3339();
    let jobs = load_jobs(&paths.jobs_dir)?;
    let mut reviews = Vec::new();
    let mut approved = Vec::new();
    let mut rejected = Vec::new();

    for job in jobs.iter().filter(|job| {
        matches!(
            job.status,
            JobStatus::AwaitingApproval | JobStatus::IntakeScored
        )
    }) {
        let candidate = scan
            .candidates
            .iter()
            .find(|candidate| candidate.slug == job.domain);
        let mut review = automated_job_review(job, candidate, config, &reviewed_at);

        if review.decision == "approve" {
            if !options.dry_run {
                let updated = approve_job(root, config, &job.domain)?;
                review.job_status_after = Some(updated.status.label().to_string());
                approved.push(updated);
            }
        } else if !options.dry_run {
            let reason = review.reasons.join("; ");
            let updated = reject_job(root, config, &job.domain, Some(&reason))?;
            review.job_status_after = Some(updated.status.label().to_string());
            rejected.push(updated);
        }

        if !options.dry_run {
            write_review_artifact(&paths, &review)?;
        }
        reviews.push(review);
    }

    let prompts_generated = if options.run_approved && !options.dry_run {
        run_approved_jobs(root, config)?
    } else {
        Vec::new()
    };

    if !options.dry_run {
        let current_jobs = load_jobs(&paths.jobs_dir)?;
        write_history_snapshot(&paths, &current_jobs)?;
        write_notification_digest(&paths, &current_jobs)?;
        write_review_digest(&paths, &reviews)?;
        refresh_dashboard(root, config);
    }

    Ok(ReviewJobsOutput {
        reviewed_at,
        reviews,
        approved,
        rejected,
        prompts_generated,
    })
}

pub fn approve_job(
    root: &Path,
    config: &OrchestratorConfig,
    domain: &str,
) -> anyhow::Result<OrchestratorJob> {
    let paths = ResolvedPaths::new(root, config);
    let job_path = job_path(&paths.jobs_dir, domain);
    let mut job = read_job(&job_path)?;
    if !matches!(
        job.status,
        JobStatus::AwaitingApproval | JobStatus::IntakeScored
    ) {
        anyhow::bail!(
            "job `{}` is `{}` and cannot be approved from this state",
            job.domain,
            job.status.label()
        );
    }
    job.status = JobStatus::Approved;
    job.updated_at = Utc::now().to_rfc3339();
    job.next_action = "generate research prompt".to_string();
    write_job(&paths.jobs_dir, &job)?;
    Ok(job)
}

pub fn reject_job(
    root: &Path,
    config: &OrchestratorConfig,
    domain: &str,
    reason: Option<&str>,
) -> anyhow::Result<OrchestratorJob> {
    update_terminal_job(root, config, domain, JobStatus::Rejected, reason)
}

pub fn archive_job(
    root: &Path,
    config: &OrchestratorConfig,
    domain: &str,
    reason: Option<&str>,
) -> anyhow::Result<OrchestratorJob> {
    update_terminal_job(root, config, domain, JobStatus::Archived, reason)
}

pub fn complete_job(
    root: &Path,
    config: &OrchestratorConfig,
    domain: &str,
    options: CompleteJobOptions,
) -> anyhow::Result<(OrchestratorJob, DomainFeedback)> {
    let paths = ResolvedPaths::new(root, config);
    let registry_update = validate_registry_update(
        &options.registry_update_path,
        domain,
        &options.report_path,
        &config.registry_updates,
    )?;
    let notify = should_notify_completion(&options.final_status, config)
        || !config.notifications.suppress_routine_failures;
    let result = complete_job_inner(root, config, domain, options, notify)?;
    if should_auto_apply_registry_update(&registry_update, config) {
        apply_registry_update(&paths.mre_root, &registry_update)?;
    }
    let jobs = load_jobs(&paths.jobs_dir)?;
    write_history_snapshot(&paths, &jobs)?;
    write_notification_digest(&paths, &jobs)?;
    Ok(result)
}

pub fn list_jobs(root: &Path, config: &OrchestratorConfig) -> anyhow::Result<Vec<OrchestratorJob>> {
    let paths = ResolvedPaths::new(root, config);
    load_jobs(&paths.jobs_dir)
}

pub fn run_approved_jobs(
    root: &Path,
    config: &OrchestratorConfig,
) -> anyhow::Result<Vec<OrchestratorJob>> {
    let paths = ResolvedPaths::new(root, config);
    ensure_orchestrator_dirs(&paths)?;
    let jobs = load_jobs(&paths.jobs_dir)?;
    let mut updated = Vec::new();
    let active = running_job_count(&jobs);
    let max_active = config
        .limits
        .max_active_jobs
        .max(config.approval.max_active_jobs);

    for job in jobs {
        if !matches!(job.status, JobStatus::Approved) {
            continue;
        }
        if active + updated.len() >= max_active {
            break;
        }
        let prompted = generate_research_prompt(root, config, &job.domain, None)?;
        let run = if config.automation.auto_run_agents {
            run_one_prompted_job(root, config, &prompted.domain)?
        } else {
            prompted
        };
        updated.push(run);
    }

    let current_jobs = load_jobs(&paths.jobs_dir)?;
    write_history_snapshot(&paths, &current_jobs)?;
    write_notification_digest(&paths, &current_jobs)?;
    Ok(updated)
}

pub fn job_history(root: &Path, config: &OrchestratorConfig) -> anyhow::Result<Vec<PathBuf>> {
    let paths = ResolvedPaths::new(root, config);
    if !paths.history_dir.exists() {
        return Ok(Vec::new());
    }
    let mut files = fs::read_dir(&paths.history_dir)
        .with_context(|| format!("failed to list history dir {}", paths.history_dir.display()))?
        .filter_map(|entry| entry.ok().map(|entry| entry.path()))
        .filter(|path| path.extension().and_then(|s| s.to_str()) == Some("json"))
        .collect::<Vec<_>>();
    files.sort();
    Ok(files)
}

pub fn notification_digest(root: &Path, config: &OrchestratorConfig) -> anyhow::Result<PathBuf> {
    let paths = ResolvedPaths::new(root, config);
    ensure_orchestrator_dirs(&paths)?;
    let jobs = load_jobs(&paths.jobs_dir)?;
    write_notification_digest(&paths, &jobs)
}

fn update_terminal_job(
    root: &Path,
    config: &OrchestratorConfig,
    domain: &str,
    status: JobStatus,
    reason: Option<&str>,
) -> anyhow::Result<OrchestratorJob> {
    let paths = ResolvedPaths::new(root, config);
    let job_path = job_path(&paths.jobs_dir, domain);
    let mut job = read_job(&job_path)?;
    job.status = status;
    job.updated_at = Utc::now().to_rfc3339();
    job.terminal_reason = reason.map(str::to_string);
    job.next_action = match status {
        JobStatus::Rejected => "rejected; no research prompt should be generated".to_string(),
        JobStatus::Archived => "archived; no further action".to_string(),
        JobStatus::Completed => "completed; review final report and registry update".to_string(),
        _ => job.next_action,
    };
    write_job(&paths.jobs_dir, &job)?;
    Ok(job)
}

pub fn generate_research_prompt(
    root: &Path,
    config: &OrchestratorConfig,
    domain: &str,
    out: Option<&Path>,
) -> anyhow::Result<OrchestratorJob> {
    let paths = ResolvedPaths::new(root, config);
    ensure_dir(&paths.prompts_dir)?;
    let job_path = job_path(&paths.jobs_dir, domain);
    let mut job = read_job(&job_path)?;
    if !matches!(job.status, JobStatus::Approved | JobStatus::PromptGenerated) {
        anyhow::bail!(
            "job `{}` is `{}`; approve it before generating a research prompt",
            job.domain,
            job.status.label()
        );
    }

    let prompt_path = out
        .map(PathBuf::from)
        .unwrap_or_else(|| paths.prompts_dir.join(format!("{}.md", job.domain)));
    let intake_text = fs::read_to_string(&job.intake_path).unwrap_or_else(|_| {
        format!(
            "Intake file was not readable at `{}`. Regenerate the intake before running research.",
            job.intake_path
        )
    });
    let prompt = research_prompt_markdown(&job, &intake_text);
    write_string(&prompt_path, &prompt)?;

    job.status = JobStatus::PromptGenerated;
    job.prompt_path = Some(prompt_path.display().to_string());
    job.updated_at = Utc::now().to_rfc3339();
    job.next_action = "send prompt to an MRE research agent; do not auto-launch".to_string();
    write_job(&paths.jobs_dir, &job)?;
    Ok(job)
}

fn run_one_prompted_job(
    root: &Path,
    config: &OrchestratorConfig,
    domain: &str,
) -> anyhow::Result<OrchestratorJob> {
    let paths = ResolvedPaths::new(root, config);
    let job_path = job_path(&paths.jobs_dir, domain);
    let mut job = read_job(&job_path)?;
    let Some(prompt_path) = job.prompt_path.clone() else {
        anyhow::bail!("job `{}` has no generated prompt", job.domain);
    };

    match config.runner.mode.trim().to_ascii_lowercase().as_str() {
        "manual" => {
            job.next_action =
                "manual runner mode; send prompt to an MRE research agent".to_string();
        }
        "noop" => {
            job.status = JobStatus::Running;
            job.next_action = "noop runner; awaiting completion artifacts".to_string();
            write_heartbeat(&paths.jobs_dir, &job, "noop_runner")?;
        }
        "command" => {
            if config.runner.command.trim().is_empty() {
                anyhow::bail!("runner mode is command but runner.command is empty");
            }
            let mut command = Command::new(&config.runner.command);
            command.current_dir(&paths.mre_root);
            for arg in &config.runner.args {
                command.arg(
                    arg.replace("{prompt_path}", &prompt_path)
                        .replace("{domain}", &job.domain)
                        .replace("{mre_root}", &paths.mre_root.display().to_string()),
                );
            }
            job.status = JobStatus::Running;
            job.next_action = "command runner launched; awaiting completion artifacts".to_string();
            write_job(&paths.jobs_dir, &job)?;
            write_heartbeat(&paths.jobs_dir, &job, "command_runner_started")?;
            let status = command
                .status()
                .with_context(|| format!("failed to launch runner for {}", job.domain))?;
            if !status.success() {
                job.status = JobStatus::Failed;
                job.terminal_reason = Some(format!("runner exited with {}", status));
                job.next_action = "runner failed; review logs before retry".to_string();
            }
        }
        other => {
            anyhow::bail!("unsupported runner mode `{}`", other);
        }
    }

    job.updated_at = Utc::now().to_rfc3339();
    write_job(&paths.jobs_dir, &job)?;
    Ok(job)
}

fn ensure_orchestrator_dirs(paths: &ResolvedPaths) -> anyhow::Result<()> {
    ensure_dir(&paths.jobs_dir)?;
    ensure_dir(&paths.notifications_dir)?;
    ensure_dir(&paths.prompts_dir)?;
    ensure_dir(&paths.history_dir)?;
    ensure_dir(&paths.reviews_dir)?;
    if let Some(parent) = paths.feedback_path.parent() {
        ensure_dir(parent)?;
    }
    Ok(())
}

fn ingest_completion_artifacts(
    root: &Path,
    config: &OrchestratorConfig,
) -> anyhow::Result<Vec<OrchestratorJob>> {
    let paths = ResolvedPaths::new(root, config);
    let jobs = load_jobs(&paths.jobs_dir)?;
    let mut completed = Vec::new();

    for job in jobs {
        if is_terminal_status(job.status) {
            continue;
        }
        let report_path = paths
            .mre_root
            .join("artifacts")
            .join(format!("{}_domain_final_report.md", job.domain));
        let registry_update_path = paths
            .mre_root
            .join("artifacts")
            .join(format!("{}_registry_update.json", job.domain));
        if !report_path.exists() || !registry_update_path.exists() {
            continue;
        }
        let registry_update = validate_registry_update(
            &registry_update_path,
            &job.domain,
            &report_path,
            &config.registry_updates,
        )?;
        let final_status = json_string(&registry_update, "status")
            .unwrap_or_else(|| "completed".to_string())
            .replace(' ', "_");
        let (completed_job, _feedback) = complete_job_inner(
            root,
            config,
            &job.domain,
            CompleteJobOptions {
                final_status,
                report_path: report_path.clone(),
                registry_update_path: registry_update_path.clone(),
                ..CompleteJobOptions::default()
            },
            should_notify_completion(&feedback_status(&registry_update), config),
        )?;
        if should_auto_apply_registry_update(&registry_update, config) {
            apply_registry_update(&paths.mre_root, &registry_update)?;
        }
        completed.push(completed_job);
    }

    Ok(completed)
}

fn validate_registry_update(
    path: &Path,
    domain: &str,
    report_path: &Path,
    config: &RegistryUpdateConfig,
) -> anyhow::Result<serde_json::Value> {
    if config.require_final_report {
        anyhow::ensure!(
            report_path.exists(),
            "final report is required before completing `{}`",
            domain
        );
    }
    let value = read_optional_json(path)?;
    if config.require_valid_json {
        anyhow::ensure!(
            value.is_object(),
            "registry update {} must be a JSON object",
            path.display()
        );
        let update_domain = json_string(&value, "domain").unwrap_or_default();
        anyhow::ensure!(
            crate::registry::normalize_slug(&update_domain)
                == crate::registry::normalize_slug(domain),
            "registry update domain `{}` does not match job `{}`",
            update_domain,
            domain
        );
        anyhow::ensure!(
            json_string(&value, "status").is_some(),
            "registry update for `{}` is missing status",
            domain
        );
        anyhow::ensure!(
            json_string(&value, "stop_reason").is_some(),
            "registry update for `{}` is missing stop_reason",
            domain
        );
    }
    Ok(value)
}

fn should_auto_apply_registry_update(
    registry_update: &serde_json::Value,
    config: &OrchestratorConfig,
) -> bool {
    let status = feedback_status(registry_update);
    let normalized = normalize_status(&status);
    if normalized == "candidate_paper_signal" {
        return config.registry_updates.auto_apply_candidate_paper_signal;
    }
    config.registry_updates.auto_apply_safe_terminal_statuses
        && config
            .registry_updates
            .safe_statuses
            .iter()
            .map(|s| normalize_status(s))
            .any(|safe| safe == normalized)
}

fn apply_registry_update(
    mre_root: &Path,
    registry_update: &serde_json::Value,
) -> anyhow::Result<()> {
    let registry_path = mre_root.join("docs/DOMAIN_RESEARCH_REGISTRY.md");
    let mut text = if registry_path.exists() {
        fs::read_to_string(&registry_path)
            .with_context(|| format!("failed to read {}", registry_path.display()))?
    } else {
        "# Domain Research Registry\n".to_string()
    };
    if !text.ends_with('\n') {
        text.push('\n');
    }
    if !text.contains("## Automated Registry Updates") {
        text.push_str("\n## Automated Registry Updates\n\n");
        text.push_str(
            "| domain | status | stage_reached | stop_reason | last_commit | revisit_trigger |\n",
        );
        text.push_str("| --- | --- | --- | --- | --- | --- |\n");
    }
    let row = format!(
        "| {} | {} | {} | {} | {} | {} |\n",
        escape_table_cell(&json_string(registry_update, "domain").unwrap_or_default()),
        escape_table_cell(&json_string(registry_update, "status").unwrap_or_default()),
        escape_table_cell(&json_string(registry_update, "stage_reached").unwrap_or_default()),
        escape_table_cell(&json_string(registry_update, "stop_reason").unwrap_or_default()),
        escape_table_cell(&json_string(registry_update, "last_commit").unwrap_or_default()),
        escape_table_cell(&json_string(registry_update, "revisit_trigger").unwrap_or_default()),
    );
    text.push_str(&row);
    write_string(&registry_path, &text)
}

fn complete_job_inner(
    root: &Path,
    config: &OrchestratorConfig,
    domain: &str,
    options: CompleteJobOptions,
    write_notification: bool,
) -> anyhow::Result<(OrchestratorJob, DomainFeedback)> {
    let paths = ResolvedPaths::new(root, config);
    let job_path = job_path(&paths.jobs_dir, domain);
    let mut job = read_job(&job_path)?;

    let registry_update = read_optional_json(&options.registry_update_path)?;
    let run_summary = read_optional_json(
        &paths
            .mre_root
            .join("data/events")
            .join(domain)
            .join("run_summary.json"),
    )?;

    let now = Utc::now().to_rfc3339();
    let stop_reason = json_string(&registry_update, "stop_reason")
        .or_else(|| options.reason.clone())
        .or_else(|| job.terminal_reason.clone());
    let stage_reached = json_string(&registry_update, "stage_reached");

    let feedback = DomainFeedback {
        domain: domain.to_string(),
        status: options.final_status.clone(),
        stage_reached,
        source_rows: options
            .source_rows
            .or_else(|| json_u64(&run_summary, "source_rows")),
        parsed_rows: options
            .parsed_rows
            .or_else(|| json_u64(&run_summary, "parsed_rows"))
            .or_else(|| json_u64(&run_summary, "source_rows")),
        machine_positive_rows: options.machine_positive_rows.or_else(|| {
            json_map_u64(&run_summary, "event_type_counts", "material_customer_loss").map(|loss| {
                loss + json_map_u64(&run_summary, "event_type_counts", "contract_termination")
                    .unwrap_or(0)
            })
        }),
        audited_true_positive_rows: options.audited_true_positive_rows,
        reviewed_usable_rows: options.reviewed_usable_rows,
        likely_oos: options.likely_oos,
        stop_reason,
        report_path: options.report_path.display().to_string(),
        registry_update_path: options.registry_update_path.display().to_string(),
        timestamp: now.clone(),
    };

    job.status = JobStatus::Completed;
    job.updated_at = now;
    job.final_status = Some(options.final_status);
    job.report_path = Some(options.report_path.display().to_string());
    job.registry_update_path = Some(options.registry_update_path.display().to_string());
    job.terminal_reason = feedback.stop_reason.clone();
    job.next_action = "completed; review final report and registry update".to_string();
    write_job(&paths.jobs_dir, &job)?;
    append_feedback(&paths.feedback_path, &feedback)?;
    if write_notification {
        write_string(
            &paths.notifications_dir.join("latest.md"),
            &completion_notification_markdown(&job, &feedback),
        )?;
    }
    Ok((job, feedback))
}

fn mark_stale_jobs(
    root: &Path,
    config: &OrchestratorConfig,
) -> anyhow::Result<Vec<OrchestratorJob>> {
    let paths = ResolvedPaths::new(root, config);
    let jobs = load_jobs(&paths.jobs_dir)?;
    let cutoff = Utc::now() - Duration::hours(config.loop_config.stale_after_hours.max(1));
    let mut stale = Vec::new();
    for mut job in jobs {
        if !matches!(job.status, JobStatus::Running | JobStatus::PromptGenerated) {
            continue;
        }
        let updated = DateTime::parse_from_rfc3339(&job.updated_at)
            .map(|dt| dt.with_timezone(&Utc))
            .unwrap_or_else(|_| Utc::now());
        if updated > cutoff {
            continue;
        }
        job.status = JobStatus::Stale;
        job.terminal_reason = Some("no heartbeat or update before stale threshold".to_string());
        job.next_action = "stale; review runner state before retry".to_string();
        job.updated_at = Utc::now().to_rfc3339();
        write_job(&paths.jobs_dir, &job)?;
        stale.push(job);
    }
    Ok(stale)
}

fn write_heartbeat(jobs_dir: &Path, job: &OrchestratorJob, phase: &str) -> anyhow::Result<()> {
    let heartbeat = serde_json::json!({
        "domain": job.domain,
        "status": job.status.label(),
        "phase": phase,
        "updated_at": Utc::now().to_rfc3339(),
    });
    write_string(
        &jobs_dir.join(format!("{}.heartbeat.json", job.domain)),
        &serde_json::to_string_pretty(&heartbeat)?,
    )
}

fn write_history_snapshot(paths: &ResolvedPaths, jobs: &[OrchestratorJob]) -> anyhow::Result<()> {
    ensure_dir(&paths.history_dir)?;
    let stamp = timestamp_slug();
    let payload = serde_json::json!({
        "generated_at": Utc::now().to_rfc3339(),
        "jobs": jobs,
    });
    write_string(
        &paths.history_dir.join(format!("{}_jobs.json", stamp)),
        &serde_json::to_string_pretty(&payload)?,
    )
}

fn write_notification_digest(
    paths: &ResolvedPaths,
    jobs: &[OrchestratorJob],
) -> anyhow::Result<PathBuf> {
    ensure_dir(&paths.notifications_dir)?;
    let path = paths.notifications_dir.join("digest.md");
    write_string(&path, &notification_digest_markdown(jobs))?;
    Ok(path)
}

fn write_review_artifact(paths: &ResolvedPaths, review: &JobReview) -> anyhow::Result<()> {
    ensure_dir(&paths.reviews_dir)?;
    write_string(
        &paths.reviews_dir.join(format!("{}.json", review.domain)),
        &serde_json::to_string_pretty(review)?,
    )
}

fn write_review_digest(paths: &ResolvedPaths, reviews: &[JobReview]) -> anyhow::Result<PathBuf> {
    ensure_dir(&paths.notifications_dir)?;
    let path = paths.notifications_dir.join("review_digest.md");
    write_string(&path, &review_digest_markdown(reviews))?;
    Ok(path)
}

fn refresh_dashboard(root: &Path, config: &OrchestratorConfig) {
    let paths = ResolvedPaths::new(root, config);
    let _ = build_dashboard(&DashboardOptions {
        root: paths.mre_root.clone(),
        out_dir: paths.dashboard_out_dir.clone(),
        registry_path: None,
        candidates_path: None,
    });
}

fn passes_orchestrator_thresholds(
    candidate: &DomainCandidate,
    config: &OrchestratorConfig,
) -> bool {
    match candidate.gate {
        GateDecision::FullLifecycle => {
            candidate.score.total >= config.thresholds.full_lifecycle_score
        }
        GateDecision::FeasibilityOnly => {
            candidate.score.total >= config.thresholds.feasibility_score
        }
        _ => false,
    }
}

fn passes_auto_approval(candidate: &DomainCandidate, config: &OrchestratorConfig) -> bool {
    if !config.approval.auto_approve {
        return true;
    }
    if config.approval.require_registry_clear && candidate.registry_status.is_some() {
        return false;
    }
    match candidate.gate {
        GateDecision::FullLifecycle => {
            config.approval.allow_full_lifecycle
                && candidate.score.total >= config.approval.min_full_lifecycle_score
        }
        GateDecision::FeasibilityOnly => {
            config.approval.allow_feasibility_only
                && candidate.score.total >= config.approval.min_feasibility_score
        }
        _ => false,
    }
}

fn automated_job_review(
    job: &OrchestratorJob,
    candidate: Option<&DomainCandidate>,
    config: &OrchestratorConfig,
    reviewed_at: &str,
) -> JobReview {
    let mut review = JobReview {
        domain: job.domain.clone(),
        decision: "reject_review_disabled".to_string(),
        confidence: "high".to_string(),
        job_status_before: job.status.label().to_string(),
        job_status_after: None,
        score: candidate
            .map(|candidate| candidate.score.total)
            .or(Some(job.score)),
        gate: candidate.map(|candidate| candidate.gate.label().to_string()),
        reasons: Vec::new(),
        required_next_step: "do not run research".to_string(),
        reviewed_at: reviewed_at.to_string(),
    };

    if !config.review.enabled {
        review
            .reasons
            .push("automated review policy is disabled".to_string());
        return review;
    }

    let Some(candidate) = candidate else {
        review.decision = "reject_missing_current_candidate".to_string();
        review
            .reasons
            .push("job is not present in the current domain-finder scan".to_string());
        return review;
    };

    review.gate = Some(candidate.gate.label().to_string());
    review.score = Some(candidate.score.total);

    if config.review.require_registry_clear && candidate.registry_status.is_some() {
        review.decision = "reject_registry_history".to_string();
        if let Some(registry) = &candidate.registry_status {
            review.reasons.push(format!(
                "registry status is `{}`; stop reason: {}",
                registry.status,
                registry
                    .stop_reason
                    .as_deref()
                    .unwrap_or("no stop reason recorded")
            ));
        }
        return review;
    }

    match candidate.gate {
        GateDecision::FullLifecycle | GateDecision::FeasibilityOnly => {}
        GateDecision::BlockedByRegistry => {
            review.decision = "reject_blocked_by_registry".to_string();
            review
                .reasons
                .push("candidate gate is blocked_by_registry".to_string());
            return review;
        }
        GateDecision::MonitorOnly => {
            review.decision = "reject_monitor_only".to_string();
            review
                .reasons
                .push("candidate is monitor_only; no run before revisit trigger".to_string());
            return review;
        }
        GateDecision::Backlog | GateDecision::Skip => {
            review.decision = "reject_not_research_ready".to_string();
            review
                .reasons
                .push(format!("candidate gate is `{}`", candidate.gate.label()));
            return review;
        }
    }

    let required_score = match candidate.gate {
        GateDecision::FullLifecycle => config.review.min_full_lifecycle_score,
        GateDecision::FeasibilityOnly => config.review.min_feasibility_score,
        _ => unreachable!("non-runnable gates returned earlier"),
    };
    if candidate.score.total < required_score {
        review.decision = "reject_score_below_policy".to_string();
        review.reasons.push(format!(
            "score {}/30 is below required {} for `{}`",
            candidate.score.total,
            required_score,
            candidate.gate.label()
        ));
    }

    if candidate
        .warnings
        .iter()
        .any(|warning| warning.contains("low true-positive yield"))
    {
        review.decision = "reject_prior_low_true_positive_yield".to_string();
        review.reasons.push(
            "historical feedback indicates low audited true-positive yield for this domain"
                .to_string(),
        );
    }

    if config.review.require_live_probe && !has_live_source_probe(candidate) {
        review.decision = "reject_needs_live_source_probe".to_string();
        review.reasons.push(
            "candidate has no live source_probe observation; static/offline seeds are insufficient"
                .to_string(),
        );
    } else if config.review.reject_static_or_offline_only && is_static_or_offline_only(candidate) {
        review.decision = "reject_static_or_offline_only".to_string();
        review
            .reasons
            .push("candidate is backed only by static or offline observations".to_string());
    }

    if candidate.score.public_timestamp_clarity < config.review.min_timestamp_score {
        review.decision = "reject_timestamp_below_review_policy".to_string();
        review.reasons.push(format!(
            "public timestamp clarity score {} is below review minimum {}",
            candidate.score.public_timestamp_clarity, config.review.min_timestamp_score
        ));
    }
    if candidate.delayed_digest_reasons.len() < config.review.min_delayed_digest_reasons {
        review.decision = "reject_delayed_digest_rationale_insufficient".to_string();
        review.reasons.push(format!(
            "only {} delayed-digestion reasons; need at least {}",
            candidate.delayed_digest_reasons.len(),
            config.review.min_delayed_digest_reasons
        ));
    }
    if candidate.hard_negatives.len() < config.review.min_hard_negatives {
        review.decision = "reject_hard_negatives_insufficient".to_string();
        review.reasons.push(format!(
            "only {} hard negatives; need at least {}",
            candidate.hard_negatives.len(),
            config.review.min_hard_negatives
        ));
    }
    if candidate.materiality_fields.len() < config.review.min_materiality_fields {
        review.decision = "reject_materiality_fields_insufficient".to_string();
        review.reasons.push(format!(
            "only {} materiality fields; need at least {}",
            candidate.materiality_fields.len(),
            config.review.min_materiality_fields
        ));
    }
    if candidate.score.ticker_mapping_feasibility < config.review.min_mapping_score {
        review.decision = "reject_mapping_score_below_review_policy".to_string();
        review.reasons.push(format!(
            "ticker/entity mapping score {} is below review minimum {}",
            candidate.score.ticker_mapping_feasibility, config.review.min_mapping_score
        ));
    }
    if candidate.score.parser_audit_feasibility < config.review.min_parser_score {
        review.decision = "reject_parser_score_below_review_policy".to_string();
        review.reasons.push(format!(
            "parser/audit feasibility score {} is below review minimum {}",
            candidate.score.parser_audit_feasibility, config.review.min_parser_score
        ));
    }
    if candidate.score.sample_size_likelihood < config.review.min_sample_score {
        review.decision = "reject_sample_score_below_review_policy".to_string();
        review.reasons.push(format!(
            "sample-size likelihood score {} is below review minimum {}",
            candidate.score.sample_size_likelihood, config.review.min_sample_score
        ));
    }

    if review.reasons.is_empty() {
        review.decision = "approve".to_string();
        review.confidence = "medium".to_string();
        review
            .reasons
            .push("registry-clear candidate passed deterministic review policy".to_string());
        review.required_next_step = "approve job and generate research prompt".to_string();
    } else {
        review.required_next_step =
            "do not run research; require new evidence or a materially different source strategy"
                .to_string();
    }

    review
}

fn has_live_source_probe(candidate: &DomainCandidate) -> bool {
    candidate.observations.iter().any(|obs| {
        let has_probe = obs.tags.iter().any(|tag| tag == "source_probe");
        let offline = obs.tags.iter().any(|tag| tag == "probe_status:offline")
            || obs
                .evidence
                .iter()
                .any(|item| item.to_ascii_lowercase().contains("status=offline"));
        has_probe && !offline
    })
}

fn is_static_or_offline_only(candidate: &DomainCandidate) -> bool {
    !has_live_source_probe(candidate)
}

fn should_auto_approve_job(
    candidate: &DomainCandidate,
    config: &OrchestratorConfig,
    auto_mode: bool,
) -> bool {
    if auto_mode {
        return config.approval.auto_approve && passes_auto_approval(candidate, config);
    }
    config.automation.auto_approve_full_lifecycle
        && matches!(candidate.gate, GateDecision::FullLifecycle)
        && !config.loop_config.require_human_approval
}

fn effective_max_new_jobs(config: &OrchestratorConfig, auto_mode: bool) -> usize {
    if auto_mode {
        config
            .approval
            .max_new_jobs_per_run
            .min(config.loop_config.max_new_jobs_per_run)
            .max(1)
    } else {
        config.loop_config.max_new_jobs_per_run.max(1)
    }
}

fn effective_max_active_jobs(config: &OrchestratorConfig, auto_mode: bool) -> usize {
    if auto_mode {
        config
            .approval
            .max_active_jobs
            .min(config.limits.max_active_jobs)
            .max(1)
    } else {
        config.limits.max_active_jobs.max(1)
    }
}

fn active_job_count(jobs: &[OrchestratorJob]) -> usize {
    jobs.iter()
        .filter(|job| !is_terminal_status(job.status))
        .count()
}

fn running_job_count(jobs: &[OrchestratorJob]) -> usize {
    jobs.iter()
        .filter(|job| {
            matches!(
                job.status,
                JobStatus::Running | JobStatus::PromptGenerated | JobStatus::Stale
            )
        })
        .count()
}

fn job_from_candidate(candidate: &DomainCandidate, intake_path: &Path) -> OrchestratorJob {
    let now = Utc::now().to_rfc3339();
    let status = JobStatus::AwaitingApproval;
    OrchestratorJob {
        domain: candidate.slug.clone(),
        title: candidate.title.clone(),
        status,
        score: candidate.score.total,
        decision: candidate.gate,
        scope: match candidate.gate {
            GateDecision::FullLifecycle => "full_lifecycle".to_string(),
            GateDecision::FeasibilityOnly => "source_feasibility_only".to_string(),
            _ => "not_eligible".to_string(),
        },
        intake_path: intake_path.display().to_string(),
        prompt_path: None,
        created_at: now.clone(),
        updated_at: now,
        next_action: "review intake and approve research run".to_string(),
        terminal_reason: None,
        final_status: None,
        report_path: None,
        registry_update_path: None,
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
    }
}

fn is_terminal_status(status: JobStatus) -> bool {
    matches!(
        status,
        JobStatus::Rejected | JobStatus::Completed | JobStatus::Archived | JobStatus::Failed
    )
}

fn load_jobs(jobs_dir: &Path) -> anyhow::Result<Vec<OrchestratorJob>> {
    if !jobs_dir.exists() {
        return Ok(Vec::new());
    }
    let mut jobs = Vec::new();
    for entry in fs::read_dir(jobs_dir)
        .with_context(|| format!("failed to list jobs dir {}", jobs_dir.display()))?
    {
        let entry = entry?;
        let path = entry.path();
        if path.extension().and_then(|s| s.to_str()) != Some("json") {
            continue;
        }
        if path
            .file_name()
            .and_then(|s| s.to_str())
            .is_some_and(|name| name.ends_with(".heartbeat.json"))
        {
            continue;
        }
        jobs.push(read_job(&path)?);
    }
    jobs.sort_by(|a, b| a.domain.cmp(&b.domain));
    Ok(jobs)
}

fn read_job(path: &Path) -> anyhow::Result<OrchestratorJob> {
    let text =
        fs::read_to_string(path).with_context(|| format!("failed to read {}", path.display()))?;
    serde_json::from_str(&text).with_context(|| format!("failed to parse {}", path.display()))
}

fn write_job(jobs_dir: &Path, job: &OrchestratorJob) -> anyhow::Result<()> {
    ensure_dir(jobs_dir)?;
    let path = job_path(jobs_dir, &job.domain);
    let text = serde_json::to_string_pretty(job)?;
    write_string(&path, &text)
}

fn append_feedback(path: &Path, feedback: &DomainFeedback) -> anyhow::Result<()> {
    if let Some(parent) = path.parent() {
        ensure_dir(parent)?;
    }
    let mut file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
        .with_context(|| format!("failed to open feedback file {}", path.display()))?;
    writeln!(file, "{}", serde_json::to_string(feedback)?)?;
    Ok(())
}

fn read_optional_json(path: &Path) -> anyhow::Result<serde_json::Value> {
    if !path.exists() {
        return Ok(serde_json::Value::Null);
    }
    let text =
        fs::read_to_string(path).with_context(|| format!("failed to read {}", path.display()))?;
    serde_json::from_str(&text).with_context(|| format!("failed to parse {}", path.display()))
}

fn json_string(value: &serde_json::Value, key: &str) -> Option<String> {
    value
        .get(key)
        .and_then(|item| item.as_str())
        .map(str::to_string)
}

fn json_u64(value: &serde_json::Value, key: &str) -> Option<u64> {
    value.get(key).and_then(|item| item.as_u64())
}

fn json_map_u64(value: &serde_json::Value, map_key: &str, item_key: &str) -> Option<u64> {
    value
        .get(map_key)
        .and_then(|item| item.get(item_key))
        .and_then(|item| item.as_u64())
}

fn job_path(jobs_dir: &Path, domain: &str) -> PathBuf {
    jobs_dir.join(format!("{}.json", crate::registry::normalize_slug(domain)))
}

fn notification_markdown(
    new_jobs: &[OrchestratorJob],
    existing_jobs: &[OrchestratorJob],
    suppressed_blocked_count: usize,
    monitor_only_count: usize,
) -> String {
    let mut out = String::new();
    out.push_str("# Domain Finder Orchestrator Notification\n\n");
    out.push_str(&format!("Generated: `{}`\n\n", Utc::now().to_rfc3339()));
    out.push_str(&format!(
        "- new jobs queued: `{}`\n- existing jobs: `{}`\n- blocked domains suppressed: `{}`\n- monitor-only domains: `{}`\n\n",
        new_jobs.len(),
        existing_jobs.len(),
        suppressed_blocked_count,
        monitor_only_count
    ));

    out.push_str("## New Jobs\n\n");
    if new_jobs.is_empty() {
        out.push_str("- none\n\n");
    } else {
        for job in new_jobs {
            out.push_str(&format!(
                "- `{}`: score `{}/30`, scope `{}`, status `{}`, intake `{}`\n",
                job.domain,
                job.score,
                job.scope,
                job.status.label(),
                job.intake_path
            ));
        }
        out.push('\n');
    }

    out.push_str("## Existing Jobs\n\n");
    if existing_jobs.is_empty() {
        out.push_str("- none\n");
    } else {
        for job in existing_jobs {
            let reason = job
                .terminal_reason
                .as_ref()
                .map(|reason| format!("; reason: {}", reason))
                .unwrap_or_default();
            out.push_str(&format!(
                "- `{}`: status `{}`, next action: {}{}\n",
                job.domain,
                job.status.label(),
                job.next_action,
                reason
            ));
        }
    }
    out
}

fn completion_notification_markdown(job: &OrchestratorJob, feedback: &DomainFeedback) -> String {
    let mut out = String::new();
    out.push_str("# Domain Finder Job Completion\n\n");
    out.push_str(&format!("Generated: `{}`\n\n", Utc::now().to_rfc3339()));
    out.push_str(&format!("- domain: `{}`\n", job.domain));
    out.push_str(&format!("- job status: `{}`\n", job.status.label()));
    out.push_str(&format!("- final status: `{}`\n", feedback.status));
    out.push_str(&format!("- report: `{}`\n", feedback.report_path));
    out.push_str(&format!(
        "- registry update: `{}`\n",
        feedback.registry_update_path
    ));
    if let Some(reason) = &feedback.stop_reason {
        out.push_str(&format!("- stop reason: {}\n", reason));
    }
    out.push_str("\nNo registry update was applied automatically.\n");
    out
}

fn research_prompt_markdown(job: &OrchestratorJob, intake_text: &str) -> String {
    let mut out = String::new();
    out.push_str(&format!("# MRE Research Prompt: `{}`\n\n", job.domain));
    out.push_str("You are an MRE domain research agent.\n\n");
    out.push_str("## Canonical Project State\n\n");
    out.push_str("- No graduated signal.\n");
    out.push_str("- No live tradable candidate.\n");
    out.push_str("- SEC-CORE is the durable MRE infrastructure win.\n");
    out.push_str("- Domain Finder is the pre-MRE idea-selection layer.\n");
    out.push_str("- Cyber Item 1.05 is the only true monitor.\n\n");
    out.push_str("## Standing Rules\n\n");
    out.push_str("- Do not assume signal.\n");
    out.push_str("- Do not model until readiness gates pass.\n");
    out.push_str("- Stop at the first hard gate failure.\n");
    out.push_str("- Do not tune thresholds after seeing returns.\n");
    out.push_str("- Do not graduate a signal from first falsification.\n");
    out.push_str("- Run fresh confirmation only if first falsification is promising.\n");
    out.push_str(
        "- Run final leakage/execution/capacity audit only if fresh confirmation passes.\n",
    );
    out.push_str(
        "- Do not auto-update the registry; produce a registry update artifact for review.\n\n",
    );
    out.push_str("## Job\n\n");
    out.push_str(&format!("- domain: `{}`\n", job.domain));
    out.push_str(&format!("- title: {}\n", job.title));
    out.push_str(&format!("- score: `{}/30`\n", job.score));
    out.push_str(&format!("- approved scope: `{}`\n", job.scope));
    if let Some(status) = &job.registry_status {
        out.push_str(&format!("- registry status: `{}`\n", status));
    }
    if let Some(reason) = &job.registry_stop_reason {
        out.push_str(&format!("- registry stop reason: {}\n", reason));
    }
    if let Some(trigger) = &job.registry_revisit_trigger {
        out.push_str(&format!("- registry revisit trigger: {}\n", trigger));
    }
    out.push_str("\n## Required Lifecycle\n\n");
    out.push_str("1. Source discovery\n");
    out.push_str("2. Parser and review queue\n");
    out.push_str("3. Reviewed corpus\n");
    out.push_str("4. Parser gold audit\n");
    out.push_str("5. Context/materiality enrichment\n");
    out.push_str("6. Timestamp/duplicate audit\n");
    out.push_str("7. Readiness report\n");
    out.push_str("8. First falsification only if readiness passes\n");
    out.push_str("9. Fresh confirmation only if first falsification is promising\n");
    out.push_str("10. Final leakage/execution/capacity audit only if fresh confirmation passes\n");
    out.push_str("11. Final report and registry update JSON\n\n");
    out.push_str("## Required Deliverables\n\n");
    out.push_str(&format!(
        "- `artifacts/{}_domain_final_report.md`\n",
        job.domain
    ));
    out.push_str(&format!(
        "- `artifacts/{}_registry_update.json`\n",
        job.domain
    ));
    out.push_str(&format!(
        "- `docs/{}_MILESTONE.md`\n\n",
        job.domain.to_uppercase()
    ));
    out.push_str("## Intake\n\n");
    out.push_str(intake_text);
    out
}

struct ResolvedPaths {
    mre_root: PathBuf,
    jobs_dir: PathBuf,
    notifications_dir: PathBuf,
    prompts_dir: PathBuf,
    feedback_path: PathBuf,
    history_dir: PathBuf,
    dashboard_out_dir: PathBuf,
    reviews_dir: PathBuf,
}

impl ResolvedPaths {
    fn new(root: &Path, config: &OrchestratorConfig) -> Self {
        let domain_finder_root = rel(root, &config.paths.domain_finder_root);
        Self {
            mre_root: rel(root, &config.paths.mre_root),
            jobs_dir: rel(&domain_finder_root, &config.paths.jobs_dir),
            notifications_dir: rel(&domain_finder_root, &config.paths.notifications_dir),
            prompts_dir: rel(&domain_finder_root, &config.paths.prompts_dir),
            feedback_path: rel(&domain_finder_root, &config.paths.feedback_path),
            history_dir: rel(&domain_finder_root, &config.paths.history_dir),
            dashboard_out_dir: rel(&domain_finder_root, &config.paths.dashboard_out_dir),
            reviews_dir: rel(&domain_finder_root, &config.paths.reviews_dir),
        }
    }
}

pub fn review_jobs_report(output: &ReviewJobsOutput) -> String {
    let mut out = String::new();
    out.push_str("| Domain | Decision | Score | Gate | Reasons |\n");
    out.push_str("| --- | --- | ---: | --- | --- |\n");
    for review in &output.reviews {
        out.push_str(&format!(
            "| `{}` | `{}` | {} | `{}` | {} |\n",
            review.domain,
            review.decision,
            review
                .score
                .map(|score| score.to_string())
                .unwrap_or_else(|| "n/a".to_string()),
            review.gate.as_deref().unwrap_or("n/a"),
            escape_table_cell(&review.reasons.join("; "))
        ));
    }
    if output.reviews.is_empty() {
        out.push_str("| _none_ | _none_ |  |  | no awaiting jobs |\n");
    }
    out
}

pub fn jobs_report(jobs: &[OrchestratorJob]) -> String {
    let mut out = String::new();
    out.push_str("| Domain | Status | Score | Scope | Next Action |\n");
    out.push_str("| --- | --- | ---: | --- | --- |\n");
    for job in jobs {
        out.push_str(&format!(
            "| `{}` | `{}` | {} | `{}` | {} |\n",
            job.domain,
            job.status.label(),
            job.score,
            job.scope,
            job.next_action
        ));
    }
    out
}

fn default_mre_root() -> String {
    "..".to_string()
}
fn default_domain_finder_root() -> String {
    ".".to_string()
}
fn default_jobs_dir() -> String {
    "artifacts/orchestrator/jobs".to_string()
}
fn default_notifications_dir() -> String {
    "artifacts/orchestrator/notifications".to_string()
}
fn default_prompts_dir() -> String {
    "artifacts/orchestrator/prompts".to_string()
}
fn default_reviews_dir() -> String {
    "artifacts/orchestrator/reviews".to_string()
}
fn default_feedback_path() -> String {
    "artifacts/orchestrator/domain_feedback.jsonl".to_string()
}
fn default_interval_secs() -> u64 {
    900
}
fn default_max_new_jobs() -> usize {
    3
}
fn default_require_human_approval() -> bool {
    true
}
fn default_full_lifecycle_score() -> u8 {
    24
}
fn default_feasibility_score() -> u8 {
    18
}
fn default_true() -> bool {
    true
}
fn default_notification_mode() -> String {
    "local_markdown".to_string()
}
fn default_history_dir() -> String {
    "artifacts/orchestrator/history".to_string()
}
fn default_dashboard_out_dir() -> String {
    "artifacts/domain_finder/dashboard".to_string()
}
fn default_stale_after_hours() -> i64 {
    24
}
fn default_one_usize() -> usize {
    1
}
fn default_two_usize() -> usize {
    2
}
fn default_three_usize() -> usize {
    3
}
fn default_two_u8() -> u8 {
    2
}
fn default_three_u8() -> u8 {
    3
}
fn default_runner_mode() -> String {
    "manual".to_string()
}
fn default_notify_on() -> Vec<String> {
    vec![
        "monitor_trigger_met".to_string(),
        "readiness_passed".to_string(),
        "first_falsification_promising".to_string(),
        "fresh_confirmation_passed".to_string(),
        "final_audit_passed".to_string(),
        "candidate_paper_signal".to_string(),
        "new_high_score_domain".to_string(),
    ]
}
fn default_safe_registry_statuses() -> Vec<String> {
    vec![
        "parser_not_trusted".to_string(),
        "underpowered".to_string(),
        "mapping_insufficient".to_string(),
        "context_insufficient".to_string(),
        "timestamp_insufficient".to_string(),
        "failed_falsification".to_string(),
        "failed_execution".to_string(),
        "execution_unrealistic".to_string(),
        "frozen".to_string(),
    ]
}
fn default_notify_only_statuses() -> Vec<String> {
    vec![
        "promising_requires_fresh_confirmation".to_string(),
        "fresh_confirmed_pending_audit".to_string(),
        "candidate_paper_signal".to_string(),
    ]
}

fn feedback_status(registry_update: &serde_json::Value) -> String {
    json_string(registry_update, "status").unwrap_or_else(|| "completed".to_string())
}

fn should_notify_completion(status: &str, config: &OrchestratorConfig) -> bool {
    let normalized = normalize_status(status);
    config
        .registry_updates
        .notify_only_statuses
        .iter()
        .map(|item| normalize_status(item))
        .any(|item| item == normalized)
        || config
            .notifications
            .notify_on
            .iter()
            .map(|item| normalize_status(item))
            .any(|item| item == normalized)
}

fn normalize_status(status: &str) -> String {
    status.trim().to_ascii_lowercase().replace([' ', '-'], "_")
}

fn escape_table_cell(value: &str) -> String {
    value.replace('|', "\\|").replace('\n', " ")
}

fn timestamp_slug() -> String {
    Utc::now().format("%Y%m%dT%H%M%SZ").to_string()
}

fn notification_digest_markdown(jobs: &[OrchestratorJob]) -> String {
    let mut out = String::new();
    out.push_str("# Domain Finder Orchestrator Digest\n\n");
    out.push_str(&format!("Generated: `{}`\n\n", Utc::now().to_rfc3339()));
    let active = active_job_count(jobs);
    let completed = jobs
        .iter()
        .filter(|job| matches!(job.status, JobStatus::Completed))
        .count();
    let stale = jobs
        .iter()
        .filter(|job| matches!(job.status, JobStatus::Stale))
        .count();
    out.push_str(&format!(
        "- active jobs: `{}`\n- completed jobs: `{}`\n- stale jobs: `{}`\n- total jobs: `{}`\n\n",
        active,
        completed,
        stale,
        jobs.len()
    ));
    out.push_str("## Jobs\n\n");
    if jobs.is_empty() {
        out.push_str("- none\n");
    } else {
        for job in jobs {
            out.push_str(&format!(
                "- `{}`: `{}`; next: {}\n",
                job.domain,
                job.status.label(),
                job.next_action
            ));
        }
    }
    out
}

fn review_digest_markdown(reviews: &[JobReview]) -> String {
    let mut out = String::new();
    out.push_str("# Domain Finder Automated Review Digest\n\n");
    out.push_str(&format!("Generated: `{}`\n\n", Utc::now().to_rfc3339()));
    let approved = reviews
        .iter()
        .filter(|review| review.decision == "approve")
        .count();
    let rejected = reviews.len().saturating_sub(approved);
    out.push_str(&format!(
        "- reviewed jobs: `{}`\n- approved: `{}`\n- rejected/deferred: `{}`\n\n",
        reviews.len(),
        approved,
        rejected
    ));
    out.push_str("## Decisions\n\n");
    if reviews.is_empty() {
        out.push_str("- none\n");
    } else {
        for review in reviews {
            out.push_str(&format!(
                "- `{}`: `{}`; {}\n",
                review.domain,
                review.decision,
                review.reasons.join("; ")
            ));
        }
    }
    out
}
