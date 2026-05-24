use crate::collectors::{available_families, built_in_observations};
use crate::io::{ensure_dir, write_string};
use crate::model::DomainObservation;
use anyhow::Context;
use chrono::Utc;
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::time::Duration;

pub const DEFAULT_PROBED_DIR: &str = "data/observations/probed";
const USER_AGENT: &str = "domain-finder/0.1 source-probe (Market Reaction Engine)";

#[derive(Debug, Clone)]
pub struct ProbeOptions {
    pub family: String,
    pub output_dir: Option<PathBuf>,
    pub timeout_secs: u64,
    pub offline: bool,
}

#[derive(Debug, Clone)]
pub struct ProbeOutput {
    pub family: String,
    pub path: PathBuf,
    pub report_path: PathBuf,
    pub observations: Vec<DomainObservation>,
    pub results: Vec<ProbeResult>,
}

#[derive(Debug, Clone)]
pub struct ProbeResult {
    pub slug: String,
    pub source_url: Option<String>,
    pub status: String,
    pub http_status: Option<u16>,
    pub byte_len: Option<usize>,
    pub keyword_hits: usize,
    pub note: String,
}

pub fn probe_family(root: &Path, options: &ProbeOptions) -> anyhow::Result<ProbeOutput> {
    let family = normalize_family(&options.family);
    anyhow::ensure!(
        available_families().contains(&family.as_str()),
        "unknown probe family `{}`; expected one of: {}",
        options.family,
        available_families().join(", ")
    );

    let output_dir = options
        .output_dir
        .as_ref()
        .map(|p| {
            if p.is_absolute() {
                p.clone()
            } else {
                root.join(p)
            }
        })
        .unwrap_or_else(|| root.join(DEFAULT_PROBED_DIR));
    ensure_dir(&output_dir)?;

    let mut cache = BTreeMap::new();
    let mut observations = Vec::new();
    let mut results = Vec::new();
    for mut obs in built_in_observations(Some(&family))? {
        let result = probe_observation(&obs, options, &mut cache);
        apply_probe_result(&mut obs, &family, &result);
        results.push(result);
        observations.push(obs);
    }

    let path = output_dir.join(format!("{}_probe_observations.jsonl", family));
    let mut jsonl = String::new();
    for obs in &observations {
        jsonl.push_str(&serde_json::to_string(obs)?);
        jsonl.push('\n');
    }
    write_string(&path, &jsonl)
        .with_context(|| format!("failed to write probe output {}", path.display()))?;

    let report_path = output_dir.join(format!("{}_source_probe_report.md", family));
    write_string(&report_path, &probe_report(&family, &results))
        .with_context(|| format!("failed to write probe report {}", report_path.display()))?;

    Ok(ProbeOutput {
        family,
        path,
        report_path,
        observations,
        results,
    })
}

fn probe_observation(
    obs: &DomainObservation,
    options: &ProbeOptions,
    cache: &mut BTreeMap<String, ProbeResult>,
) -> ProbeResult {
    let Some(url) = obs.source_url.clone() else {
        return ProbeResult {
            slug: obs.slug.clone(),
            source_url: None,
            status: "missing_url".to_string(),
            http_status: None,
            byte_len: None,
            keyword_hits: 0,
            note: "observation has no source_url".to_string(),
        };
    };

    if let Some(cached) = cache.get(&url) {
        let mut result = cached.clone();
        result.slug = obs.slug.clone();
        return result;
    }

    let result = if options.offline {
        ProbeResult {
            slug: obs.slug.clone(),
            source_url: Some(url.clone()),
            status: "offline".to_string(),
            http_status: None,
            byte_len: None,
            keyword_hits: 0,
            note: "offline probe recorded source URL without fetching".to_string(),
        }
    } else {
        fetch_source(obs, &url, options.timeout_secs)
    };
    cache.insert(url, result.clone());
    result
}

