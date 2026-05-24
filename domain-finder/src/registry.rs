use crate::model::RegistryEntry;
use anyhow::Context;
use std::collections::HashMap;
use std::fs;
use std::path::Path;

#[derive(Debug, Clone, Default)]
pub struct Registry {
    entries: HashMap<String, RegistryEntry>,
}

#[derive(Debug, Clone, Default)]
struct TableColumns {
    domain: Option<usize>,
    status: Option<usize>,
    stage_reached: Option<usize>,
    stop_reason: Option<usize>,
    last_commit: Option<usize>,
    revisit_trigger: Option<usize>,
}

impl Registry {
    pub fn load_markdown(path: &Path) -> anyhow::Result<Self> {
        if !path.exists() {
            return Ok(Self::default());
        }
        let text = fs::read_to_string(path)
            .with_context(|| format!("failed to read registry {}", path.display()))?;
        Ok(Self::parse_markdown(&text))
    }

    pub fn parse_markdown(text: &str) -> Self {
        let mut entries = HashMap::new();
        let mut current_domain: Option<String> = None;
        let mut current_status: Option<String> = None;
        let mut current_stage: Option<String> = None;
        let mut current_reason: Option<String> = None;
        let mut current_trigger: Option<String> = None;
        let mut active_table: Option<TableColumns> = None;

        for line in text.lines() {
            let trimmed = line.trim();
            if trimmed.starts_with('|') && trimmed.ends_with('|') {
                let cells = split_markdown_row(trimmed);
                if cells.is_empty() || is_separator_row(&cells) {
                    continue;
                }
                if let Some(cols) = TableColumns::from_header(&cells) {
                    active_table = Some(cols);
                    continue;
                }
                if let Some(cols) = &active_table {
                    if let Some(entry) = cols.entry_from_row(&cells) {
                        entries.insert(entry.domain.clone(), entry);
                    }
                }
                continue;
            }

            let lower = trimmed.to_lowercase();
            if lower.starts_with("domain:") {
                current_domain = Some(normalize_slug(
                    trimmed.split_once(':').map(|(_, v)| v).unwrap_or(""),
                ));
            } else if lower.starts_with("status:") {
                current_status = Some(clean_value(trimmed));
            } else if lower.starts_with("stage_reached:") || lower.starts_with("stage reached:") {
                current_stage = Some(clean_value(trimmed));
            } else if lower.starts_with("stop_reason:") || lower.starts_with("stop reason:") {
                current_reason = Some(clean_value(trimmed));
            } else if lower.starts_with("revisit_trigger:") || lower.starts_with("revisit trigger:")
            {
                current_trigger = Some(clean_value(trimmed));
            }

            if let (Some(domain), Some(status)) = (current_domain.clone(), current_status.clone()) {
                entries.entry(domain.clone()).or_insert(RegistryEntry {
                    domain,
                    status,
                    stage_reached: current_stage.clone(),
                    stop_reason: current_reason.clone(),
                    last_commit: None,
                    revisit_trigger: current_trigger.clone(),
                });
                current_domain = None;
                current_status = None;
                current_stage = None;
                current_reason = None;
                current_trigger = None;
            }
        }

        Self { entries }
    }

    pub fn get(&self, slug: &str) -> Option<&RegistryEntry> {
        self.entries.get(&normalize_slug(slug))
    }

    pub fn len(&self) -> usize {
        self.entries.len()
    }

    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }

    pub fn entries(&self) -> Vec<&RegistryEntry> {
        let mut entries = self.entries.values().collect::<Vec<_>>();
        entries.sort_by(|a, b| a.domain.cmp(&b.domain));
        entries
    }
}

impl TableColumns {
    fn from_header(cells: &[String]) -> Option<Self> {
        let mut cols = Self::default();
        for (idx, cell) in cells.iter().enumerate() {
            let header = normalize_header(cell);
            if matches!(header.as_str(), "domain" | "slug" | "domain_slug" | "name") {
                cols.domain = Some(idx);
            } else if matches!(
                header.as_str(),
                "status" | "final_status" | "current_status" | "verdict"
            ) {
                cols.status = Some(idx);
            } else if matches!(header.as_str(), "stage_reached" | "stage" | "stage_reach") {
                cols.stage_reached = Some(idx);
            } else if matches!(
                header.as_str(),
                "stop_reason" | "stop" | "reason" | "blocker"
            ) {
                cols.stop_reason = Some(idx);
            } else if matches!(
                header.as_str(),
                "last_commit" | "last_known_commit" | "commit" | "last_known"
            ) {
                cols.last_commit = Some(idx);
            } else if matches!(header.as_str(), "revisit_trigger" | "revisit" | "trigger") {
                cols.revisit_trigger = Some(idx);
            }
        }

        if cols.domain.is_some() && cols.status.is_some() {
            Some(cols)
        } else {
            None
        }
    }

    fn entry_from_row(&self, cells: &[String]) -> Option<RegistryEntry> {
        let domain = normalize_slug(self.cell(cells, self.domain)?);
        let status = clean_cell(self.cell(cells, self.status)?);
        if domain.is_empty() || status.is_empty() {
            return None;
        }
        Some(RegistryEntry {
            domain,
            status,
            stage_reached: self
                .cell(cells, self.stage_reached)
                .map(clean_cell)
                .filter(|s| !s.is_empty()),
            stop_reason: self
                .cell(cells, self.stop_reason)
                .map(clean_cell)
                .filter(|s| !s.is_empty()),
            last_commit: self
                .cell(cells, self.last_commit)
                .map(clean_cell)
                .filter(|s| !s.is_empty()),
            revisit_trigger: self
                .cell(cells, self.revisit_trigger)
                .map(clean_cell)
                .filter(|s| !s.is_empty()),
        })
    }

    fn cell<'a>(&self, cells: &'a [String], idx: Option<usize>) -> Option<&'a str> {
        idx.and_then(|i| cells.get(i))
            .map(|s| s.as_str())
            .filter(|s| !s.trim().is_empty())
    }
}

fn split_markdown_row(line: &str) -> Vec<String> {
    line.trim()
        .trim_matches('|')
        .split('|')
        .map(clean_cell)
        .collect()
}

fn clean_cell(s: &str) -> String {
    s.trim()
        .trim()
        .replace('`', "")
        .replace("**", "")
        .replace("\\_", "_")
}

fn clean_value(line: &str) -> String {
    line.split_once(':')
        .map(|(_, v)| clean_cell(v))
        .unwrap_or_default()
}

fn normalize_header(s: &str) -> String {
    clean_cell(s)
        .to_ascii_lowercase()
        .replace([' ', '-'], "_")
        .trim_matches('_')
        .to_string()
}

fn is_separator_row(cells: &[String]) -> bool {
    cells
        .iter()
        .all(|c| c.chars().all(|ch| ch == '-' || ch == ':' || ch == ' '))
}

pub fn normalize_slug(s: &str) -> String {
    let mut out = String::new();
    let mut last_underscore = false;
    for ch in s.trim().trim_matches('`').chars() {
        if ch.is_ascii_alphanumeric() {
            out.push(ch.to_ascii_lowercase());
            last_underscore = false;
        } else if !last_underscore {
            out.push('_');
            last_underscore = true;
        }
    }
    out.trim_matches('_').to_string()
}
