# Domain Schema Scaffold

The JSON files in `schemas/domains/` are an additive scaffold for making domain
quality comparable. They do not replace `src/mre/corpus.py` yet; the current
`DOMAIN_SPECS` registry remains the source of truth for template generation and
existing CLI behavior.

Each schema declares:

- `domain`, `event_type`, `default_subtype`, and `description`
- review columns that must be manually or mechanically verified before modeling
- domain-specific source fields
- categorical and numeric features that are intended to be known before the
  reaction window
- promotion gates such as minimum reviewed rows and likely walk-forward
  predictions

The loader in `src/mre/domain_schema.py` intentionally uses JSON rather than
YAML so the scaffold does not add a runtime dependency. Future migrations should
move one domain at a time from the Python registry into schema-driven templates,
validation, promotion reports, and feature selection.

Schema files are expected to be small and explicit. They should not include
post-event price outcomes, model predictions, or fields whose values require
looking past `event_time`.
