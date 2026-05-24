# Domain Research Registry

This registry records domain status, stop reasons, and revisit triggers for the
Market Reaction Engine research program. It is meant to prevent repeated work on
known-failing patterns and to preserve the reasons a domain did or did not
advance.

## Current State

```text
No graduated tradable signal.
No current live tradable candidate.
SEC-CORE is the durable infrastructure win.
Cybersecurity Item 1.05 is an underpowered monitor, not failed.
Everything else tested is frozen or failed under its current thesis.
```

## Durable Infrastructure

SEC-CORE is integrated into `main` and provides reusable SEC-native tooling:

```text
sec-domain-source-docs
sec-domain-review-template
sec-domain-context
sec-domain-timestamp-audit
sec-domain-readiness-report
```

Future SEC-native domains should use these commands before adding new
domain-specific source, context, timestamp, or readiness plumbing.

## Domain Board

| Domain | Status | Stage Reached | Stop Reason | Last Known Commit | Revisit Trigger |
| --- | --- | --- | --- | --- | --- |
| `cybersecurity_material_incidents_8k` | underpowered_monitor | monitor/readiness | Item 1.05 sample too small; 43 reviewed usable rows, 37 model-eligible rows, 0 likely OOS predictions | `878db5f` monitor update | Rerun when 80+ reviewed usable rows, 60+ approved material incidents, and 30+ likely OOS predictions are available. |
| `insider_purchase_clusters` | frozen | causal-feature rebuild/final audit | Failed empirical gate after leakage repair: feature leakage false after rebuild, null-shuffle h10 p-value 0.7143, liquid subset tickers 14, top-5 liquid ticker contribution 86.7397% | `b0923ce` causal rebuild | Only revisit as a new pre-registered thesis, such as CEO/CFO-only, high-liquidity-only, longer-horizon post-drawdown purchases, or a different cluster definition. |
| `capital_raise_dilution` | frozen | timestamp-repaired falsification | Timestamp/session repair invalidated the initial result; corrected clean-slice falsification failed | historical domain artifacts | Only revisit with a new pre-registered slice, not by reviving the old timestamp-suspect result. |
| `biotech_negative_catalysts` | explanatory only | fresh confirmation/execution audit | Close-to-close explanatory effect survived, but realistic next-open execution failed | historical domain artifacts | Revisit only with intraday execution, earlier public-awareness sources, or a pre-event catalyst-calendar strategy. |
| `government_contract_awards` | frozen | falsification/narrow-slice audit | Broad falsification failed; narrow material slice too small | historical domain artifacts | Revisit only with stronger public-announcement linking and a larger audited materiality slice. |
| `semiconductors` | frozen | readiness/corpus review | Promising but underpowered | historical domain artifacts | Revisit only if a materially larger reviewed event bridge is available. |
| `accounting_integrity_8k` | frozen | real corpus/falsification | Real corpus built, but broad thesis failed next-open cost stress | `fc6d7b7` | Only revisit with a narrow severe-event thesis, such as Item 4.02 plus auditor resignation/disagreement. |
| `activist_13d_control_intent` | frozen | real corpus/falsification | Broad active/control thesis failed h3/h10 OOS versus hard negatives | `29164f0` | Only revisit with a narrow known-activist, board-seat, sale-pressure, initial-13D slice. |
| `sec_distress_events` | frozen | real corpus/falsification | Execution unrealistic due illiquidity, distress mechanics, and cost stress | `01e99bc` | Revisit only with a liquid-only, non-halted slice and explicit execution controls. |
| `nhtsa_auto_safety_investigations` | frozen | real corpus/falsification | Severe investigation short thesis failed h10/h20 next-open cost stress | `b8b73e6` | Revisit only with a materially different safety thesis. |
| `bank_regulatory_enforcement` | underpowered_feasibility | source/corpus/readiness | Federal Reserve source path worked, but public-bank adverse corpus was too small: 28 reviewed usable rows and 0 likely OOS predictions | `cb53eba` | Revisit only if a source expansion plan identifies enough additional public-bank adverse actions, such as durable OCC/FDIC/state ingestion plus audited public-bank parent mapping. |
| `material_customer_contract_loss_8k` | parser not trusted | source discovery/parser audit/readiness | Broad SEC full-text search produced 191 candidate 8-K rows but 0 audited true material customer-loss events; the only machine-proposed positive was a cybersecurity/operations false positive, leaving 0 reviewed usable rows and 0 likely OOS predictions | local run 2026-05-24 | Revisit only with a materially different source strategy or manually seeded parser gold set; do not rerun the same broad customer/termination 8-K search path. |
| `fda_warning_letters_manufacturing_enforcement` | mapping insufficient | source/corpus/readiness | Official FDA source and timestamps were good, but public-company mapping was too sparse: 47 mapped rows, 25 primary material enforcement rows, 0 likely OOS predictions | `d7d8db8` | Improve public company, subsidiary, product, and facility mapping before any modeling. |
| `patent_itc_litigation_events` | mapping insufficient | source feasibility | Official notice volume was sufficient, but company mapping and product/materiality fields were too weak from Federal Register metadata alone | `e034baa` | Use USITC IDS/EDIS participant parsing or ticker-linked company disclosures with manual product exposure review. |

## Common Failure Modes

The project repeatedly found that explanatory event reactions are not the same
as tradable post-event signals. Failed or frozen domains usually hit one or more
of these issues:

```text
timestamp/session leakage
feature lookahead
duplicate-event leakage
parser false positives
unreviewed lazy labels
first-tradable-window mistakes
next-open execution failure
cost/slippage fragility
liquidity/capacity limits
ticker/outlier concentration
failed fresh confirmation
insufficient public-company mapping
insufficient model-ready sample size
```

## Required Status Labels

Use one of these labels in future domain reports:

```text
model-ready
candidate paper signal
promising, requires fresh confirmation
underpowered_monitor
underpowered_feasibility
parser not trusted
context insufficient
timestamp insufficient
mapping insufficient
execution unrealistic
failed falsification
failed fresh confirmation
freeze domain
monitor later
```

Do not use `candidate paper signal` unless the domain has survived source
grounding, parser audit, reviewed corpus gates, timestamp/duplicate audit,
context/materiality checks, first falsification, fresh confirmation, final
leakage audit, execution stress, liquidity/capacity checks, and concentration
checks.

## Revisit Rules

Do not relaunch a frozen domain under the same thesis. A revisit requires:

```text
new pre-registered thesis
new source or mapping capability
larger reviewed corpus
clearer timestamp/public-awareness source
stronger materiality field
or a different execution hypothesis
```

Cybersecurity Item 1.05 is the main monitor domain. It should be refreshed
periodically, but not modeled until the row and OOS gates pass.

Underpowered feasibility domains, such as bank regulatory enforcement, are not
passive timer-based monitors. They require a specific source or mapping
improvement before rerunning.
