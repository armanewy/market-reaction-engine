from __future__ import annotations

import pandas as pd

from mre.amendments import add_amendment_flags, build_amendment_chains


def test_build_amendment_chains_links_same_issuer_item_8k_amendment():
    filings = pd.DataFrame(
        [
            {"cik": "1", "accession": "orig", "form": "8-K", "accepted_at": "2024-01-02T16:00:00", "item_numbers": "1.05"},
            {"cik": "1", "accession": "amend", "form": "8-K/A", "accepted_at": "2024-01-05T16:00:00", "item_numbers": "1.05"},
            {"cik": "2", "accession": "other", "form": "8-K/A", "accepted_at": "2024-01-06T16:00:00", "item_numbers": "1.05"},
        ]
    )

    chains = build_amendment_chains(filings)

    linked = chains[chains["amendment_accession"] == "amend"].iloc[0]
    unmatched = chains[chains["amendment_accession"] == "other"].iloc[0]
    assert linked["original_accession"] == "orig"
    assert linked["days_after_original"] == 3
    assert "same_item" in linked["link_method"]
    assert unmatched["link_method"] == "unmatched_amendment"


def test_add_amendment_flags_sets_counts():
    events = pd.DataFrame([{"event_id": "E1", "accession": "orig"}, {"event_id": "E2", "accession": "other"}])
    chains = pd.DataFrame(
        [
            {"original_accession": "orig", "amendment_accession": "amend1", "days_after_original": 2.5},
            {"original_accession": "orig", "amendment_accession": "amend2", "days_after_original": 4.0},
        ]
    )

    out = add_amendment_flags(events, chains)

    row = out.set_index("event_id").loc["E1"]
    assert row["amended_later"] == True
    assert row["amendment_count"] == 2
    assert row["first_amendment_days"] == 2.5
