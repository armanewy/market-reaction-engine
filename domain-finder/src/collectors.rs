use crate::io::{ensure_dir, write_string};
use crate::model::{DomainObservation, TimestampQuality};
use anyhow::Context;
use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};

pub const DEFAULT_GENERATED_DIR: &str = "data/observations/generated";

#[derive(Debug, Clone)]
pub struct CollectorOutput {
    pub files: Vec<CollectorFile>,
    pub observations: Vec<DomainObservation>,
}

#[derive(Debug, Clone)]
pub struct CollectorFile {
    pub family: String,
    pub path: PathBuf,
    pub observation_count: usize,
}

pub fn available_families() -> Vec<&'static str> {
    vec!["agency", "fda", "index", "litigation", "sec"]
}

pub fn built_in_observations(family: Option<&str>) -> anyhow::Result<Vec<DomainObservation>> {
    let selected = family.map(normalize_family);
    validate_family(selected.as_deref())?;

    let observations = seed_observations()
        .into_iter()
        .filter(|(candidate_family, _)| {
            selected
                .as_deref()
                .map(|wanted| wanted == "all" || wanted == *candidate_family)
                .unwrap_or(true)
        })
        .map(|(_, obs)| obs)
        .collect();
    Ok(observations)
}

pub fn collect_to_generated_dir(
    root: &Path,
    output_dir: Option<&Path>,
    family: Option<&str>,
) -> anyhow::Result<CollectorOutput> {
    let output_dir = output_dir
        .map(|p| {
            if p.is_absolute() {
                p.to_path_buf()
            } else {
                root.join(p)
            }
        })
        .unwrap_or_else(|| root.join(DEFAULT_GENERATED_DIR));
    ensure_dir(&output_dir)?;

    let selected = family.map(normalize_family);
    validate_family(selected.as_deref())?;
    let mut grouped: BTreeMap<String, Vec<DomainObservation>> = BTreeMap::new();
    for (candidate_family, obs) in seed_observations() {
        if selected
            .as_deref()
            .map(|wanted| wanted == "all" || wanted == candidate_family)
            .unwrap_or(true)
        {
            grouped
                .entry(candidate_family.to_string())
                .or_default()
                .push(obs);
        }
    }

    if grouped.is_empty() {
        let requested = selected.unwrap_or_else(|| "all".to_string());
        anyhow::bail!(
            "collector family `{}` produced no observations; expected one of: all, {}",
            requested,
            available_families().join(", ")
        );
    }

    let mut files = Vec::new();
    let mut observations = Vec::new();
    for (family, family_observations) in grouped {
        let path = output_dir.join(format!("{}_observations.jsonl", family));
        let mut text = String::new();
        for obs in &family_observations {
            text.push_str(&serde_json::to_string(obs)?);
            text.push('\n');
        }
        write_string(&path, &text)
            .with_context(|| format!("failed to write collector output {}", path.display()))?;
        observations.extend(family_observations.iter().cloned());
        files.push(CollectorFile {
            family,
            path,
            observation_count: family_observations.len(),
        });
    }

    Ok(CollectorOutput {
        files,
        observations,
    })
}

pub fn source_family_count(observations: &[DomainObservation]) -> usize {
    observations
        .iter()
        .filter_map(|obs| {
            obs.tags
                .iter()
                .find_map(|tag| tag.strip_prefix("collector:"))
                .map(str::to_string)
        })
        .collect::<BTreeSet<_>>()
        .len()
}

fn normalize_family(family: &str) -> String {
    family.trim().to_ascii_lowercase().replace([' ', '-'], "_")
}

fn validate_family(family: Option<&str>) -> anyhow::Result<()> {
    if let Some(family) = family {
        anyhow::ensure!(
            family == "all" || available_families().contains(&family),
            "unknown collector family `{}`; expected one of: all, {}",
            family,
            available_families().join(", ")
        );
    }
    Ok(())
}

fn seed_observations() -> Vec<(&'static str, DomainObservation)> {
    let mut out = Vec::new();
    out.extend(sec_observations());
    out.extend(agency_observations());
    out.extend(fda_observations());
    out.extend(litigation_observations());
    out.extend(index_observations());
    out
}

