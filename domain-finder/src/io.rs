use anyhow::{bail, Context};
use serde::Deserialize;
use std::fs::{self, File};
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};

use crate::model::DomainObservation;

pub fn ensure_dir(path: &Path) -> anyhow::Result<()> {
    fs::create_dir_all(path).with_context(|| format!("failed to create {}", path.display()))
}

pub fn write_string(path: &Path, text: &str) -> anyhow::Result<()> {
    if let Some(parent) = path.parent() {
        ensure_dir(parent)?;
    }
    let mut f =
        File::create(path).with_context(|| format!("failed to create {}", path.display()))?;
    f.write_all(text.as_bytes())
        .with_context(|| format!("failed to write {}", path.display()))
}

pub fn read_observations_path(path: &Path) -> anyhow::Result<Vec<DomainObservation>> {
    if path.is_dir() {
        let mut out = Vec::new();
        let mut files = Vec::new();
        collect_observation_files(path, &mut files)?;
        files.sort();
        for p in files {
            out.extend(read_observations_path(&p)?);
        }
        Ok(out)
    } else if path.extension().and_then(|s| s.to_str()) == Some("jsonl") {
        read_jsonl(path)
    } else if path.extension().and_then(|s| s.to_str()) == Some("json") {
        read_json(path)
    } else if path.extension().and_then(|s| s.to_str()) == Some("toml") {
        read_toml(path)
    } else {
        bail!(
            "unsupported observation path {}; expected .jsonl, .json, .toml, or directory",
            path.display()
        )
    }
}

fn collect_observation_files(path: &Path, files: &mut Vec<PathBuf>) -> anyhow::Result<()> {
    for entry in fs::read_dir(path).with_context(|| format!("failed to list {}", path.display()))? {
        let entry = entry?;
        let p = entry.path();
        if p.is_dir() {
            collect_observation_files(&p, files)?;
        } else if matches!(
            p.extension().and_then(|s| s.to_str()),
            Some("jsonl" | "json" | "toml")
        ) {
            files.push(p);
        }
    }
    Ok(())
}

fn read_jsonl(path: &Path) -> anyhow::Result<Vec<DomainObservation>> {
    let f = File::open(path).with_context(|| format!("failed to open {}", path.display()))?;
    let reader = BufReader::new(f);
    let mut out = Vec::new();
    for (idx, line) in reader.lines().enumerate() {
        let line =
            line.with_context(|| format!("failed to read {} line {}", path.display(), idx + 1))?;
        let trimmed = line.trim();
        if trimmed.is_empty() || trimmed.starts_with('#') {
            continue;
        }
        let obs: DomainObservation = serde_json::from_str(trimmed)
            .with_context(|| format!("invalid JSONL in {} line {}", path.display(), idx + 1))?;
        out.push(obs);
    }
    Ok(out)
}

fn read_json(path: &Path) -> anyhow::Result<Vec<DomainObservation>> {
    let text =
        fs::read_to_string(path).with_context(|| format!("failed to read {}", path.display()))?;
    #[derive(Deserialize)]
    #[serde(untagged)]
    enum JsonShape {
        One(Box<DomainObservation>),
        Many(Vec<DomainObservation>),
    }
    match serde_json::from_str::<JsonShape>(&text)
        .with_context(|| format!("invalid JSON {}", path.display()))?
    {
        JsonShape::One(obs) => Ok(vec![*obs]),
        JsonShape::Many(obs) => Ok(obs),
    }
}

fn read_toml(path: &Path) -> anyhow::Result<Vec<DomainObservation>> {
    let text =
        fs::read_to_string(path).with_context(|| format!("failed to read {}", path.display()))?;
    #[derive(Deserialize)]
    struct Wrapper {
        observations: Vec<DomainObservation>,
    }
    let w: Wrapper =
        toml::from_str(&text).with_context(|| format!("invalid TOML {}", path.display()))?;
    Ok(w.observations)
}

pub fn rel(root: &Path, p: &str) -> PathBuf {
    let path = PathBuf::from(p);
    if path.is_absolute() {
        path
    } else {
        root.join(path)
    }
}
