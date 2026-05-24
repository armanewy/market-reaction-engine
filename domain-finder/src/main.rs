use anyhow::Context;
use clap::{Parser, Subcommand};
use domain_finder::collectors::{available_families, collect_to_generated_dir};
use domain_finder::config::Config;
use domain_finder::io::{read_observations_path, write_string};
use domain_finder::model::DomainCandidate;
use domain_finder::pipeline::{candidate_from_observations, init_project, run_scan};
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
