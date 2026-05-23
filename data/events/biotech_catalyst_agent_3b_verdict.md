# Agent 3B Biotech Catalyst Verdict

Verdict: parser not trusted.

This was a real corpus feasibility pass, not a model or event study. SEC 8-K / Exhibit 99 source recovery found 2,247 source documents across 51 biotech/pharma tickers. The parser emitted 931 candidate event rows. Rule review of the best source exhibit/headline per event retained 112 usable catalyst rows and rejected 819 rows, mostly background mentions, stale approvals, soft updates, conference/publication notices, enrollment updates, and risk-factor language.

Readiness counts are strong enough to continue the domain: 112 reviewed usable rows, 98 binary catalysts, 50 FDA/regulatory decision rows, 23 Phase 2/3 or pivotal readout rows, 44 negative catalysts, 48 positive catalysts, 112 rows with market-cap context, 112 rows with 20-day XBI-adjusted run-up context, clear timestamps, and 72 likely OOS rows at min_train=40. ClinicalTrials.gov metadata was fetched for 85 NCT IDs as a support sidecar.

The blocker is parser label quality. The 60-row rule-reviewed gold audit produced 55/60 correct rows overall, but event_type precision was only 88.6% versus the 95% gate. The parser also failed the negative-control gates by mistaking at least one enrollment/update row and one publication/conference notice for a readout. Drug/asset, trial phase, endpoint, statistical, and regulatory-decision fact checks passed on this gold set, but event classification is not trustworthy enough for modeling.

Decision: continue corpus buildout only after parser hardening. Priority fixes are to require catalyst language in the headline/lead paragraph, distinguish current action from background product descriptions, reject investor-deck pipeline tables as event labels, and enforce hard negative controls for enrollment, conference, and publication-only notices. Do not model this domain yet.
