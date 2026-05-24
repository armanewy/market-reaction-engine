use anyhow::Context;
use clap::{Parser, Subcommand};
use domain_finder::collectors::{available_families, collect_to_generated_dir};
use domain_finder::config::Config;
use domain_finder::dashboard::{build_dashboard, DashboardOptions};
use domain_finder::io::{read_observations_path, write_string};
use domain_finder::model::DomainCandidate;
use domain_finder::operations::{
    alerts_report, current_alerts, diff_candidates, diff_report, explain_candidate, explain_report,
    load_candidates, top_candidates, top_report,
};
use domain_finder::orchestrator::{
    approve_job, archive_job, complete_job, generate_research_prompt, job_history, jobs_report,
    list_jobs, notification_digest, reject_job, review_jobs, review_jobs_report, run_approved_jobs,
    run_orchestrator_once, CompleteJobOptions, OrchestratorConfig, OrchestratorRunOptions,
    ReviewJobsOptions,
};
use domain_finder::pipeline::{candidate_from_observations, init_project, run_scan};
use domain_finder::probes::{probe_family, ProbeOptions};
use domain_finder::registry::Registry;
use domain_finder::report::{discovery_report, intake_doc};
use domain_finder::scoring::score_candidate;
use std::path::{Path, PathBuf};
use std::thread;
use std::time::Duration;

#[derive(Debug, Parser)]
#[command(name = "domain-finder")]
#[command(about = "Continuous domain discovery and intake scoring for Market Reaction Engine", long_about = None)]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Debug, Subcommand)]
enum Commands {
    /// Create sample config, observations, registry, and intake template.
    Init {
        #[arg(long, default_value = ".")]
        root: PathBuf,
        #[arg(long)]
        overwrite: bool,
    },
    /// Run one discovery scan and write report/intake artifacts.
    Scan {
        #[arg(long, default_value = ".")]
        root: PathBuf,
        #[arg(long)]
        config: Option<PathBuf>,
        #[arg(long)]
        json: bool,
    },
    /// Run discovery continuously on an interval.
    Watch {
        #[arg(long, default_value = ".")]
        root: PathBuf,
        #[arg(long)]
        config: Option<PathBuf>,
        #[arg(long, default_value_t = 900)]
        interval_secs: u64,
        /// Optional finite iteration count for automation/tests.
        #[arg(long)]
        iterations: Option<u64>,
    },
    /// Write built-in source-backed candidate observations.
    Collect {
        #[arg(long, default_value = ".")]
        root: PathBuf,
        /// Optional family: sec, agency, fda, litigation, index, or all.
        #[arg(long)]
        family: Option<String>,
        /// Optional output directory. Defaults to data/observations/generated.
        #[arg(long)]
        output_dir: Option<PathBuf>,
        #[arg(long)]
        json: bool,
    },
    /// Probe SEC-backed candidate domains and write dynamic observations.
    ProbeSecItems(ProbeArgs),
    /// Probe agency enforcement candidate domains and write dynamic observations.
    ProbeAgencyActions(ProbeArgs),
    /// Probe FDA enforcement candidate domains and write dynamic observations.
    ProbeFdaEnforcement(ProbeArgs),
    /// Probe litigation/ITC candidate domains and write dynamic observations.
    ProbeLitigation(ProbeArgs),
    /// Probe index/passive-flow candidate domains and write dynamic observations.
    ProbeIndexEvents(ProbeArgs),
    /// Score one candidate observation file and optionally write a report.
    Score {
        #[arg(long)]
        input: PathBuf,
        #[arg(long)]
        slug: Option<String>,
        #[arg(long)]
        registry: Option<PathBuf>,
        #[arg(long)]
        output: Option<PathBuf>,
        #[arg(long)]
        json: bool,
    },
    /// Generate an intake document from a candidate observation file.
    MakeIntake {
        #[arg(long)]
        input: PathBuf,
        #[arg(long)]
        slug: Option<String>,
        #[arg(long)]
        output: PathBuf,
        #[arg(long)]
        registry: Option<PathBuf>,
    },
    /// Show the highest-priority current candidates from a scan.
    Top {
        #[arg(long, default_value = ".")]
        root: PathBuf,
        #[arg(long)]
        config: Option<PathBuf>,
        #[arg(long, default_value_t = 10)]
        limit: usize,
        #[arg(long)]
        json: bool,
    },
    /// Explain the score, gate, and registry state for one domain.
    Explain {
        #[arg(long, default_value = ".")]
        root: PathBuf,
        #[arg(long)]
        config: Option<PathBuf>,
        #[arg(long)]
        slug: String,
        #[arg(long)]
        json: bool,
    },
    /// Compare two domain candidate JSON files from prior scans.
    Diff {
        #[arg(long)]
        old: PathBuf,
        #[arg(long)]
        new: PathBuf,
        #[arg(long)]
        json: bool,
    },
    /// Print actionable current alerts from the latest scan.
    Alerts {
        #[arg(long, default_value = ".")]
        root: PathBuf,
        #[arg(long)]
        config: Option<PathBuf>,
        #[arg(long)]
        json: bool,
    },
    /// Build a local static research dashboard.
    Dashboard {
        #[arg(long, default_value = ".")]
        root: PathBuf,
        #[arg(long, default_value = "artifacts/domain_finder/dashboard")]
        out: PathBuf,
        /// Optional registry override. Defaults to ../docs/DOMAIN_RESEARCH_REGISTRY.md when available.
        #[arg(long)]
        registry: Option<PathBuf>,
        /// Optional candidate JSON override.
        #[arg(long)]
        candidates: Option<PathBuf>,
        #[arg(long)]
        json: bool,
    },
    /// Run the conservative discovery -> intake -> job queue loop.
    Orchestrate(OrchestrateArgs),
    /// Approve a queued orchestrator job for prompt generation.
    Approve(ApproveArgs),
    /// Reject a queued orchestrator job with an optional reason.
    Reject(UpdateJobArgs),
    /// Archive an orchestrator job with an optional reason.
    ArchiveJob(UpdateJobArgs),
    /// Mark an orchestrator job complete and append domain feedback.
    CompleteJob(CompleteJobArgs),
    /// Generate prompts and optionally launch configured runners for approved jobs.
    RunApproved(ListJobsArgs),
    /// Deterministically approve or reject awaiting jobs using local review policy.
    ReviewJobs(ReviewJobsArgs),
    /// List queued orchestrator jobs.
    ListJobs(ListJobsArgs),
    /// List orchestrator history snapshots.
    JobHistory(ListJobsArgs),
    /// Write and print the local notification digest path.
    NotificationDigest(ListJobsArgs),
    /// Generate an approved MRE research prompt.
    ResearchPrompt(ResearchPromptArgs),
}

