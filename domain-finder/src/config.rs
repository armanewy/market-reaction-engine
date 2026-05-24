use anyhow::Context;
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Config {
    #[serde(default)]
    pub thresholds: Thresholds,
    #[serde(default)]
    pub hard_minimums: HardMinimums,
    #[serde(default)]
    pub registry: RegistryConfig,
    #[serde(default)]
    pub feeds: Vec<FeedConfig>,
    #[serde(default = "default_artifacts_dir")]
    pub artifacts_dir: String,
    #[serde(default = "default_intake_dir")]
    pub intake_dir: String,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            thresholds: Thresholds::default(),
            hard_minimums: HardMinimums::default(),
            registry: RegistryConfig::default(),
            feeds: vec![FeedConfig::default()],
            artifacts_dir: default_artifacts_dir(),
            intake_dir: default_intake_dir(),
        }
    }
}

impl Config {
    pub fn load(path: &Path) -> anyhow::Result<Self> {
        let text = fs::read_to_string(path)
            .with_context(|| format!("failed to read config {}", path.display()))?;
        let cfg: Config = toml::from_str(&text)
            .with_context(|| format!("failed to parse config {}", path.display()))?;
        Ok(cfg)
    }

    pub fn default_path(root: &Path) -> PathBuf {
        root.join("config/domain_finder.toml")
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Thresholds {
    #[serde(default = "default_full_lifecycle")]
    pub full_lifecycle: u8,
    #[serde(default = "default_feasibility")]
    pub feasibility_only: u8,
    #[serde(default = "default_backlog")]
    pub backlog: u8,
}

impl Default for Thresholds {
    fn default() -> Self {
        Self {
            full_lifecycle: default_full_lifecycle(),
            feasibility_only: default_feasibility(),
            backlog: default_backlog(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HardMinimums {
    #[serde(default = "default_hard_min")]
    pub public_timestamp_clarity: u8,
    #[serde(default = "default_hard_min")]
    pub delayed_digestion_plausibility: u8,
    #[serde(default = "default_hard_min")]
    pub materiality_field_clarity: u8,
    #[serde(default = "default_hard_min")]
    pub sample_size_likelihood: u8,
}

impl Default for HardMinimums {
    fn default() -> Self {
        Self {
            public_timestamp_clarity: default_hard_min(),
            delayed_digestion_plausibility: default_hard_min(),
            materiality_field_clarity: default_hard_min(),
            sample_size_likelihood: default_hard_min(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RegistryConfig {
    #[serde(default = "default_registry_path")]
    pub path: String,
    #[serde(default)]
    pub frozen_statuses: Vec<String>,
    #[serde(default)]
    pub monitor_statuses: Vec<String>,
}

impl Default for RegistryConfig {
    fn default() -> Self {
        Self {
            path: default_registry_path(),
            frozen_statuses: vec![
                "frozen".to_string(),
                "failed".to_string(),
                "failed_falsification".to_string(),
                "failed_execution".to_string(),
                "mapping_insufficient".to_string(),
                "parser_not_trusted".to_string(),
            ],
            monitor_statuses: vec!["underpowered_monitor".to_string()],
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FeedConfig {
    #[serde(default = "default_feed_name")]
    pub name: String,
    #[serde(default = "default_feed_kind")]
    pub kind: String,
    #[serde(default = "default_feed_path")]
    pub path: String,
}

impl Default for FeedConfig {
    fn default() -> Self {
        Self {
            name: default_feed_name(),
            kind: default_feed_kind(),
            path: default_feed_path(),
        }
    }
}

fn default_full_lifecycle() -> u8 {
    24
}
fn default_feasibility() -> u8 {
    18
}
fn default_backlog() -> u8 {
    12
}
fn default_hard_min() -> u8 {
    2
}
fn default_registry_path() -> String {
    "docs/DOMAIN_RESEARCH_REGISTRY.md".to_string()
}
fn default_feed_name() -> String {
    "local_observations".to_string()
}
fn default_feed_kind() -> String {
    "jsonl".to_string()
}
fn default_feed_path() -> String {
    "data/observations".to_string()
}
fn default_artifacts_dir() -> String {
    "artifacts/domain_finder".to_string()
}
fn default_intake_dir() -> String {
    "docs/intakes/generated".to_string()
}
