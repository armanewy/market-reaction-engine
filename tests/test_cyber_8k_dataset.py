from __future__ import annotations

import json

import pandas as pd

from mre.cyber_8k_dataset import build_cyber_8k_dataset
from mre.source_docs import make_source_docs_template


def test_build_cyber_8k_dataset_from_manifest(tmp_path):
    manifest = tmp_path / "source_documents.csv"
    make_source_docs_template(
        manifest,
        rows=[
            {
                "source_doc_id": "doc1",
                "ticker": "ACME",
                "event_id": "event1",
                "event_time": "2024-01-02T16:05:00",
                "event_type": "cybersecurity",
                "event_subtype": "sec_8_k_item_1_05",
                "release_session": "after_close",
                "source_type": "sec_primary_filing",
                "source_url": "https://sec.test/acme",
                "title": "ACME Item 1.05",
                "notes": json.dumps({"cik": "123456", "company_name": "Acme Corp", "form": "8-K", "accession": "orig"}),
                "text": "Item 1.05 Material Cybersecurity Incident. ACME experienced operational disruption after a ransomware incident.",
            }
        ],
    )

    summary = build_cyber_8k_dataset(manifest, out_dir=tmp_path / "out", auto_accept_min_confidence=0.8)

    events = pd.read_csv(summary["outputs"]["events"])
    claims = pd.read_csv(summary["outputs"]["claims"])
    review = pd.read_csv(summary["outputs"]["review_queue"])
    assert summary["events"] == 1
    assert not claims.empty
    assert events.loc[0, "ransomware_mentioned"] == True
    assert events.loc[0, "operational_disruption_mentioned"] == True
    assert events.loc[0, "timestamp_readiness_status"] == "ok"
    assert review["review_status"].eq("machine_high_confidence").any()
    assert json.loads((tmp_path / "out" / "cyber_summary.json").read_text(encoding="utf-8"))["events"] == 1
