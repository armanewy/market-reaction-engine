# Domain Intake: FERC Utility Enforcement Actions

Domain slug: `ferc_utility_enforcement_actions`

## Current Finder Score

- Total score: `24/30`
- Finder gate: `full_lifecycle`

## Scoring Rubric

Generated from Domain Finder's current scorecard. Review and adjust before launching an MRE agent.

| Dimension | Score | Notes |
| --- | ---: | --- |
| Official source quality | 3 | 2 official-source observations; source kinds: official_agency |
| Public timestamp clarity | 3 | Finder timestamp-quality score from observations |
| Delayed-digestion plausibility | 2 | market impact depends on rate base, region, and penalty materiality; utility regulatory consequences can unfold through compliance plans and penalties |
| Hard-negative clarity | 2 | duplicate press release; immaterial settlement; non-public utility; routine compliance filing |
| Materiality-field clarity | 3 | compliance_restriction_flag; penalty_pct_market_cap; repeat_offender_flag; utility_segment_exposure |
| Sample-size likelihood | 2 | max sample-size hint: 80 |
| Ticker/entity mapping feasibility | 2 | utility parent mapping feasible but needs manual validation |
| Liquidity/execution feasibility | 3 | public utilities are generally liquid; smaller issuers need filters |
| Parser/audit feasibility | 2 | Estimated from source structure and domain text complexity |
| Fresh-data availability | 2 | evidence count: 3 |

## Front-Door Gate

1. What is the official or primary source?

   - Finder evidence: official_agency

2. What is the first realistic public-awareness timestamp?

3. Why should this still be tradable after next open?

   - Finder delayed-digestion notes: market impact depends on rate base, region, and penalty materiality; utility regulatory consequences can unfold through compliance plans and penalties

4. What hard negatives prevent lazy labels?

   - Finder hard negatives: duplicate press release; immaterial settlement; non-public utility; routine compliance filing

5. What materiality field makes the event economically meaningful?

   - Finder materiality fields: compliance_restriction_flag; penalty_pct_market_cap; repeat_offender_flag; utility_segment_exposure

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