#[derive(Debug, clap::Args)]
struct ProbeArgs {
    #[arg(long, default_value = ".")]
    root: PathBuf,
    /// Optional output directory. Defaults to data/observations/probed.
    #[arg(long)]
    output_dir: Option<PathBuf>,
    /// HTTP timeout for each source check.
    #[arg(long, default_value_t = 10)]
    timeout_secs: u64,
    /// Record probe metadata without fetching source URLs.
    #[arg(long)]
    offline: bool,
    #[arg(long)]
    json: bool,
}

#[derive(Debug, clap::Args)]
struct OrchestrateArgs {
    #[arg(long, default_value = ".")]
    root: PathBuf,
    #[arg(long)]
    config: Option<PathBuf>,
    #[arg(long)]
    domain_config: Option<PathBuf>,
    #[arg(long)]
    once: bool,
    #[arg(long)]
    watch: bool,
    #[arg(long)]
    interval_secs: Option<u64>,
    #[arg(long)]
    iterations: Option<u64>,
    #[arg(long)]
    dry_run: bool,
    #[arg(long)]
    offline_probes: bool,
    /// Enable policy-controlled auto approval/runner behavior.
    #[arg(long)]
    auto: bool,
    #[arg(long)]
    json: bool,
}

#[derive(Debug, clap::Args)]
struct ApproveArgs {
    #[arg(long, default_value = ".")]
    root: PathBuf,
    #[arg(long)]
    config: Option<PathBuf>,
    #[arg(long)]
    domain: String,
    #[arg(long)]
    json: bool,
}

