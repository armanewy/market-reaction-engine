from __future__ import annotations

from pathlib import Path

import pandas as pd

from mre.cyber_8k_dataset import build_cyber_8k_dataset
from mre.cyber_8k_plugin import run_cyber_8k_plugin_manifest


FIXTURE = Path("tests/fixtures/cyber_8k/source_documents.csv")


def test_cyber_8k_golden_fixture_parser_and_dataset(tmp_path):
    claims, evidence, diagnostics = run_cyber_8k_plugin_manifest(FIXTURE)
    expected = set(pd.read_csv("tests/fixtures/cyber_8k/expected_claims.csv")["field_name"])

    assert expected.issubset(set(claims["field_name"]))
    assert diagnostics["documents_total"] == 2
    for _, span in evidence.iterrows():
        source_doc = pd.read_csv(FIXTURE)
        doc_row = source_doc[source_doc["source_doc_id"] == span["source_doc_id"]].iloc[0]
        text = (Path("tests/fixtures/cyber_8k") / doc_row["path"]).read_text(encoding="utf-8")
        assert span["evidence_text"] in text

    summary = build_cyber_8k_dataset(FIXTURE, out_dir=tmp_path / "dataset", auto_accept_min_confidence=0.8)
    events = pd.read_csv(summary["outputs"]["events"])
    assert len(events) == 2
    assert events["third_party_vendor_mentioned"].any()
    assert claims[claims["field_name"] == "amendment_flag"]["event_id"].str.contains("AMEND").any()