fn sec_observations() -> Vec<(&'static str, DomainObservation)> {
    vec![
        obs(
            "sec",
            "cybersecurity_material_incidents_8k",
            "SEC Item 1.05 Material Cybersecurity Incidents",
            "SEC EDGAR",
            "sec_official",
            "https://www.sec.gov/edgar/search/",
            true,
            TimestampQuality::Clear,
            &[
                "scope and financial impact often evolve through amendments",
                "investors may need to separate operational disruption from generic breach disclosure",
            ],
            &[
                "generic cyber risk language",
                "no-material-impact amendment",
                "vendor vulnerability not tied to issuer",
                "duplicate press release and 8-K",
            ],
            &[
                "operational_disruption_flag",
                "customer_data_exposure_flag",
                "financial_impact_language",
                "market_cap_before_event",
            ],
            "SEC issuer CIK to ticker mapping is clean",
            43,
            "mixed public issuers; price and ADV filters required",
            &["existing MRE monitor domain; Item 1.05 sample is still too small"],
            &["sec", "cyber", "monitor"],
        ),
        obs(
            "sec",
            "executive_departure_for_cause_8k",
            "8-K Executive Departure for Cause / Investigation Context",
            "SEC EDGAR",
            "sec_official",
            "https://www.sec.gov/edgar/search/",
            true,
            TimestampQuality::Clear,
            &[
                "for-cause language and investigation context may require filing text review",
                "leadership risk can be digested over several sessions",
            ],
            &[
                "routine retirement",
                "planned succession",
                "director resignation without disagreement",
                "duplicate 8-K amendment",
            ],
            &[
                "for_cause_flag",
                "investigation_flag",
                "role_ceo_cfo_flag",
                "market_cap_before_event",
            ],
            "SEC CIK mapping is clean; role extraction needs parser audit",
            120,
            "public issuers; liquidity filters still required",
            &["8-K Item 5.02 provides official timestamps and primary text"],
            &["sec", "8k", "management"],
        ),
        obs(
            "sec",
            "material_customer_contract_loss_8k",
            "Material Customer / Contract Loss 8-K",
            "SEC EDGAR",
            "sec_official",
            "https://www.sec.gov/edgar/search/",
            true,
            TimestampQuality::Clear,
            &[
                "revenue exposure may need calculation from customer concentration and contract terms",
                "impact can be clarified through follow-up filings",
            ],
            &[
                "routine contract expiration",
                "immaterial customer notice",
                "contract renewal with changed terms",
                "already-announced customer loss",
            ],
            &[
                "customer_revenue_pct",
                "contract_value_pct_market_cap",
                "termination_flag",
                "market_cap_before_event",
            ],
            "SEC issuer mapping is clean; customer mapping may require manual review",
            90,
            "issuer liquidity likely mixed; require ADV buckets",
            &["8-K Item 1.01/1.02/8.01 text can expose material commercial changes"],
            &["sec", "contracts"],
        ),
        obs(
            "sec",
            "regulatory_investigation_8k",
            "SEC 8-K Regulatory Investigation Disclosure",
            "SEC EDGAR",
            "sec_official",
            "https://www.sec.gov/edgar/search/",
            true,
            TimestampQuality::Clear,
            &[
                "investigation scope, regulator identity, and potential penalties are often uncertain",
                "market may digest severity through later updates",
            ],
            &[
                "routine risk-factor boilerplate",
                "resolved investigation",
                "subpoena disclosed after settlement",
                "duplicate press release",
            ],
            &[
                "regulator_type",
                "investigation_scope",
                "penalty_language",
                "market_cap_before_event",
            ],
            "SEC issuer mapping is clean; investigation taxonomy needs parser audit",
            110,
            "public issuer liquidity filters required",
            &["Official company-filed 8-K text anchors timestamp and disclosure content"],
            &["sec", "regulatory"],
        ),
        obs(
            "sec",
            "auditor_disagreement_severe_only",
            "Severe Auditor Disagreement / Resignation Slice",
            "SEC EDGAR",
            "sec_official",
            "https://www.sec.gov/edgar/search/",
            true,
            TimestampQuality::Clear,
            &[
                "severe disagreement language is text-heavy and may not be fully digested at first print",
                "Exhibit 16 letters can clarify severity",
            ],
            &[
                "routine auditor change",
                "no-disagreement dismissal",
                "merger-related auditor change",
                "already-disclosed restatement",
            ],
            &[
                "auditor_disagreement_flag",
                "reportable_event_flag",
                "exhibit_16_disagreement_flag",
                "market_cap_before_event",
            ],
            "SEC issuer mapping is clean; severe-only slice must be distinct from failed broad accounting thesis",
            60,
            "small issuer skew likely; strict liquidity gates needed",
            &["Prior MRE accounting run failed broad thesis; this is a possible new severe-only intake"],
            &["sec", "accounting", "new-thesis-required"],
        ),
        obs(
            "sec",
            "insider_purchase_clusters",
            "Form 4 Insider Purchase Clusters",
            "SEC EDGAR",
            "sec_official",
            "https://www.sec.gov/edgar/search/",
            true,
            TimestampQuality::Clear,
            &[
                "Form 4 purchases can be digested through role, size, and clustering context",
                "market may react over several sessions after public filing acceptance",
            ],
            &[
                "option exercise",
                "tax withholding",
                "10b5-1 planned trade",
                "derivative transaction",
            ],
            &[
                "transaction_value_pct_market_cap",
                "causal_cluster_count_10d",
                "officer_director_flag",
                "market_cap_before_event",
            ],
            "SEC Form 4 issuer mapping is clean, but current MRE thesis is frozen after causal rebuild",
            200,
            "liquid subset was overconcentrated in prior MRE audit",
            &["This source-backed idea should be blocked by the MRE registry unless a new thesis is proposed"],
            &["sec", "form4", "registry-blocked"],
        ),
        obs(
            "sec",
            "capital_raise_dilution",
            "Capital Raise Dilution Events",
            "SEC EDGAR",
            "sec_official",
            "https://www.sec.gov/edgar/search/",
            true,
            TimestampQuality::Clear,
            &[
                "financing impact depends on size, discount, warrants, and issuer context",
                "market may need to digest final terms after filing",
            ],
            &[
                "shelf registration only",
                "ATM availability without draw",
                "already-announced financing",
                "non-dilutive debt",
            ],
            &[
                "raise_amount_pct_market_cap",
                "warrant_coverage",
                "discount_to_last_close",
                "shares_outstanding_before_event",
            ],
            "SEC issuer mapping is clean, but current MRE thesis is frozen after timestamp/session repair",
            200,
            "liquidity varies; current thesis failed corrected falsification",
            &["This source-backed idea should be blocked by the MRE registry unless a new thesis is proposed"],
            &["sec", "capital-raise", "registry-blocked"],
        ),
    ]
}

