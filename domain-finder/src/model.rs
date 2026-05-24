use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct DomainObservation {
    pub slug: String,
    pub title: String,
    #[serde(default)]
    pub source_name: String,
    #[serde(default)]
    pub source_kind: String,
    #[serde(default)]
    pub source_url: Option<String>,
    #[serde(default)]
    pub official_source: bool,
    #[serde(default)]
    pub timestamp_quality: TimestampQuality,
    #[serde(default)]
    pub delayed_digest_reasons: Vec<String>,
    #[serde(default)]
    pub hard_negatives: Vec<String>,
    #[serde(default)]
    pub materiality_fields: Vec<String>,
    #[serde(default)]
    pub mapping_notes: Option<String>,
    #[serde(default)]
    pub sample_size_hint: Option<u32>,
    #[serde(default)]
    pub liquidity_notes: Option<String>,
    #[serde(default)]
    pub evidence: Vec<String>,
    #[serde(default)]
    pub tags: Vec<String>,
    #[serde(default)]
    pub observed_at: Option<String>,
    #[serde(default)]
    pub proposed_by: Option<String>,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, Default, Eq, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum TimestampQuality {
    Clear,
    PublicButSessionAmbiguous,
    RecordOnly,
    Fuzzy,
    #[default]
    Unknown,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct DomainCandidate {
    pub slug: String,
    pub title: String,
    pub observations: Vec<DomainObservation>,
    pub evidence_count: usize,
    pub official_source_count: usize,
    pub source_kinds: Vec<String>,
    pub hard_negatives: Vec<String>,
    pub materiality_fields: Vec<String>,
    pub delayed_digest_reasons: Vec<String>,
    pub max_sample_size_hint: Option<u32>,
    pub score: ScoreCard,
    pub gate: GateDecision,
    pub registry_status: Option<RegistryEntry>,
    pub warnings: Vec<String>,
}

impl DomainCandidate {
    pub fn from_observations(slug: String, observations: Vec<DomainObservation>) -> Self {
        let title = observations
            .iter()
            .find(|o| !o.title.trim().is_empty())
            .map(|o| o.title.clone())
            .unwrap_or_else(|| slug.clone());

        let mut source_kinds = BTreeSet::new();
        let mut hard_negatives = BTreeSet::new();
        let mut materiality_fields = BTreeSet::new();
        let mut delayed_digest_reasons = BTreeSet::new();
        let mut evidence_count = 0usize;
        let mut official_source_count = 0usize;
        let mut max_sample_size_hint: Option<u32> = None;

        for obs in &observations {
            if !obs.source_kind.trim().is_empty() {
                source_kinds.insert(obs.source_kind.clone());
            }
            for item in &obs.hard_negatives {
                if !item.trim().is_empty() {
                    hard_negatives.insert(item.clone());
                }
            }
            for item in &obs.materiality_fields {
                if !item.trim().is_empty() {
                    materiality_fields.insert(item.clone());
                }
            }
            for item in &obs.delayed_digest_reasons {
                if !item.trim().is_empty() {
                    delayed_digest_reasons.insert(item.clone());
                }
            }
            evidence_count += obs.evidence.len();
            if obs.official_source {
                official_source_count += 1;
            }
            if let Some(n) = obs.sample_size_hint {
                max_sample_size_hint = Some(max_sample_size_hint.map_or(n, |m| m.max(n)));
            }
        }

        Self {
            slug,
            title,
            observations,
            evidence_count,
            official_source_count,
            source_kinds: source_kinds.into_iter().collect(),
            hard_negatives: hard_negatives.into_iter().collect(),
            materiality_fields: materiality_fields.into_iter().collect(),
            delayed_digest_reasons: delayed_digest_reasons.into_iter().collect(),
            max_sample_size_hint,
            score: ScoreCard::default(),
            gate: GateDecision::Backlog,
            registry_status: None,
            warnings: Vec::new(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ScoreCard {
    pub official_source_quality: u8,
    pub public_timestamp_clarity: u8,
    pub delayed_digestion_plausibility: u8,
    pub hard_negative_clarity: u8,
    pub materiality_field_clarity: u8,
    pub sample_size_likelihood: u8,
    pub ticker_mapping_feasibility: u8,
    pub liquidity_execution_feasibility: u8,
    pub parser_audit_feasibility: u8,
    pub fresh_data_availability: u8,
    pub total: u8,
}

impl ScoreCard {
    pub fn recalc_total(&mut self) {
        self.total = self.official_source_quality
            + self.public_timestamp_clarity
            + self.delayed_digestion_plausibility
            + self.hard_negative_clarity
            + self.materiality_field_clarity
            + self.sample_size_likelihood
            + self.ticker_mapping_feasibility
            + self.liquidity_execution_feasibility
            + self.parser_audit_feasibility
            + self.fresh_data_availability;
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, Default, Eq, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum GateDecision {
    FullLifecycle,
    FeasibilityOnly,
    #[default]
    Backlog,
    Skip,
    BlockedByRegistry,
    MonitorOnly,
}

impl GateDecision {
    pub fn label(&self) -> &'static str {
        match self {
            GateDecision::FullLifecycle => "full_lifecycle",
            GateDecision::FeasibilityOnly => "feasibility_only",
            GateDecision::Backlog => "backlog",
            GateDecision::Skip => "skip",
            GateDecision::BlockedByRegistry => "blocked_by_registry",
            GateDecision::MonitorOnly => "monitor_only",
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RegistryEntry {
    pub domain: String,
    pub status: String,
    #[serde(default)]
    pub stage_reached: Option<String>,
    #[serde(default)]
    pub stop_reason: Option<String>,
    #[serde(default)]
    pub last_commit: Option<String>,
    #[serde(default)]
    pub revisit_trigger: Option<String>,
}
