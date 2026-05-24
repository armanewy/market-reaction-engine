use crate::collectors::collect_to_generated_dir;
use crate::config::Config;
use crate::io::{ensure_dir, rel, write_string};
use crate::model::{DomainCandidate, GateDecision};
use crate::pipeline::run_scan;
use crate::probes::{probe_family, ProbeOptions};
use crate::report::intake_doc;
use anyhow::Context;
use chrono::Utc;
use serde::{Deserialize, Serialize};
use std::fs;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::{Path, PathBuf};

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
}

impl Default for OrchestratorLoop {
    fn default() -> Self {
        Self {
            interval_secs: default_interval_secs(),
            max_new_jobs_per_run: default_max_new_jobs(),
            require_human_approval: default_require_human_approval(),
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
}

impl Default for OrchestratorNotifications {
    fn default() -> Self {
        Self {
            mode: default_notification_mode(),
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
}

pub fn run_orchestrator_once(
    root: &Path,
    domain_config: &Config,
    orchestrator_config: &OrchestratorConfig,
    options: OrchestratorRunOptions,
) -> anyhow::Result<OrchestratorRunOutput> {
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

    let scan = run_scan(root, domain_config)?;
    let paths = ResolvedPaths::new(root, orchestrator_config);
    ensure_dir(&paths.jobs_dir)?;
    ensure_dir(&paths.notifications_dir)?;

    let existing_jobs = load_jobs(&paths.jobs_dir)?;
    let has_active_jobs = existing_jobs
        .iter()
        .any(|job| !is_terminal_status(job.status));
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

        if has_active_jobs {
            continue;
        }
        if !passes_orchestrator_thresholds(candidate, orchestrator_config) {
            continue;
        }
        if existing_domains
            .iter()
            .any(|domain| domain == &candidate.slug)
        {
            continue;
        }
        if new_jobs.len() >= orchestrator_config.loop_config.max_new_jobs_per_run {
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
        if orchestrator_config.automation.auto_approve_full_lifecycle
            && matches!(job.decision, GateDecision::FullLifecycle)
            && !orchestrator_config.loop_config.require_human_approval
        {
            job.status = JobStatus::Approved;
            job.next_action = "generate research prompt".to_string();
        }

        if !options.dry_run {
            write_job(&paths.jobs_dir, &job)?;
        }
        existing_domains.push(job.domain.clone());
        new_jobs.push(job);
    }

    let notification = notification_markdown(
        &new_jobs,
        &existing_jobs,
        suppressed_blocked_count,
        monitor_only_count,
    );
    let notification_path = paths.notifications_dir.join("latest.md");
    if !options.dry_run {
        write_string(&notification_path, &notification)?;
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
    write_string(
        &paths.notifications_dir.join("latest.md"),
        &completion_notification_markdown(&job, &feedback),
    )?;
    Ok((job, feedback))
}

pub fn list_jobs(root: &Path, config: &OrchestratorConfig) -> anyhow::Result<Vec<OrchestratorJob>> {
    let paths = ResolvedPaths::new(root, config);
    load_jobs(&paths.jobs_dir)
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
        JobStatus::Rejected | JobStatus::Completed | JobStatus::Archived
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
        }
    }
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