fn agency_observations() -> Vec<(&'static str, DomainObservation)> {
    vec![
        obs(
            "agency",
            "bank_regulatory_enforcement",
            "Public Bank Regulatory Enforcement / Consent Orders",
            "OCC / FDIC / Federal Reserve",
            "official_agency",
            "https://www.federalreserve.gov/supervisionreg/enforcementactions.htm",
            true,
            TimestampQuality::Clear,
            &[
                "orders can restrict growth, capital, compliance, and operations over time",
                "severity and repeat-offender status require document review",
            ],
            &[
                "termination of prior order",
                "minor procedural update",
                "private bank",
                "already-known consent order",
            ],
            &[
                "civil_money_penalty_pct_market_cap",
                "asset_size",
                "capital_restriction_flag",
                "bsa_aml_flag",
            ],
            "public bank parent mapping feasible but prior MRE run was underpowered",
            28,
            "public banks often tradable; small banks may be illiquid",
            &[
                "Prior MRE result was underpowered-feasibility, not a signal failure",
                "Source expansion needs OCC/FDIC/state coverage",
            ],
            &["agency", "bank", "feasibility"],
        ),
        obs(
            "agency",
            "faa_airworthiness_directives_groundings",
            "FAA Airworthiness Directives / Groundings",
            "FAA Dynamic Regulatory System",
            "official_agency",
            "https://drs.faa.gov/",
            true,
            TimestampQuality::Clear,
            &[
                "fleet remediation, operator impact, and supplier exposure may unfold over days",
                "grounding and inspection requirements require severity review",
            ],
            &[
                "routine airworthiness directive",
                "small supplier-only issue",
                "already-announced service bulletin",
                "non-public manufacturer",
            ],
            &[
                "fleet_units_affected",
                "grounding_flag",
                "affected_model_revenue_exposure",
                "market_cap_before_event",
            ],
            "public-company OEM and supplier mapping required",
            150,
            "large OEMs liquid; supplier exposure may be fragmented",
            &["FAA AD database is an official source for directives and effective dates"],
            &["agency", "faa", "aviation"],
        ),
        obs(
            "agency",
            "epa_enforcement_consent_decrees_public_companies",
            "EPA Enforcement / Consent Decrees for Public Companies",
            "EPA Enforcement and Compliance History Online",
            "official_agency",
            "https://echo.epa.gov/",
            true,
            TimestampQuality::PublicButSessionAmbiguous,
            &[
                "remediation cost, consent decree terms, and facility impact can take time to assess",
                "environmental liabilities may be under-covered outside mega-cap issuers",
            ],
            &[
                "minor local notice",
                "private facility owner",
                "duplicate DOJ/EPA announcement",
                "already-reserved liability",
            ],
            &[
                "penalty_pct_market_cap",
                "remediation_cost_language",
                "facility_revenue_exposure",
                "repeat_offender_flag",
            ],
            "facility owner to public parent mapping is the main blocker",
            130,
            "liquidity depends on public parent; require mapped issuer filters",
            &["EPA ECHO and enforcement releases provide official source records"],
            &["agency", "epa", "enforcement"],
        ),
        obs(
            "agency",
            "osha_severe_violations_public_companies",
            "OSHA Severe Violations / Penalty Actions for Public Companies",
            "OSHA Establishment Search",
            "official_agency",
            "https://www.osha.gov/ords/imis/establishment.html",
            true,
            TimestampQuality::RecordOnly,
            &[
                "large penalties and repeat severe violations may imply operational control issues",
                "company-level impact depends on facility and recurrence context",
            ],
            &[
                "minor citation",
                "private employer",
                "subsidiary with immaterial exposure",
                "settled historical record only",
            ],
            &[
                "penalty_pct_market_cap",
                "repeat_violation_flag",
                "fatality_injury_flag",
                "facility_importance",
            ],
            "employer-to-public-parent mapping likely difficult",
            200,
            "large public parents liquid; source often maps to facilities",
            &["OSHA records are official but public-awareness timing needs feasibility review"],
            &["agency", "osha", "mapping-risk"],
        ),
        obs(
            "agency",
            "ferc_utility_enforcement_actions",
            "FERC Utility Enforcement Actions",
            "Federal Energy Regulatory Commission",
            "official_agency",
            "https://www.ferc.gov/enforcement-legal/enforcement",
            true,
            TimestampQuality::Clear,
            &[
                "utility regulatory consequences can unfold through compliance plans and penalties",
                "market impact depends on rate base, region, and penalty materiality",
            ],
            &[
                "routine compliance filing",
                "non-public utility",
                "immaterial settlement",
                "duplicate press release",
            ],
            &[
                "penalty_pct_market_cap",
                "compliance_restriction_flag",
                "utility_segment_exposure",
                "repeat_offender_flag",
            ],
            "utility parent mapping feasible but needs manual validation",
            80,
            "public utilities are generally liquid; smaller issuers need filters",
            &["FERC enforcement releases are official source-backed observations"],
            &["agency", "ferc", "utilities"],
        ),
    ]
}

