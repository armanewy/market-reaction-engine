# Capital Raises / Dilution Milestone

This milestone starts the capital-raises domain as a data-product track, not a prediction track.

The research question is:

```text
Do equity offerings, ATM programs, convertibles, shelf registrations, and liquidity warnings produce measurable abnormal returns after controlling for market context, offering size, discount, pre-event run-up, and dilution risk?
```

The first implementation only creates source-grounded candidate rows:

```text
source document
-> parsed financing facts
-> reviewable feature rows
-> review-queue event rows
```

It intentionally does not run a model.

## Domain

The corpus domain is:

```text
capital_raise_dilution
```

Supported event labels include:

```text
equity_offering
registered_direct_offering
atm_program
convertible_debt
shelf_registration
private_placement
going_concern_warning
```

## Parser Command

```bash
mre parse-capital-raises \
  --documents data/events/capital_raise_source_documents.csv \
  --facts-out data/events/capital_raise_facts.csv \
  --features-out data/events/capital_raise_features.csv \
  --events-out data/events/capital_raise_review_queue.csv
```

Important extracted fields:

```text
financing_event_type
security_type
offering_amount
gross_proceeds
net_proceeds
shares_offered
price_per_share
atm_capacity
convertible_principal
conversion_price
use_of_proceeds
underwriter_or_agent
going_concern_warning
liquidity_warning
```

## Modeling Gate

Do not model this domain until there is a reviewed corpus with:

```text
80+ reviewed usable events
clear event timestamps
offering amount or ATM/convertible principal coverage
price/discount coverage where applicable
market-cap or shares-outstanding context
placebo and peer controls
walk-forward validation
cost/slippage simulation
```

The parser output is a review queue, not a model-ready corpus.