#[derive(Debug, clap::Args)]
struct UpdateJobArgs {
    #[arg(long, default_value = ".")]
    root: PathBuf,
    #[arg(long)]
    config: Option<PathBuf>,
    #[arg(long)]
    domain: String,
    #[arg(long)]
    reason: Option<String>,
    #[arg(long)]
    json: bool,
}

#[derive(Debug, clap::Args)]
struct ListJobsArgs {
    #[arg(long, default_value = ".")]
    root: PathBuf,
    #[arg(long)]
    config: Option<PathBuf>,
    #[arg(long)]
    json: bool,
}

#[derive(Debug, clap::Args)]
struct ReviewJobsArgs {
    #[arg(long, default_value = ".")]
    root: PathBuf,
    #[arg(long)]
    config: Option<PathBuf>,
    #[arg(long)]
    domain_config: Option<PathBuf>,
    #[arg(long)]
    dry_run: bool,
    #[arg(long)]
    run_approved: bool,
    #[arg(long)]
    json: bool,
}

#[derive(Debug, clap::Args)]
struct CompleteJobArgs {
    #[arg(long, default_value = ".")]
    root: PathBuf,
    #[arg(long)]
    config: Option<PathBuf>,
    #[arg(long)]
    domain: String,
    #[arg(long)]
    status: String,
    #[arg(long)]
    report: PathBuf,
    #[arg(long = "registry-update")]
    registry_update: PathBuf,
    #[arg(long)]
    reason: Option<String>,
    #[arg(long = "source-rows")]
    source_rows: Option<u64>,
    #[arg(long = "parsed-rows")]
    parsed_rows: Option<u64>,
    #[arg(long = "machine-positive-rows")]
    machine_positive_rows: Option<u64>,
    #[arg(long = "audited-true-positive-rows")]
    audited_true_positive_rows: Option<u64>,
    #[arg(long = "reviewed-usable-rows")]
    reviewed_usable_rows: Option<u64>,
    #[arg(long = "likely-oos")]
    likely_oos: Option<u64>,
    #[arg(long)]
    json: bool,
}

#[derive(Debug, clap::Args)]
struct ResearchPromptArgs {
    #[arg(long, default_value = ".")]
    root: PathBuf,
    #[arg(long)]
    config: Option<PathBuf>,
    #[arg(long)]
    domain: String,
    #[arg(long)]
    out: Option<PathBuf>,
    #[arg(long)]
    json: bool,
}

