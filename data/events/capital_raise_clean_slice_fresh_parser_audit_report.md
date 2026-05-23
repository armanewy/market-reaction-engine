# Capital Raise Clean Slice Fresh Parser Audit

Decision: **not independently audited on the fresh rows**.

The fresh-data pass inherits the completed-common-stock / registered-direct parser standard from Agent 2G, where the focused clean-slice audit was 33/33 correct. This fresh pass did not create a new independent gold set because the available fresh corpus was already below the data-volume and market-context gates.

Fresh parser-audit status:

- Inherited focused clean-slice audit rows: 33
- Inherited focused clean-slice audit accuracy: 100%
- Fresh independent audit rows: 0
- Fresh parser-audit gate: not passed for fresh confirmation

Reason: the fresh corpus has only 32 reviewed rows and 22 event-study-usable rows, so the correct decision is underpowered corpus buildout rather than spending audit effort on a non-modelable sample.