fn fda_observations() -> Vec<(&'static str, DomainObservation)> {
    vec![
        obs(
            "fda",
            "fda_import_alerts_public_companies",
            "FDA Import Alerts for Public Companies",
            "FDA Import Alert Database",
            "official_agency",
            "https://www.accessdata.fda.gov/cms_ia/",
            true,
            TimestampQuality::Clear,
            &[
                "import restrictions can affect supply, remediation, and revenue over time",
                "materiality depends on product and facility exposure",
            ],
            &[
                "private company",
                "minor product line",
                "already-resolved alert",
                "foreign supplier not tied to issuer",
            ],
            &[
                "import_alert_flag",
                "affected_product_revenue_exposure",
                "facility_importance",
                "market_cap_before_event",
            ],
            "public-company, subsidiary, facility, and product mapping required",
            70,
            "depends on mapped public issuer liquidity",
            &["FDA import alert database is an official source"],
            &["fda", "import-alert", "mapping-risk"],
        ),
        obs(
            "fda",
            "fda_warning_letters_public_companies",
            "FDA Warning Letters and Manufacturing Enforcement",
            "FDA Warning Letters",
            "official_agency",
            "https://www.fda.gov/inspections-compliance-enforcement-and-criminal-investigations/compliance-actions-and-activities/warning-letters",
            true,
            TimestampQuality::Clear,
            &[
                "manufacturing and quality-system consequences may unfold through remediation",
                "investors need product and facility materiality context",
            ],
            &[
                "private company",
                "minor labeling issue",
                "already-resolved warning",
                "non-material product line",
            ],
            &[
                "affected_product_revenue_exposure",
                "repeat_warning_flag",
                "facility_importance",
                "market_cap_before_event",
            ],
            "mapping was insufficient in prior MRE run; start with known public-company universe",
            25,
            "depends on public-company filter",
            &["Prior MRE feasibility found official FDA rows but sparse SEC ticker mapping"],
            &["fda", "warning-letter", "mapping-risk"],
        ),
        obs(
            "fda",
            "fda_device_quality_enforcement_public_companies",
            "FDA Device Quality System Enforcement for Public Companies",
            "FDA Warning Letters",
            "official_agency",
            "https://www.fda.gov/medical-devices",
            true,
            TimestampQuality::Clear,
            &[
                "device quality findings can affect production, approvals, and customer confidence",
                "impact depends on product-line exposure and remediation scope",
            ],
            &[
                "non-device warning",
                "private manufacturer",
                "minor documentation issue",
                "already-remediated facility",
            ],
            &[
                "device_quality_system_flag",
                "affected_device_revenue_exposure",
                "repeat_warning_flag",
                "market_cap_before_event",
            ],
            "device manufacturer to SEC issuer mapping required",
            55,
            "medtech liquidity varies; require ADV filters",
            &["FDA medical-device warning letters and recalls provide official context"],
            &["fda", "device", "quality"],
        ),
        obs(
            "fda",
            "fda_consent_decrees_manufacturing",
            "FDA Manufacturing Consent Decrees",
            "FDA Compliance Actions",
            "official_agency",
            "https://www.fda.gov/inspections-compliance-enforcement-and-criminal-investigations/compliance-actions-and-activities",
            true,
            TimestampQuality::Clear,
            &[
                "consent decree terms can restrict production and require costly remediation",
                "financial impact may be interpreted across multiple disclosures",
            ],
            &[
                "private company",
                "non-manufacturing action",
                "minor warning without decree",
                "already-announced settlement",
            ],
            &[
                "consent_decree_flag",
                "remediation_cost_language",
                "affected_product_revenue_exposure",
                "market_cap_before_event",
            ],
            "public issuer and product exposure mapping required",
            40,
            "likely sparse; large mapped issuers can be liquid",
            &["FDA compliance action pages and DOJ releases are source-backed but sparse"],
            &["fda", "consent-decree"],
        ),
    ]
}