fn main() -> anyhow::Result<()> {
    let cli = Cli::parse();
    match cli.command {
        Commands::Init { root, overwrite } => {
            init_project(&root, overwrite)?;
            println!("initialized domain-finder workspace at {}", root.display());
        }
        Commands::Scan { root, config, json } => {
            let cfg = load_config(&root, config.as_deref())?;
            let out = run_scan(&root, &cfg)?;
            if json {
                println!("{}", serde_json::to_string_pretty(&out.candidates)?);
            } else {
                println!("candidates: {}", out.candidates.len());
                println!("report: {}", out.report_path.display());
                println!("json: {}", out.json_path.display());
                println!("intakes: {}", out.intake_dir.display());
            }
        }
        Commands::Watch {
            root,
            config,
            interval_secs,
            iterations,
        } => {
            let mut count = 0u64;
            loop {
                let cfg = load_config(&root, config.as_deref())?;
                let out = run_scan(&root, &cfg)?;
                println!(
                    "scan {} complete: {} candidates -> {}",
                    count + 1,
                    out.candidates.len(),
                    out.report_path.display()
                );
                count += 1;
                if let Some(max) = iterations {
                    if count >= max {
                        break;
                    }
                }
                thread::sleep(Duration::from_secs(interval_secs));
            }
        }
        Commands::Collect {
            root,
            family,
            output_dir,
            json,
        } => {
            let out = collect_to_generated_dir(&root, output_dir.as_deref(), family.as_deref())?;
            if json {
                println!("{}", serde_json::to_string_pretty(&out.observations)?);
            } else {
                println!(
                    "wrote {} observations across {} files",
                    out.observations.len(),
                    out.files.len()
                );
                for file in &out.files {
                    println!(
                        "{}: {} observations -> {}",
                        file.family,
                        file.observation_count,
                        file.path.display()
                    );
                }
                println!("families: {}", available_families().join(", "));
            }
        }
        Commands::ProbeSecItems(args) => run_probe("sec", args)?,
        Commands::ProbeAgencyActions(args) => run_probe("agency", args)?,
        Commands::ProbeFdaEnforcement(args) => run_probe("fda", args)?,
        Commands::ProbeLitigation(args) => run_probe("litigation", args)?,
        Commands::ProbeIndexEvents(args) => run_probe("index", args)?,
        Commands::Score {
            input,
            slug,
            registry,
            output,
            json,
        } => {
            let candidate = score_single(&input, slug.as_deref(), registry.as_deref())
                .with_context(|| score_usage_hint(&input))?;
            if let Some(path) = output {
                let report = discovery_report(std::slice::from_ref(&candidate));
                write_string(&path, &report)?;
                println!("wrote {}", path.display());
            }
            if json {
                println!("{}", serde_json::to_string_pretty(&candidate)?);
            } else {
                println!(
                    "{} score={}/30 gate={}",
                    candidate.slug,
                    candidate.score.total,
                    candidate.gate.label()
                );
                for warning in &candidate.warnings {
                    println!("warning: {}", warning);
                }
            }
        }
        Commands::MakeIntake {
            input,
            slug,
            output,
            registry,
        } => {
            let candidate = score_single(&input, slug.as_deref(), registry.as_deref())
                .with_context(|| score_usage_hint(&input))?;
            write_string(&output, &intake_doc(&candidate))?;
            println!("wrote {}", output.display());
        }
        Commands::Top {
            root,
            config,
            limit,
            json,
        } => {
            let cfg = load_config(&root, config.as_deref())?;
            let out = run_scan(&root, &cfg)?;
            let top = top_candidates(&out.candidates, limit);
            if json {
                println!("{}", serde_json::to_string_pretty(&top)?);
            } else {
                print!("{}", top_report(&top));
            }
        }
        Commands::Explain {
            root,
            config,
            slug,
            json,
        } => {
            let cfg = load_config(&root, config.as_deref())?;
            let out = run_scan(&root, &cfg)?;
            let candidate = find_candidate(&out.candidates, &slug)?;
            let explanation = explain_candidate(candidate);
            if json {
                println!("{}", serde_json::to_string_pretty(&explanation)?);
            } else {
                print!("{}", explain_report(&explanation));
            }
        }
        Commands::Diff { old, new, json } => {
            let old_candidates = load_candidates(&old)?;
            let new_candidates = load_candidates(&new)?;
            let diff = diff_candidates(&old_candidates, &new_candidates);
            if json {
                println!("{}", serde_json::to_string_pretty(&diff)?);
            } else {
                print!("{}", diff_report(&diff));
            }
        }
        Commands::Alerts { root, config, json } => {
            let cfg = load_config(&root, config.as_deref())?;
            let out = run_scan(&root, &cfg)?;
            let alerts = current_alerts(&out.candidates);
            if json {
                println!("{}", serde_json::to_string_pretty(&alerts)?);
            } else {
                print!("{}", alerts_report(&alerts));
            }
        }
        Commands::Dashboard {
            root,
            out,
            registry,
            candidates,
            json,
        } => {
            let output = build_dashboard(&DashboardOptions {
                root,
                out_dir: out,
                registry_path: registry,
                candidates_path: candidates,
            })?;
            if json {
                println!("{}", serde_json::to_string_pretty(&output.state)?);
            } else {
                println!("dashboard: {}", output.index_path.display());
                println!("state: {}", output.state_path.display());
                println!("domains: {}", output.state.domains.len());
            }
        }
        Commands::Orchestrate(args) => {
            run_orchestrate_command(args)?;
        }
        Commands::Approve(args) => {
            let cfg = load_orchestrator_config(&args.root, args.config.as_deref())?;
            let job = approve_job(&args.root, &cfg, &args.domain)?;
            if args.json {
                println!("{}", serde_json::to_string_pretty(&job)?);
            } else {
                println!("approved {} -> status={}", job.domain, job.status.label());
            }
        }
        Commands::Reject(args) => {
            let cfg = load_orchestrator_config(&args.root, args.config.as_deref())?;
            let job = reject_job(&args.root, &cfg, &args.domain, args.reason.as_deref())?;
            if args.json {
                println!("{}", serde_json::to_string_pretty(&job)?);
            } else {
                println!("rejected {} -> status={}", job.domain, job.status.label());
            }
        }
        Commands::ArchiveJob(args) => {
            let cfg = load_orchestrator_config(&args.root, args.config.as_deref())?;
            let job = archive_job(&args.root, &cfg, &args.domain, args.reason.as_deref())?;
            if args.json {
                println!("{}", serde_json::to_string_pretty(&job)?);
            } else {
                println!("archived {} -> status={}", job.domain, job.status.label());
            }
        }
        Commands::CompleteJob(args) => {
            let cfg = load_orchestrator_config(&args.root, args.config.as_deref())?;
            let (job, feedback) = complete_job(
                &args.root,
                &cfg,
                &args.domain,
                CompleteJobOptions {
                    final_status: args.status,
                    report_path: args.report,
                    registry_update_path: args.registry_update,
                    reason: args.reason,
                    source_rows: args.source_rows,
                    parsed_rows: args.parsed_rows,
                    machine_positive_rows: args.machine_positive_rows,
                    audited_true_positive_rows: args.audited_true_positive_rows,
                    reviewed_usable_rows: args.reviewed_usable_rows,
                    likely_oos: args.likely_oos,
                },
            )?;
            if args.json {
                println!("{}", serde_json::to_string_pretty(&feedback)?);
            } else {
                println!(
                    "completed {} -> status={} final_status={}",
                    job.domain,
                    job.status.label(),
                    feedback.status
                );
            }
        }
        Commands::RunApproved(args) => {
            let cfg = load_orchestrator_config(&args.root, args.config.as_deref())?;
            let jobs = run_approved_jobs(&args.root, &cfg)?;
            if args.json {
                println!("{}", serde_json::to_string_pretty(&jobs)?);
            } else if jobs.is_empty() {
                println!("no approved jobs were run");
            } else {
                print!("{}", jobs_report(&jobs));
            }
        }
        Commands::ReviewJobs(args) => {
            let cfg = load_orchestrator_config(&args.root, args.config.as_deref())?;
            let domain_cfg = load_config(&args.root, args.domain_config.as_deref())?;
            let output = review_jobs(
                &args.root,
                &domain_cfg,
                &cfg,
                ReviewJobsOptions {
                    dry_run: args.dry_run,
                    run_approved: args.run_approved,
                },
            )?;
            if args.json {
                println!("{}", serde_json::to_string_pretty(&output)?);
            } else {
                print!("{}", review_jobs_report(&output));
                println!(
                    "\napproved={} rejected={} prompts_generated={}",
                    output.approved.len(),
                    output.rejected.len(),
                    output.prompts_generated.len()
                );
            }
        }
        Commands::ListJobs(args) => {
            let cfg = load_orchestrator_config(&args.root, args.config.as_deref())?;
            let jobs = list_jobs(&args.root, &cfg)?;
            if args.json {
                println!("{}", serde_json::to_string_pretty(&jobs)?);
            } else {
                print!("{}", jobs_report(&jobs));
            }
        }
        Commands::JobHistory(args) => {
            let cfg = load_orchestrator_config(&args.root, args.config.as_deref())?;
            let history = job_history(&args.root, &cfg)?;
            if args.json {
                println!("{}", serde_json::to_string_pretty(&history)?);
            } else if history.is_empty() {
                println!("no history snapshots found");
            } else {
                for path in history {
                    println!("{}", path.display());
                }
            }
        }
        Commands::NotificationDigest(args) => {
            let cfg = load_orchestrator_config(&args.root, args.config.as_deref())?;
            let path = notification_digest(&args.root, &cfg)?;
            if args.json {
                println!("{}", serde_json::to_string_pretty(&path)?);
            } else {
                println!("digest: {}", path.display());
            }
        }
        Commands::ResearchPrompt(args) => {
            let cfg = load_orchestrator_config(&args.root, args.config.as_deref())?;
            let job =
                generate_research_prompt(&args.root, &cfg, &args.domain, args.out.as_deref())?;
            if args.json {
                println!("{}", serde_json::to_string_pretty(&job)?);
            } else if let Some(path) = &job.prompt_path {
                println!("prompt: {}", path);
            } else {
                println!("prompt generated for {}", job.domain);
            }
        }
    }
    Ok(())
}

