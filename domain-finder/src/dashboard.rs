use crate::io::{ensure_dir, write_string};
use crate::model::{DomainCandidate, RegistryEntry};
use crate::operations::{current_alerts, top_candidates, AlertOutput, TopEntry};
use crate::registry::{normalize_slug, Registry};
use chrono::Utc;
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone)]
pub struct DashboardOptions {
    pub root: PathBuf,
    pub out_dir: PathBuf,
    pub registry_path: Option<PathBuf>,
    pub candidates_path: Option<PathBuf>,
}

#[derive(Debug, Clone)]
pub struct DashboardOutput {
    pub out_dir: PathBuf,
    pub index_path: PathBuf,
    pub state_path: PathBuf,
    pub state: DashboardState,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DashboardState {
    pub generated_at: String,
    pub registry_path: Option<String>,
    pub summary: DashboardSummary,
    pub domains: Vec<DashboardDomain>,
    pub stop_reasons: Vec<StopReasonBucket>,
    pub infrastructure: Vec<InfrastructureItem>,
    pub domain_finder: DomainFinderDashboard,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct DashboardSummary {
    pub graduated_signals: usize,
    pub live_candidates: usize,
    pub monitors: usize,
    pub feasibility: usize,
    pub frozen_or_failed: usize,
    pub infrastructure: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DashboardDomain {
    pub slug: String,
    pub status: String,
    pub stage_reached: Option<String>,
    pub stop_reason: Option<String>,
    pub last_commit: Option<String>,
    pub revisit_trigger: Option<String>,
    pub category: String,
    pub current_recommendation: String,
    pub reports: Vec<ArtifactLink>,
    pub key_metrics: BTreeMap<String, String>,
    pub detail_page: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ArtifactLink {
    pub label: String,
    pub path: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StopReasonBucket {
    pub reason: String,
    pub count: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InfrastructureItem {
    pub name: String,
    pub status: String,
    pub description: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct DomainFinderDashboard {
    pub candidates_path: Option<String>,
    pub top_candidates: Vec<TopEntry>,
    pub alerts: Option<AlertOutput>,
    pub monitor_only_domains: Vec<String>,
    pub blocked_by_registry_domains: Vec<String>,
    pub feasibility_only_domains: Vec<String>,
}

pub fn build_dashboard(options: &DashboardOptions) -> anyhow::Result<DashboardOutput> {
    let root = absolute_or_current(&options.root)?;
    let out_dir = resolve_path(&root, &options.out_dir);
    let registry_path = resolve_registry_path(&root, options.registry_path.as_deref());
    let registry = registry_path
        .as_ref()
        .map(|path| Registry::load_markdown(path))
        .transpose()?
        .unwrap_or_default();
    let candidates_path = resolve_candidates_path(&root, options.candidates_path.as_deref());
    let candidates = candidates_path
        .as_ref()
        .map(|path| load_candidate_json(path))
        .transpose()?
        .unwrap_or_default();

    let report_files = collect_report_files(&root)?;
    let state = dashboard_state_from_parts(
        registry_path.as_deref(),
        &registry,
        candidates_path.as_deref(),
        &candidates,
        &report_files,
        &out_dir,
    );

    write_dashboard_files(&out_dir, &state)?;
    Ok(DashboardOutput {
        index_path: out_dir.join("index.html"),
        state_path: out_dir.join("dashboard_state.json"),
        out_dir,
        state,
    })
}

pub fn dashboard_state_from_parts(
    registry_path: Option<&Path>,
    registry: &Registry,
    candidates_path: Option<&Path>,
    candidates: &[DomainCandidate],
    report_files: &[PathBuf],
    out_dir: &Path,
) -> DashboardState {
    let mut domains = registry
        .entries()
        .into_iter()
        .map(|entry| dashboard_domain(entry, report_files, out_dir))
        .collect::<Vec<_>>();
    domains.sort_by(|a, b| {
        category_rank(&a.category)
            .cmp(&category_rank(&b.category))
            .then_with(|| a.slug.cmp(&b.slug))
    });

    let summary = summary_from_domains(&domains);
    let stop_reasons = stop_reason_buckets(&domains);
    let domain_finder = domain_finder_state(candidates_path, candidates);

    DashboardState {
        generated_at: Utc::now().to_rfc3339(),
        registry_path: registry_path.map(|path| path.display().to_string()),
        summary,
        domains,
        stop_reasons,
        infrastructure: infrastructure_items(),
        domain_finder,
    }
}

fn dashboard_domain(
    entry: &RegistryEntry,
    report_files: &[PathBuf],
    out_dir: &Path,
) -> DashboardDomain {
    let category = category_for_status(&entry.status);
    let reports = reports_for_domain(&entry.domain, report_files, out_dir);
    DashboardDomain {
        slug: entry.domain.clone(),
        status: entry.status.clone(),
        stage_reached: entry.stage_reached.clone(),
        stop_reason: entry.stop_reason.clone(),
        last_commit: entry.last_commit.clone(),
        revisit_trigger: entry.revisit_trigger.clone(),
        category: category.clone(),
        current_recommendation: recommendation_for(&category, entry),
        reports,
        key_metrics: key_metrics(entry),
        detail_page: format!("domains/{}.html", entry.domain),
    }
}

fn domain_finder_state(
    candidates_path: Option<&Path>,
    candidates: &[DomainCandidate],
) -> DomainFinderDashboard {
    let alerts = if candidates.is_empty() {
        None
    } else {
        Some(current_alerts(candidates))
    };
    DomainFinderDashboard {
        candidates_path: candidates_path.map(|path| path.display().to_string()),
        top_candidates: top_candidates(candidates, 10),
        alerts,
        monitor_only_domains: candidates
            .iter()
            .filter(|candidate| candidate.gate.label() == "monitor_only")
            .map(|candidate| candidate.slug.clone())
            .collect(),
        blocked_by_registry_domains: candidates
            .iter()
            .filter(|candidate| candidate.gate.label() == "blocked_by_registry")
            .map(|candidate| candidate.slug.clone())
            .collect(),
        feasibility_only_domains: candidates
            .iter()
            .filter(|candidate| candidate.gate.label() == "feasibility_only")
            .map(|candidate| candidate.slug.clone())
            .collect(),
    }
}

fn write_dashboard_files(out_dir: &Path, state: &DashboardState) -> anyhow::Result<()> {
    ensure_dir(out_dir)?;
    ensure_dir(&out_dir.join("assets"))?;
    ensure_dir(&out_dir.join("domains"))?;
    write_string(
        &out_dir.join("dashboard_state.json"),
        &serde_json::to_string_pretty(state)?,
    )?;
    write_string(&out_dir.join("assets/style.css"), STYLE_CSS)?;
    write_string(&out_dir.join("index.html"), &index_html(state))?;
    for domain in &state.domains {
        write_string(
            &out_dir.join(&domain.detail_page),
            &domain_detail_html(state, domain),
        )?;
    }
    Ok(())
}

fn index_html(state: &DashboardState) -> String {
    format!(
        r#"<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MRE Research Command Center</title>
  <link rel="stylesheet" href="assets/style.css">
</head>
<body>
  <header class="topbar">
    <div>
      <p class="eyebrow">Market Reaction Engine</p>
      <h1>Research Command Center</h1>
    </div>
    <div class="generated">Generated {generated}</div>
  </header>
  <main>
    {summary}
    {canonical}
    {domain_board}
    {stop_reasons}
    {finder}
    {infrastructure}
  </main>
</body>
</html>
"#,
        generated = escape(&state.generated_at),
        summary = summary_cards(&state.summary),
        canonical = canonical_panel(),
        domain_board = domain_board(state),
        stop_reasons = stop_reason_section(state),
        finder = domain_finder_section(state),
        infrastructure = infrastructure_section(state)
    )
}

fn domain_detail_html(state: &DashboardState, domain: &DashboardDomain) -> String {
    format!(
        r#"<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <link rel="stylesheet" href="../assets/style.css">
</head>
<body>
  <header class="topbar">
    <div>
      <p class="eyebrow">Domain Detail</p>
      <h1>{title}</h1>
    </div>
    <a class="nav-link" href="../index.html">Domain board</a>
  </header>
  <main>
    <section class="band">
      <div class="detail-grid">
        <div>
          <p class="label">Status</p>
          <p class="status status-{category}">{status}</p>
        </div>
        <div>
          <p class="label">Stage Reached</p>
          <p>{stage}</p>
        </div>
        <div>
          <p class="label">Last Commit</p>
          <p>{commit}</p>
        </div>
        <div>
          <p class="label">Next Allowed Action</p>
          <p>{recommendation}</p>
        </div>
      </div>
    </section>
    <section class="band">
      <h2>Verdict</h2>
      <p>{stop_reason}</p>
      <h3>Revisit Trigger</h3>
      <p>{trigger}</p>
    </section>
    {timeline}
    {metrics}
    {reports}
  </main>
  <footer>Generated {generated}</footer>
</body>
</html>
"#,
        title = escape(&domain.slug),
        category = escape(&domain.category),
        status = escape(&domain.status),
        stage = optional(&domain.stage_reached),
        commit = optional(&domain.last_commit),
        recommendation = escape(&domain.current_recommendation),
        stop_reason = optional(&domain.stop_reason),
        trigger = optional(&domain.revisit_trigger),
        timeline = timeline_section(domain),
        metrics = metrics_section(domain),
        reports = reports_section(domain),
        generated = escape(&state.generated_at)
    )
}

fn summary_cards(summary: &DashboardSummary) -> String {
    format!(
        r#"<section class="summary-grid">
  <div class="metric"><span>{}</span><label>Graduated Signals</label></div>
  <div class="metric"><span>{}</span><label>Live Candidates</label></div>
  <div class="metric"><span>{}</span><label>Monitors</label></div>
  <div class="metric"><span>{}</span><label>Feasibility</label></div>
  <div class="metric"><span>{}</span><label>Frozen / Failed</label></div>
  <div class="metric"><span>{}</span><label>Infrastructure</label></div>
</section>"#,
        summary.graduated_signals,
        summary.live_candidates,
        summary.monitors,
        summary.feasibility,
        summary.frozen_or_failed,
        summary.infrastructure
    )
}

fn canonical_panel() -> String {
    r#"<section class="band canonical">
  <h2>Canonical State</h2>
  <div class="state-list">
    <span>No graduated signal</span>
    <span>No live tradable candidate</span>
    <span>SEC-CORE is durable infrastructure</span>
    <span>Cyber Item 1.05 is the only true monitor</span>
    <span>Insider clusters are frozen after causal rebuild</span>
  </div>
</section>"#
        .to_string()
}

fn domain_board(state: &DashboardState) -> String {
    let mut rows = String::new();
    for domain in &state.domains {
        rows.push_str(&format!(
            r#"<tr>
  <td><a href="{detail}">{slug}</a></td>
  <td><span class="status status-{category}">{status}</span></td>
  <td>{stage}</td>
  <td>{reason}</td>
  <td>{trigger}</td>
  <td>{commit}</td>
  <td>{recommendation}</td>
</tr>"#,
            detail = escape(&domain.detail_page),
            slug = escape(&domain.slug),
            category = escape(&domain.category),
            status = escape(&domain.status),
            stage = optional(&domain.stage_reached),
            reason = optional(&domain.stop_reason),
            trigger = optional(&domain.revisit_trigger),
            commit = optional(&domain.last_commit),
            recommendation = escape(&domain.current_recommendation)
        ));
    }
    format!(
        r#"<section class="band">
  <div class="section-heading">
    <h2>Domain Board</h2>
    <span>{count} domains</span>
  </div>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Domain</th>
          <th>Status</th>
          <th>Stage Reached</th>
          <th>Stop Reason</th>
          <th>Revisit Trigger</th>
          <th>Last Commit</th>
          <th>Current Recommendation</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
</section>"#,
        count = state.domains.len(),
        rows = rows
    )
}

fn stop_reason_section(state: &DashboardState) -> String {
    let mut rows = String::new();
    for bucket in &state.stop_reasons {
        rows.push_str(&format!(
            r#"<tr><td>{}</td><td>{}</td></tr>"#,
            escape(&bucket.reason),
            bucket.count
        ));
    }
    format!(
        r#"<section class="band two-col">
  <div>
    <h2>Stop Reasons</h2>
    <table class="compact">
      <thead><tr><th>Reason</th><th>Count</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
  <div>
    <h2>Research Funnel</h2>
    <ol class="funnel">
      <li>Proposed</li>
      <li>Source corpus</li>
      <li>Parser audit</li>
      <li>Timestamp audit</li>
      <li>Model-ready</li>
      <li>First falsification</li>
      <li>Fresh confirmation</li>
      <li>Final audit</li>
      <li>Candidate paper signal</li>
    </ol>
  </div>
</section>"#,
        rows = rows
    )
}

fn domain_finder_section(state: &DashboardState) -> String {
    let mut top_rows = String::new();
    for entry in &state.domain_finder.top_candidates {
        top_rows.push_str(&format!(
            r#"<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>"#,
            escape(&entry.slug),
            entry.score,
            escape(entry.gate.label()),
            escape(&entry.recommended_next_action)
        ));
    }
    let alert_count = state
        .domain_finder
        .alerts
        .as_ref()
        .map(|alerts| alerts.alerts.len())
        .unwrap_or(0);
    format!(
        r#"<section class="band">
  <div class="section-heading">
    <h2>Domain Finder</h2>
    <span>{alert_count} alerts</span>
  </div>
  <div class="finder-grid">
    <div>
      <h3>Top Candidates</h3>
      <table class="compact">
        <thead><tr><th>Domain</th><th>Score</th><th>Gate</th><th>Next Action</th></tr></thead>
        <tbody>{top_rows}</tbody>
      </table>
    </div>
    <div class="lists">
      <h3>Registry Outcomes</h3>
      <p><strong>Monitor-only</strong>: {monitors}</p>
      <p><strong>Blocked</strong>: {blocked}</p>
      <p><strong>Feasibility-only</strong>: {feasibility}</p>
    </div>
  </div>
</section>"#,
        alert_count = alert_count,
        top_rows = top_rows,
        monitors = list_inline(&state.domain_finder.monitor_only_domains),
        blocked = list_inline(&state.domain_finder.blocked_by_registry_domains),
        feasibility = list_inline(&state.domain_finder.feasibility_only_domains)
    )
}

fn infrastructure_section(state: &DashboardState) -> String {
    let mut rows = String::new();
    for item in &state.infrastructure {
        rows.push_str(&format!(
            r#"<tr><td>{}</td><td>{}</td><td>{}</td></tr>"#,
            escape(&item.name),
            escape(&item.status),
            escape(&item.description)
        ));
    }
    format!(
        r#"<section class="band">
  <h2>Infrastructure</h2>
  <table class="compact">
    <thead><tr><th>Name</th><th>Status</th><th>Role</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</section>"#,
        rows = rows
    )
}

fn timeline_section(domain: &DashboardDomain) -> String {
    let mut items = Vec::new();
    if let Some(stage) = &domain.stage_reached {
        items.push(format!("Stage reached: {}", escape(stage)));
    }
    if domain.slug == "insider_purchase_clusters" {
        items = vec![
            "Fresh confirmation passed after duplicate/timestamp repair".to_string(),
            "Final audit found feature leakage".to_string(),
            "Causal rebuild fixed leakage".to_string(),
            "Empirical gate failed on null-shuffle and concentration".to_string(),
            "Frozen under current thesis".to_string(),
        ];
    }
    if items.is_empty() {
        return String::new();
    }
    let list = items
        .iter()
        .map(|item| format!("<li>{}</li>", item))
        .collect::<Vec<_>>()
        .join("");
    format!(
        r#"<section class="band">
  <h2>Run Timeline</h2>
  <ol class="timeline">{}</ol>
</section>"#,
        list
    )
}

fn metrics_section(domain: &DashboardDomain) -> String {
    if domain.key_metrics.is_empty() {
        return String::new();
    }
    let rows = domain
        .key_metrics
        .iter()
        .map(|(key, value)| {
            format!(
                r#"<tr><td>{}</td><td>{}</td></tr>"#,
                escape(key),
                escape(value)
            )
        })
        .collect::<Vec<_>>()
        .join("");
    format!(
        r#"<section class="band">
  <h2>Key Metrics</h2>
  <table class="compact"><tbody>{}</tbody></table>
</section>"#,
        rows
    )
}

fn reports_section(domain: &DashboardDomain) -> String {
    if domain.reports.is_empty() {
        return String::new();
    }
    let links = domain
        .reports
        .iter()
        .map(|report| {
            format!(
                r#"<li><a href="{}">{}</a></li>"#,
                escape(&report.path),
                escape(&report.label)
            )
        })
        .collect::<Vec<_>>()
        .join("");
    format!(
        r#"<section class="band">
  <h2>Reports</h2>
  <ul class="report-list">{}</ul>
</section>"#,
        links
    )
}

fn summary_from_domains(domains: &[DashboardDomain]) -> DashboardSummary {
    let mut summary = DashboardSummary {
        infrastructure: infrastructure_items().len(),
        ..DashboardSummary::default()
    };
    for domain in domains {
        match domain.category.as_str() {
            "candidate" => summary.live_candidates += 1,
            "monitor" => summary.monitors += 1,
            "feasibility" => summary.feasibility += 1,
            "frozen" => summary.frozen_or_failed += 1,
            "graduated" => summary.graduated_signals += 1,
            _ => {}
        }
    }
    summary
}

fn stop_reason_buckets(domains: &[DashboardDomain]) -> Vec<StopReasonBucket> {
    let mut counts = BTreeMap::<String, usize>::new();
    for domain in domains {
        let reason = stop_reason_bucket(domain);
        *counts.entry(reason).or_default() += 1;
    }
    counts
        .into_iter()
        .map(|(reason, count)| StopReasonBucket { reason, count })
        .collect()
}

fn stop_reason_bucket(domain: &DashboardDomain) -> String {
    let text = format!(
        "{} {} {}",
        domain.status,
        domain.stage_reached.clone().unwrap_or_default(),
        domain.stop_reason.clone().unwrap_or_default()
    )
    .to_ascii_lowercase();
    if text.contains("underpowered") || text.contains("too small") || text.contains("0 likely oos")
    {
        "underpowered".to_string()
    } else if text.contains("mapping") {
        "mapping insufficient".to_string()
    } else if text.contains("timestamp") || text.contains("session") {
        "timestamp/session".to_string()
    } else if text.contains("execution") || text.contains("next-open") || text.contains("cost") {
        "execution".to_string()
    } else if text.contains("leakage")
        || text.contains("concentration")
        || text.contains("null-shuffle")
    {
        "leakage/concentration".to_string()
    } else if text.contains("falsification") || text.contains("failed") {
        "failed falsification".to_string()
    } else if text.contains("parser") {
        "parser not trusted".to_string()
    } else {
        "other".to_string()
    }
}

fn category_for_status(status: &str) -> String {
    let normalized = status.trim().to_ascii_lowercase().replace([' ', '-'], "_");
    if normalized.contains("candidate_paper_signal") {
        "graduated".to_string()
    } else if normalized.contains("underpowered_monitor") || normalized == "monitor_later" {
        "monitor".to_string()
    } else if normalized.contains("underpowered_feasibility") {
        "feasibility".to_string()
    } else if normalized.contains("model_ready")
        || normalized.contains("promising")
        || normalized.contains("fresh_confirmed")
    {
        "candidate".to_string()
    } else {
        "frozen".to_string()
    }
}

fn category_rank(category: &str) -> u8 {
    match category {
        "candidate" => 0,
        "monitor" => 1,
        "feasibility" => 2,
        "frozen" => 3,
        "graduated" => 4,
        _ => 5,
    }
}

fn recommendation_for(category: &str, entry: &RegistryEntry) -> String {
    match category {
        "graduated" => "Paper signal only; still requires independent validation.".to_string(),
        "candidate" => "Review remaining gates before any paper-signal claim.".to_string(),
        "monitor" => entry
            .revisit_trigger
            .as_ref()
            .map(|trigger| format!("Monitor only until trigger is met: {}", trigger))
            .unwrap_or_else(|| "Monitor only; do not model yet.".to_string()),
        "feasibility" => "Source/mapping feasibility only; do not model.".to_string(),
        _ => entry
            .revisit_trigger
            .as_ref()
            .map(|trigger| format!("Suppress unless revisit condition is met: {}", trigger))
            .unwrap_or_else(|| "Suppress under current thesis.".to_string()),
    }
}

fn key_metrics(entry: &RegistryEntry) -> BTreeMap<String, String> {
    let mut metrics = BTreeMap::new();
    let text = entry.stop_reason.clone().unwrap_or_default();
    if let Some(value) = number_after(&text, "null-shuffle h10 p-value") {
        metrics.insert("null_shuffle_h10_p_value".to_string(), value);
    }
    if let Some(value) = number_after(&text, "liquid subset tickers") {
        metrics.insert("liquid_subset_tickers".to_string(), value);
    }
    if let Some(value) = number_after(&text, "top-5 liquid ticker contribution") {
        metrics.insert("top5_liquid_ticker_contribution".to_string(), value);
    }
    if let Some(value) = number_after(&text, "reviewed usable rows") {
        metrics.insert("reviewed_usable_rows".to_string(), value);
    }
    if let Some(value) = number_after(&text, "model-eligible rows") {
        metrics.insert("model_eligible_rows".to_string(), value);
    }
    if let Some(value) = number_after(&text, "likely OOS predictions") {
        metrics.insert("likely_oos_predictions".to_string(), value);
    }
    metrics
}

fn number_after(text: &str, needle: &str) -> Option<String> {
    let lower = text.to_ascii_lowercase();
    let idx = lower.find(&needle.to_ascii_lowercase())?;
    let tail = &text[idx + needle.len()..];
    let mut number = String::new();
    let mut started = false;
    for ch in tail.chars() {
        if ch.is_ascii_digit() || ch == '.' {
            number.push(ch);
            started = true;
        } else if ch == '%' && started {
            number.push(ch);
            break;
        } else if started {
            break;
        }
    }
    if number.is_empty() {
        None
    } else {
        Some(number)
    }
}

fn infrastructure_items() -> Vec<InfrastructureItem> {
    vec![
        InfrastructureItem {
            name: "SEC-CORE".to_string(),
            status: "integrated".to_string(),
            description:
                "Reusable SEC source discovery, review template, context, timestamp audit, and readiness tooling."
                    .to_string(),
        },
        InfrastructureItem {
            name: "Domain Finder".to_string(),
            status: "operational".to_string(),
            description:
                "Pre-MRE collect/probe/scan/top/explain/diff/alerts layer for registry-aware intake."
                    .to_string(),
        },
    ]
}

fn resolve_registry_path(root: &Path, explicit: Option<&Path>) -> Option<PathBuf> {
    if let Some(path) = explicit {
        let resolved = resolve_path(root, path);
        return resolved.exists().then_some(resolved);
    }
    let parent_registry = root.join("../docs/DOMAIN_RESEARCH_REGISTRY.md");
    if parent_registry.exists() {
        return Some(parent_registry);
    }
    let local_registry = root.join("docs/DOMAIN_RESEARCH_REGISTRY.md");
    local_registry.exists().then_some(local_registry)
}

fn resolve_candidates_path(root: &Path, explicit: Option<&Path>) -> Option<PathBuf> {
    if let Some(path) = explicit {
        let resolved = resolve_path(root, path);
        return resolved.exists().then_some(resolved);
    }
    let candidates = [
        root.join("artifacts/domain_finder/domain_candidates.json"),
        root.join("domain-finder/artifacts/domain_finder/domain_candidates.json"),
    ];
    candidates.into_iter().find(|path| path.exists())
}

fn load_candidate_json(path: &Path) -> anyhow::Result<Vec<DomainCandidate>> {
    let text = fs::read_to_string(path)?;
    Ok(serde_json::from_str(&text)?)
}

fn collect_report_files(root: &Path) -> anyhow::Result<Vec<PathBuf>> {
    let mut files = Vec::new();
    for base in [root.join("artifacts"), root.join("domain-finder/artifacts")] {
        if base.exists() {
            collect_reports_recursive(&base, &mut files)?;
        }
    }
    files.sort();
    Ok(files)
}

fn collect_reports_recursive(path: &Path, files: &mut Vec<PathBuf>) -> anyhow::Result<()> {
    for entry in fs::read_dir(path)? {
        let entry = entry?;
        let path = entry.path();
        if path.is_dir() {
            collect_reports_recursive(&path, files)?;
        } else if path
            .file_name()
            .and_then(|name| name.to_str())
            .is_some_and(|name| name.ends_with("_report.md") || name.ends_with("_audit.md"))
        {
            files.push(path);
        }
    }
    Ok(())
}

fn reports_for_domain(slug: &str, files: &[PathBuf], out_dir: &Path) -> Vec<ArtifactLink> {
    files
        .iter()
        .filter(|path| {
            path.file_stem()
                .and_then(|stem| stem.to_str())
                .map(normalize_slug)
                .is_some_and(|stem| stem.contains(slug))
        })
        .take(12)
        .map(|path| ArtifactLink {
            label: path
                .file_name()
                .and_then(|name| name.to_str())
                .unwrap_or("report")
                .to_string(),
            path: relative_link(out_dir, path),
        })
        .collect()
}

fn relative_link(from_dir: &Path, target: &Path) -> String {
    let from = from_dir.components().collect::<Vec<_>>();
    let to = target.components().collect::<Vec<_>>();
    let common = from
        .iter()
        .zip(to.iter())
        .take_while(|(a, b)| a == b)
        .count();
    if common == 0 {
        return target.display().to_string();
    }
    let mut parts = Vec::new();
    for _ in common..from.len() {
        parts.push("..".to_string());
    }
    for component in &to[common..] {
        parts.push(component.as_os_str().to_string_lossy().to_string());
    }
    parts.join("/")
}

fn resolve_path(root: &Path, path: &Path) -> PathBuf {
    if path.is_absolute() {
        path.to_path_buf()
    } else {
        root.join(path)
    }
}

fn absolute_or_current(path: &Path) -> anyhow::Result<PathBuf> {
    if path.exists() {
        Ok(path.canonicalize()?)
    } else if path.is_absolute() {
        Ok(path.to_path_buf())
    } else {
        Ok(std::env::current_dir()?.join(path))
    }
}

fn optional(value: &Option<String>) -> String {
    value
        .as_ref()
        .map(|v| escape(v))
        .unwrap_or_else(|| "-".to_string())
}

fn list_inline(items: &[String]) -> String {
    if items.is_empty() {
        "-".to_string()
    } else {
        items
            .iter()
            .map(|item| format!("<code>{}</code>", escape(item)))
            .collect::<Vec<_>>()
            .join(" ")
    }
}

fn escape(value: &str) -> String {
    value
        .replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
}

const STYLE_CSS: &str = r#"
:root {
  color-scheme: light;
  --bg: #f6f7f9;
  --panel: #ffffff;
  --text: #1b2533;
  --muted: #667085;
  --line: #d8dee8;
  --blue: #275f9f;
  --green: #1f7a4d;
  --amber: #9a5b00;
  --red: #a13b3b;
  --violet: #6654a7;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-size: 14px;
  line-height: 1.45;
}
a { color: var(--blue); text-decoration: none; }
a:hover { text-decoration: underline; }
.topbar {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  padding: 28px 32px 18px;
  border-bottom: 1px solid var(--line);
  background: #fff;
}
h1, h2, h3, p { margin-top: 0; }
h1 { margin-bottom: 0; font-size: 28px; letter-spacing: 0; }
h2 { margin-bottom: 12px; font-size: 18px; letter-spacing: 0; }
h3 { margin-bottom: 8px; font-size: 14px; letter-spacing: 0; }
main { padding: 24px 32px 40px; }
footer { padding: 24px 32px; color: var(--muted); }
.eyebrow, .generated, .label { color: var(--muted); font-size: 12px; margin-bottom: 4px; }
.nav-link { align-self: center; }
.summary-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(120px, 1fr));
  gap: 12px;
  margin-bottom: 18px;
}
.metric {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 14px;
  min-height: 86px;
}
.metric span { display: block; font-size: 28px; font-weight: 700; }
.metric label { display: block; color: var(--muted); margin-top: 4px; }
.band {
  background: var(--panel);
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
  margin: 0 -32px 18px;
  padding: 22px 32px;
}
.canonical { border-left: 4px solid var(--blue); }
.state-list { display: flex; flex-wrap: wrap; gap: 8px; }
.state-list span {
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 6px 8px;
  background: #f8fafc;
}
.section-heading {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 12px;
}
.section-heading span { color: var(--muted); }
.table-wrap { overflow-x: auto; }
table {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
}
th, td {
  border-bottom: 1px solid var(--line);
  padding: 9px 8px;
  text-align: left;
  vertical-align: top;
  overflow-wrap: anywhere;
}
th { color: var(--muted); font-weight: 600; font-size: 12px; }
.compact th, .compact td { padding: 7px 8px; }
.status {
  display: inline-block;
  border-radius: 6px;
  padding: 3px 7px;
  font-weight: 600;
  background: #edf1f7;
}
.status-monitor { color: var(--blue); background: #e9f2ff; }
.status-feasibility { color: var(--amber); background: #fff3d6; }
.status-frozen { color: var(--red); background: #ffe9e9; }
.status-candidate { color: var(--green); background: #e5f6ed; }
.status-graduated { color: var(--violet); background: #efecff; }
.two-col, .finder-grid, .detail-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 24px;
}
.detail-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.lists p { margin-bottom: 10px; }
code {
  background: #eef2f6;
  border-radius: 4px;
  padding: 2px 4px;
  font-family: ui-monospace, "SFMono-Regular", Consolas, monospace;
  font-size: 12px;
}
.funnel, .timeline { margin: 0; padding-left: 18px; }
.funnel li, .timeline li { margin-bottom: 6px; }
.report-list { margin-bottom: 0; padding-left: 18px; }
@media (max-width: 1000px) {
  .summary-grid { grid-template-columns: repeat(3, minmax(120px, 1fr)); }
  .two-col, .finder-grid, .detail-grid { grid-template-columns: 1fr; }
}
@media (max-width: 640px) {
  .topbar { display: block; padding: 22px 18px 16px; }
  main { padding: 18px; }
  .band { margin-left: -18px; margin-right: -18px; padding: 18px; }
  .summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  table { min-width: 760px; }
}
"#;
