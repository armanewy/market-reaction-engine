# Domain Intake Template

Use this template before assigning a new Market Reaction Engine domain to an
agent. The purpose is to stop weak domains before they become code-heavy
scaffolds or attractive but fragile backtests.

## Domain Packet

```text
Domain name:

Short description:

Research question:

Candidate universe:

Primary source types:

Primary benchmark:
SPY

Sector benchmark:

Event types:

Critical lazy-label risk:

Key extracted facts:

Key context/materiality fields:

Hard negatives:

Pre-registered hypotheses:
```

## Front-Door Gate

Answer these before writing code.

### 1. Official Source

```text
What is the official or primary source?
Is it machine-readable or programmatically retrievable?
Is source access stable enough for repeated runs?
```

Fail early if source access is ad hoc, paid-only, or too manual for a durable
pipeline.

### 2. Public-Awareness Timestamp

```text
What is the first realistic public-awareness timestamp?
Is it the same as the record date?
Can we distinguish before-open, intraday, and after-close release sessions?
Could the market have known before our event_time?
```

Fail early if the record date is not the public timestamp and no reliable
publication or announcement timestamp exists.

### 3. Delayed-Digestion Rationale

This is the most important gate.

```text
Why should the market still be digesting this after next open?
```

Strong answers include:

```text
complex legal or regulatory implications
multi-day analyst digestion
uncertain financial impact
follow-up disclosures likely
institutional undercoverage
fragmented or obscure source
company-specific materiality requires calculation
```

Weak answers include:

```text
binary outcome fully resolves uncertainty
headline instantly conveys impact
stock likely gaps before first tradable entry
event is routine or expected
```

Fail early if the domain is mostly an immediate-gap domain and there is no
intraday, pre-event, or delayed-digestion strategy.

### 4. Hard Negatives

Define hard negatives before parsing.

Examples:

```text
shelf registration is not completed financing
USAspending record is not market-public contract announcement
conference presentation is not clinical readout
routine recall is not material safety event
routine auditor change is not accounting integrity shock
option exercise is not insider open-market purchase
termination of consent order is not new enforcement action
generic cybersecurity risk language is not a material incident
minor FDA labeling issue is not material manufacturing enforcement
routine legal docket item is not material patent/ITC event
```

Fail early if hard negatives cannot be stated clearly.

### 5. Materiality Field

The event needs a field that separates meaningful cases from noise.

Examples:

```text
financing amount / market cap
obligated contract amount / market cap
transaction value / market cap
affected units / annual sales
civil penalty / market cap or assets
product revenue exposure
asset or pipeline concentration
injunction/exclusion/remedy severity
repeat-offender flag
severity classification
```

Fail early if there is no plausible materiality field.

### 6. Breadth and Concentration

Before modeling, the domain should plausibly support:

```text
80+ reviewed usable events minimum
100+ reviewed usable events preferred
60+ primary event rows where applicable
40+ rows with primary materiality context
40+ rows with relevant pre-event context
30+ likely OOS predictions
enough tickers to avoid concentration
controls or hard negatives
```

Fail early if the domain is structurally too sparse or likely to be dominated
by a few tickers/events.

### 7. Execution Survivability

Every modeled domain must report:

```text
close-to-close behavior
next-open behavior
25 / 50 / 100 bps cost stress
liquidity filters
capacity / ADV constraints
outlier and top-ticker contribution
```

Fail if:

```text
next-open fails
100 bps destroys the result
liquid subset is tiny
top 5 tickers/events dominate
```

## Scoring Rubric

Score each category from 0 to 3.

```text
0 = missing or poor
1 = weak
2 = adequate
3 = strong
```

| Dimension | Score | Notes |
| --- | ---: | --- |
| Official source quality |  |  |
| Public timestamp clarity |  |  |
| Delayed-digestion plausibility |  |  |
| Hard-negative clarity |  |  |
| Materiality-field clarity |  |  |
| Sample-size likelihood |  |  |
| Ticker/entity mapping feasibility |  |  |
| Liquidity/execution feasibility |  |  |
| Parser/audit feasibility |  |  |
| Fresh-data availability |  |  |

Total possible: 30.

Interpretation:

```text
24-30: worth a full agent lifecycle
18-23: source-feasibility only
12-17: backlog, do not assign yet
<12: skip unless new data/source appears
```

A domain should not get a full lifecycle agent unless it scores at least:

```text
2+ on public timestamp clarity
2+ on delayed-digestion plausibility
2+ on materiality-field clarity
2+ on sample-size likelihood
```

## Recommended Agent Scope

### Full Lifecycle

Use only for domains scoring 24 or above and clearing the minimum required
dimension scores.

Required stages:

```text
source discovery
parser/fact extraction
review queue
reviewed corpus
parser audit
context/materiality enrichment
timestamp/duplicate audit
readiness gates
first falsification if model-ready
fresh confirmation if promising
final leakage/execution audit if fresh-confirmed
```

### Source Feasibility Only

Use for domains scoring 18 to 23.

Required report:

```text
official source URLs/APIs
timestamp source
entity-to-ticker mapping plan
expected sample size
hard negatives
materiality fields
execution-survivability rationale
recommendation: build / skip / needs manual data
```

### Backlog Only

Use for domains scoring below 18, or any domain that fails a critical gate.

Do not assign an implementation agent until the missing source, mapping,
materiality, or execution rationale is solved.

## Final Intake Decision

```text
Domain:
Score:
Critical gates passed:
Critical gates failed:
Recommended scope:
  full lifecycle / source-feasibility only / backlog / skip
Reason:
Revisit trigger:
```