fn run_orchestrate_command(args: OrchestrateArgs) -> anyhow::Result<()> {
    let cfg = load_orchestrator_config(&args.root, args.config.as_deref())?;
    let domain_cfg = load_config(&args.root, args.domain_config.as_deref())?;
    let interval_secs = args.interval_secs.unwrap_or(cfg.loop_config.interval_secs);
    let mut count = 0u64;
    loop {
        let output = run_orchestrator_once(
            &args.root,
            &domain_cfg,
            &cfg,
            OrchestratorRunOptions {
                dry_run: args.dry_run,
                offline_probes: args.offline_probes,
                auto_mode: args.auto,
            },
        )?;
        if args.json {
            println!("{}", serde_json::to_string_pretty(&output)?);
        } else {
            println!(
                "orchestrator run complete: candidates={} new_jobs={} existing_jobs={} notification={}",
                output.candidates_seen,
                output.new_jobs.len(),
                output.existing_jobs.len(),
                output.notification_path.display()
            );
        }
        count += 1;
        if !args.watch || args.once {
            break;
        }
        if let Some(max) = args.iterations {
            if count >= max {
                break;
            }
        }
        thread::sleep(Duration::from_secs(interval_secs));
    }
    Ok(())
}

fn run_probe(family: &str, args: ProbeArgs) -> anyhow::Result<()> {
    let out = probe_family(
        &args.root,
        &ProbeOptions {
            family: family.to_string(),
            output_dir: args.output_dir,
            timeout_secs: args.timeout_secs,
            offline: args.offline,
        },
    )?;
    if args.json {
        println!("{}", serde_json::to_string_pretty(&out.observations)?);
    } else {
        println!(
            "probed {} observations for {} -> {}",
            out.observations.len(),
            out.family,
            out.path.display()
        );
        println!("report: {}", out.report_path.display());
        for result in &out.results {
            println!(
                "{}: {} http={} bytes={} keyword_hits={}",
                result.slug,
                result.status,
                result
                    .http_status
                    .map(|s| s.to_string())
                    .unwrap_or_else(|| "n/a".to_string()),
                result
                    .byte_len
                    .map(|n| n.to_string())
                    .unwrap_or_else(|| "n/a".to_string()),
                result.keyword_hits
            );
        }
    }
    Ok(())
}