fn fetch_source(obs: &DomainObservation, url: &str, timeout_secs: u64) -> ProbeResult {
    let agent = ureq::AgentBuilder::new()
        .timeout(Duration::from_secs(timeout_secs.max(1)))
        .build();
    let response = agent.get(url).set("User-Agent", USER_AGENT).call();

    match response {
        Ok(response) => {
            let status = response.status();
            let text = response.into_string().unwrap_or_default();
            let byte_len = text.len();
            let keyword_hits = keyword_hits(obs, &text);
            ProbeResult {
                slug: obs.slug.clone(),
                source_url: Some(url.to_string()),
                status: if (200..400).contains(&status) {
                    "ok".to_string()
                } else {
                    "http_non_success".to_string()
                },
                http_status: Some(status),
                byte_len: Some(byte_len),
                keyword_hits,
                note: format!(
                    "fetched source; {} bytes; {} keyword hits",
                    byte_len, keyword_hits
                ),
            }
        }
        Err(ureq::Error::Status(status, response)) => {
            let text = response.into_string().unwrap_or_default();
            let byte_len = text.len();
            let keyword_hits = keyword_hits(obs, &text);
            ProbeResult {
                slug: obs.slug.clone(),
                source_url: Some(url.to_string()),
                status: "http_non_success".to_string(),
                http_status: Some(status),
                byte_len: Some(byte_len),
                keyword_hits,
                note: format!(
                    "source returned HTTP {}; {} bytes; {} keyword hits",
                    status, byte_len, keyword_hits
                ),
            }
        }
        Err(err) => ProbeResult {
            slug: obs.slug.clone(),
            source_url: Some(url.to_string()),
            status: "fetch_error".to_string(),
            http_status: None,
            byte_len: None,
            keyword_hits: 0,
            note: err.to_string(),
        },
    }
}

fn apply_probe_result(obs: &mut DomainObservation, family: &str, result: &ProbeResult) {
    obs.observed_at = Some(Utc::now().to_rfc3339());
    obs.proposed_by = Some(format!("domain-finder source probe: {}", family));
    push_unique(&mut obs.tags, "source_probe");
    push_unique(&mut obs.tags, &format!("probe:{}", family));
    push_unique(&mut obs.tags, &format!("probe_status:{}", result.status));
    if let Some(http_status) = result.http_status {
        push_unique(&mut obs.tags, &format!("http_status:{}", http_status));
    }
    obs.evidence.push(format!(
        "source probe: status={}, http_status={}, bytes={}, keyword_hits={}, note={}",
        result.status,
        result
            .http_status
            .map(|s| s.to_string())
            .unwrap_or_else(|| "n/a".to_string()),
        result
            .byte_len
            .map(|n| n.to_string())
            .unwrap_or_else(|| "n/a".to_string()),
        result.keyword_hits,
        result.note
    ));
}

fn keyword_hits(obs: &DomainObservation, text: &str) -> usize {
    let haystack = text.to_ascii_lowercase();
    let mut needles = Vec::new();
    needles.push(obs.source_name.to_ascii_lowercase());
    needles.push(obs.source_kind.to_ascii_lowercase());
    needles.extend(obs.tags.iter().map(|tag| tag.to_ascii_lowercase()));
    needles
        .into_iter()
        .flat_map(|needle| {
            needle
                .split(|ch: char| !ch.is_ascii_alphanumeric())
                .filter(|part| part.len() >= 4)
                .map(str::to_string)
                .collect::<Vec<_>>()
        })
        .filter(|needle| haystack.contains(needle))
        .count()
}

fn probe_report(family: &str, results: &[ProbeResult]) -> String {
    let mut out = String::new();
    out.push_str(&format!("# Source Probe Report: {}\n\n", family));
    out.push_str(&format!("Generated: `{}`\n\n", Utc::now().to_rfc3339()));
    out.push_str("| Domain | Probe Status | HTTP | Bytes | Keyword Hits | Source URL |\n");
    out.push_str("| --- | --- | ---: | ---: | ---: | --- |\n");
    for result in results {
        out.push_str(&format!(
            "| `{}` | `{}` | {} | {} | {} | {} |\n",
            result.slug,
            result.status,
            result
                .http_status
                .map(|s| s.to_string())
                .unwrap_or_else(|| "-".to_string()),
            result
                .byte_len
                .map(|n| n.to_string())
                .unwrap_or_else(|| "-".to_string()),
            result.keyword_hits,
            result.source_url.as_deref().unwrap_or("-")
        ));
    }
    out
}

fn push_unique(items: &mut Vec<String>, item: &str) {
    if !items.iter().any(|existing| existing == item) {
        items.push(item.to_string());
    }
}

fn normalize_family(family: &str) -> String {
    family.trim().to_ascii_lowercase().replace([' ', '-'], "_")
}