fn litigation_observations() -> Vec<(&'static str, DomainObservation)> {
    vec![
        obs(
            "litigation",
            "itc_exclusion_orders_public_companies",
            "ITC Exclusion Orders for Public Companies",
            "U.S. International Trade Commission",
            "official_agency",
            "https://www.usitc.gov/intellectual_property/337.htm",
            true,
            TimestampQuality::Clear,
            &[
                "exclusion remedies can affect product availability and negotiations over days",
                "market must interpret remedy scope, appeal status, and product exposure",
            ],
            &[
                "routine procedural notice",
                "non-final claim construction",
                "private party only",
                "immaterial product",
            ],
            &[
                "exclusion_order_flag",
                "affected_product_revenue_exposure",
                "remedy_scope",
                "market_cap_before_event",
            ],
            "prior Federal Register-only mapping was insufficient; USITC participant parsing needed",
            45,
            "mapped public companies may be liquid; sample likely concentrated",
            &["Prior MRE patent/ITC feasibility found mapping insufficient from Federal Register alone"],
            &["litigation", "itc", "mapping-risk"],
        ),
        obs(
            "litigation",
            "patent_injunction_public_companies",
            "Patent Injunctions Affecting Public Companies",
            "Federal court dockets / company disclosures",
            "court_official",
            "https://www.uscourts.gov/",
            true,
            TimestampQuality::PublicButSessionAmbiguous,
            &[
                "injunction scope and stay/appeal status require interpretation",
                "revenue exposure and remedy timing may be digested slowly",
            ],
            &[
                "temporary procedural order",
                "non-final ruling",
                "private counterparty",
                "immaterial patent",
            ],
            &[
                "injunction_flag",
                "stay_status",
                "affected_product_revenue_exposure",
                "market_cap_before_event",
            ],
            "ticker-linked company disclosures likely needed for high-confidence mapping",
            60,
            "liquidity depends on mapped public companies",
            &["Official court records are source-backed but access/mapping feasibility is the blocker"],
            &["litigation", "patent", "mapping-risk"],
        ),
        obs(
            "litigation",
            "large_jury_verdict_public_companies",
            "Large Jury Verdicts Against Public Companies",
            "Court records / company disclosures",
            "court_official",
            "https://www.uscourts.gov/",
            true,
            TimestampQuality::PublicButSessionAmbiguous,
            &[
                "damages, appeal prospects, insurance coverage, and reserve adequacy require interpretation",
                "financial impact may be digested through follow-up filings",
            ],
            &[
                "small verdict",
                "private defendant",
                "already-reserved liability",
                "settlement without material terms",
            ],
            &[
                "damages_pct_market_cap",
                "punitive_damage_flag",
                "appeal_status",
                "reserve_language",
            ],
            "public-company mapping and verified timestamp are hard blockers",
            80,
            "large public defendants liquid; sample may be sparse",
            &["Court records and issuer 8-K/10-Q disclosures can source material verdict observations"],
            &["litigation", "verdict", "mapping-risk"],
        ),
        obs(
            "litigation",
            "antitrust_consent_decrees_public_companies",
            "Antitrust Consent Decrees / Competition Remedies",
            "DOJ Antitrust Division / FTC",
            "official_agency",
            "https://www.justice.gov/atr",
            true,
            TimestampQuality::Clear,
            &[
                "behavioral remedies and business restrictions can take time to evaluate",
                "competitive implications may unfold through implementation details",
            ],
            &[
                "routine merger clearance",
                "private company",
                "immaterial procedural update",
                "already-announced settlement",
            ],
            &[
                "remedy_scope",
                "business_restriction_flag",
                "affected_segment_revenue_exposure",
                "market_cap_before_event",
            ],
            "public-company mapping usually feasible when party names are explicit",
            70,
            "larger antitrust targets usually liquid; sample may be low frequency",
            &["DOJ/FTC releases are official sources with clear publication dates"],
            &["litigation", "antitrust", "agency"],
        ),
    ]
}