fn load_config(root: &Path, override_path: Option<&Path>) -> anyhow::Result<Config> {
    let path = override_path
        .map(|p| p.to_path_buf())
        .unwrap_or_else(|| Config::default_path(root));
    if path.exists() {
        Config::load(&path)
    } else {
        Ok(Config::default())
    }
}

fn load_orchestrator_config(
    root: &Path,
    override_path: Option<&Path>,
) -> anyhow::Result<OrchestratorConfig> {
    let path = override_path
        .map(|p| p.to_path_buf())
        .unwrap_or_else(|| OrchestratorConfig::default_path(root));
    if path.exists() {
        OrchestratorConfig::load(&path)
    } else {
        Ok(OrchestratorConfig::default())
    }
}

fn score_single(
    input: &Path,
    slug_filter: Option<&str>,
    registry_path: Option<&Path>,
) -> anyhow::Result<DomainCandidate> {
    let observations = read_observations_path(input)
        .with_context(|| format!("failed to read candidate input {}", input.display()))?;
    let mut candidate = candidate_from_observations(observations, slug_filter)?;

    let cfg = Config::default();
    if let Some(path) = registry_path {
        let registry = Registry::load_markdown(path)?;
        candidate.registry_status = registry.get(&candidate.slug).cloned();
    }
    Ok(score_candidate(candidate, &cfg))
}

fn score_usage_hint(input: &Path) -> String {
    format!(
        "score/make-intake are single-domain commands for {}. Use `domain-finder scan` for multi-domain feeds or pass `--slug <domain>`.",
        input.display()
    )
}

fn find_candidate<'a>(
    candidates: &'a [DomainCandidate],
    slug: &str,
) -> anyhow::Result<&'a DomainCandidate> {
    let normalized = domain_finder::registry::normalize_slug(slug);
    candidates
        .iter()
        .find(|candidate| candidate.slug == normalized)
        .ok_or_else(|| anyhow::anyhow!("domain `{}` was not found in current scan", slug))
}
