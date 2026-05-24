# Domain Intake: Material Customer / Contract Loss 8-K

Domain slug: `material_customer_contract_loss_8k`

## Current Finder Score

- Total score: `25/30`
- Finder gate: `full_lifecycle`

## Scoring Rubric

Generated from Domain Finder's current scorecard. Review and adjust before launching an MRE agent.

| Dimension | Score | Notes |
| --- | ---: | --- |
| Official source quality | 3 | 2 official-source observations; source kinds: sec_official |
| Public timestamp clarity | 3 | Finder timestamp-quality score from observations |
| Delayed-digestion plausibility | 2 | impact can be clarified through follow-up filings; revenue exposure may need calculation from customer concentration and contract terms |
| Hard-negative clarity | 2 | already-announced customer loss; contract renewal with changed terms; immaterial customer notice; routine contract expiration |
| Materiality-field clarity | 3 | contract_value_pct_market_cap; customer_revenue_pct; market_cap_before_event; termination_flag |
| Sample-size likelihood | 2 | max sample-size hint: 90 |
| Ticker/entity mapping feasibility | 3 | SEC issuer mapping is clean; customer mapping may require manual review |
| Liquidity/execution feasibility | 3 | issuer liquidity likely mixed; require ADV buckets |
| Parser/audit feasibility | 2 | Estimated from source structure and domain text complexity |
| Fresh-data availability | 2 | evidence count: 3 |

## Front-Door Gate

1. What is the official or primary source?

   - Finder evidence: sec_official

2. What is the first realistic public-awareness timestamp?

3. Why should this still be tradable after next open?

   - Finder delayed-digestion notes: impact can be clarified through follow-up filings; revenue exposure may need calculation from customer concentration and contract terms

4. What hard negatives prevent lazy labels?

   - Finder hard negatives: already-announced customer loss; contract renewal with changed terms; immaterial customer notice; routine contract expiration

5. What materiality field makes the event economically meaningful?

   - Finder materiality fields: contract_value_pct_market_cap; customer_revenue_pct; market_cap_before_event; termination_flag

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