fn index_observations() -> Vec<(&'static str, DomainObservation)> {
    vec![
        obs(
            "index",
            "index_additions_deletions",
            "Index Additions / Deletions and Passive Flow Events",
            "Index provider announcements",
            "public_index_announcement",
            "https://www.spglobal.com/spdji/en/resources/index-news-and-announcements/",
            false,
            TimestampQuality::PublicButSessionAmbiguous,
            &[
                "implementation date and passive flow may unfold after announcement",
                "demand impact depends on float and index ownership",
            ],
            &[
                "preliminary list",
                "already-known change",
                "tiny float names",
                "duplicate rebalancing notice",
            ],
            &[
                "expected_passive_demand_pct_float",
                "index_weight_change",
                "market_cap_before_event",
            ],
            "ticker mapping usually clean if announcements are structured",
            150,
            "varies by index; liquidity filters required",
            &["Primary index-provider announcements are source-backed but may require licensed feeds"],
            &["index", "passive-flow", "crowded"],
        ),
        obs(
            "index",
            "sp500_addition_deletion_effective_date",
            "S&P 500 Addition / Deletion Effective-Date Effects",
            "S&P Dow Jones Indices",
            "public_index_announcement",
            "https://www.spglobal.com/spdji/en/resources/index-news-and-announcements/",
            false,
            TimestampQuality::PublicButSessionAmbiguous,
            &[
                "trade pressure can occur between announcement and effective date",
                "impact depends on expected passive demand and liquidity",
            ],
            &[
                "rumored addition",
                "already-effective change",
                "spin-off mechanical adjustment",
                "duplicate notice",
            ],
            &[
                "expected_passive_demand_pct_float",
                "days_to_effective",
                "index_weight_change",
                "adv_before_event",
            ],
            "ticker mapping clean; source licensing and crowdedness are key risks",
            80,
            "generally liquid but heavily arbitraged",
            &["S&P DJI announcements are primary source records for index changes"],
            &["index", "sp500", "crowded"],
        ),
        obs(
            "index",
            "russell_reconstitution_extreme_flows",
            "Russell Reconstitution Extreme Passive Flow Candidates",
            "FTSE Russell announcements",
            "public_index_announcement",
            "https://www.lseg.com/en/ftse-russell/resources/russell-reconstitution",
            false,
            TimestampQuality::PublicButSessionAmbiguous,
            &[
                "rebalance implementation and passive flow can unfold predictably",
                "impact depends on float, index weight, and liquidity imbalance",
            ],
            &[
                "ordinary small flow",
                "preliminary list only",
                "illiquid microcap without execution capacity",
                "already-arbitraged change",
            ],
            &[
                "expected_passive_demand_pct_float",
                "float_adjusted_market_cap",
                "adv_before_event",
                "days_to_reconstitution",
            ],
            "ticker mapping clean; licensed constituent data may be needed",
            200,
            "capacity depends heavily on ADV and crowding",
            &["FTSE Russell reconstitution materials are primary source observations"],
            &["index", "russell", "passive-flow"],
        ),
        obs(
            "index",
            "msci_rebalance_emerging_market_deletions",
            "MSCI Rebalance / Emerging Market Deletions",
            "MSCI index announcements",
            "public_index_announcement",
            "https://www.msci.com/index-announcements",
            false,
            TimestampQuality::PublicButSessionAmbiguous,
            &[
                "foreign ownership, index weights, and implementation timing can create delayed pressure",
                "market digestion depends on accessibility and passive ownership",
            ],
            &[
                "ordinary weight change",
                "low-accessibility market",
                "licensed-only source without timestamp",
                "duplicate broker summary",
            ],
            &[
                "expected_passive_demand_pct_float",
                "country_weight_change",
                "foreign_ownership_limit_flag",
                "adv_before_event",
            ],
            "ticker/ADR mapping and licensed data access are likely blockers",
            120,
            "liquidity varies by ADR/local listing; execution feasibility must be scored hard",
            &["MSCI announcements are primary source observations but data access may be constrained"],
            &["index", "msci", "mapping-risk"],
        ),
    ]
}

