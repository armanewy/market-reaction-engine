# Agent 3C Biotech Catalyst Verdict

Verdict: model-ready.

This was a parser-hardening milestone, not a model, event study, or backtest. No new source volume was added. The parser was rerun against the existing Agent 3B source-document manifest and hardened around soft-update false positives.

Agent 3C added a false-positive taxonomy and section-aware catalyst gating. The parser now rejects enrollment-only updates, first-patient dosing, trial initiation, trial design/protocol updates, publication or conference notices, expected future readouts, previously announced results, investor-deck/pipeline-table rows without new result facts, and about-company/risk-factor boilerplate. It still permits body or pipeline-table evidence when the text contains explicit new-result or regulatory-decision language.

The refreshed parser emitted 1,196 event rows from 2,247 source documents. After preserving Agent 3B review/context fields and demoting 15 previously reviewed rows that now parse as unknown, the reviewed usable corpus has 97 events, 68 binary catalysts, 40 FDA/regulatory decision rows, 25 Phase 2/3 or pivotal readout rows, 34 negative catalysts, and 39 positive catalysts. Market-cap context, 20-day XBI-adjusted run-up context, clear timestamps, source evidence, and sector benchmark coverage are present for all 97 reviewed usable rows.

The parser audit was expanded to 82 reviewed rows so the hard-negative controls could be tested alongside event-type, drug/indication, trial-phase, endpoint, and regulatory-decision facts. Audit result: 82/82 correct, event_type_precision 100.0%, drug_asset_indication_precision 100.0%, trial_phase_precision 100.0%, endpoint_success_failure_precision 100.0%, regulatory_decision_precision 100.0%. No designation-only event was mistaken for approval, and no enrollment/update, publication/conference notice, trial initiation/design row, previously announced result, or investor-deck/pipeline-table row was mistaken for a new catalyst.

Readiness decision: model-ready under the hard gates. The corpus is below the 100-row preferred target but above the 80-row minimum, with parser audit passing, binary/positive/negative counts above gate, market context present, event timestamps clear, and 57 likely OOS predictions at min_train=40.

Do not treat this verdict as an empirical result. It only clears the data-product and parser-trust gate for a future preregistered biotech event-study/modeling milestone.
