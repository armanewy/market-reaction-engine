# Domain Intake: 8-K Executive Departure for Cause / Investigation Context

Domain slug: `executive_departure_for_cause_8k`

## Current Finder Score

- Total score: `25/30`
- Finder gate: `full_lifecycle`

## Scoring Rubric

Generated from Domain Finder's current scorecard. Review and adjust before launching an MRE agent.

| Dimension | Score | Notes |
| --- | ---: | --- |
| Official source quality | 3 | 2 official-source observations; source kinds: sec_official |
| Public timestamp clarity | 3 | Finder timestamp-quality score from observations |
| Delayed-digestion plausibility | 2 | for-cause language and investigation context may require filing text review; leadership risk can be digested over several sessions |
| Hard-negative clarity | 2 | director resignation without disagreement; duplicate 8-K amendment; planned succession; routine retirement |
| Materiality-field clarity | 3 | for_cause_flag; investigation_flag; market_cap_before_event; role_ceo_cfo_flag |
| Sample-size likelihood | 2 | max sample-size hint: 120 |
| Ticker/entity mapping feasibility | 3 | SEC CIK mapping is clean; role extraction needs parser audit |
| Liquidity/execution feasibility | 3 | public issuers; liquidity filters still required |
| Parser/audit feasibility | 2 | Estimated from source structure and domain text complexity |
| Fresh-data availability | 2 | evidence count: 3 |

## Front-Door Gate

1. What is the official or primary source?

   - Finder evidence: sec_official

2. What is the first realistic public-awareness timestamp?

3. Why should this still be tradable after next open?

   - Finder delayed-digestion notes: for-cause language and investigation context may require filing text review; leadership risk can be digested over several sessions

4. What hard negatives prevent lazy labels?

   - Finder hard negatives: director resignation without disagreement; duplicate 8-K amendment; planned succession; routine retirement

5. What materiality field makes the event economically meaningful?

   - Finder materiality fields: for_cause_flag; investigation_flag; market_cap_before_event; role_ceo_cfo_flag

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