#[allow(clippy::too_many_arguments)]
fn obs(
    family: &'static str,
    slug: &str,
    title: &str,
    source_name: &str,
    source_kind: &str,
    source_url: &str,
    official_source: bool,
    timestamp_quality: TimestampQuality,
    delayed_digest_reasons: &[&str],
    hard_negatives: &[&str],
    materiality_fields: &[&str],
    mapping_notes: &str,
    sample_size_hint: u32,
    liquidity_notes: &str,
    evidence: &[&str],
    tags: &[&str],
) -> (&'static str, DomainObservation) {
    let mut tags = tags.iter().map(|s| s.to_string()).collect::<Vec<_>>();
    tags.push(format!("collector:{}", family));
    (
        family,
        DomainObservation {
            slug: slug.to_string(),
            title: title.to_string(),
            source_name: source_name.to_string(),
            source_kind: source_kind.to_string(),
            source_url: Some(source_url.to_string()),
            official_source,
            timestamp_quality,
            delayed_digest_reasons: delayed_digest_reasons
                .iter()
                .map(|s| s.to_string())
                .collect(),
            hard_negatives: hard_negatives.iter().map(|s| s.to_string()).collect(),
            materiality_fields: materiality_fields.iter().map(|s| s.to_string()).collect(),
            mapping_notes: Some(mapping_notes.to_string()),
            sample_size_hint: Some(sample_size_hint),
            liquidity_notes: Some(liquidity_notes.to_string()),
            evidence: evidence.iter().map(|s| s.to_string()).collect(),
            tags,
            observed_at: None,
            proposed_by: Some("domain-finder built-in collector".to_string()),
        },
    )
}
