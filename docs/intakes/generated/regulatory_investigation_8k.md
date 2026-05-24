# Domain Intake: SEC 8-K Regulatory Investigation Disclosure

Domain slug: `regulatory_investigation_8k`

## Current Finder Score

- Total score: `25/30`
- Finder gate: `full_lifecycle`

## Scoring Rubric

Generated from Domain Finder's current scorecard. Review and adjust before launching an MRE agent.

| Dimension | Score | Notes |
| --- | ---: | --- |
| Official source quality | 3 | 2 official-source observations; source kinds: sec_official |
| Public timestamp clarity | 3 | Finder timestamp-quality score from observations |
| Delayed-digestion plausibility | 2 | investigation scope, regulator identity, and potential penalties are often uncertain; market may digest severity through later updates |
| Hard-negative clarity | 2 | duplicate press release; resolved investigation; routine risk-factor boilerplate; subpoena disclosed after settlement |
| Materiality-field clarity | 3 | investigation_scope; market_cap_before_event; penalty_language; regulator_type |
| Sample-size likelihood | 2 | max sample-size hint: 110 |
| Ticker/entity mapping feasibility | 3 | SEC issuer mapping is clean; investigation taxonomy needs parser audit |
| Liquidity/execution feasibility | 3 | public issuer liquidity filters required |
| Parser/audit feasibility | 2 | Estimated from source structure and domain text complexity |
| Fresh-data availability | 2 | evidence count: 3 |

## Front-Door Gate

1. What is the official or primary source?

   - Finder evidence: sec_official

2. What is the first realistic public-awareness timestamp?

3. Why should this still be tradable after next open?

   - Finder delayed-digestion notes: investigation scope, regulator identity, and potential penalties are often uncertain; market may digest severity through later updates

4. What hard negatives prevent lazy labels?

   - Finder hard negatives: duplicate press release; resolved investigation; routine risk-factor boilerplate; subpoena disclosed after settlement

5. What materiality field makes the event economically meaningful?

   - Finder materiality fields: investigation_scope; market_cap_before_event; penalty_language; regulator_type

6. What would make execution unrealistic?

7. What would make the result explanation-only rather than tradable?

## Required Feasibility Outputs

- Estimated source rows
- Estimated public-company mapped rows
- Estimated primary event rows
- Timestamp quality assessment
- Hard-negative examples
- Materiality coverage estimate
- Liquidity/execution risk
- Recommendation: full lifecycle / feasibility only / backlog / skip
