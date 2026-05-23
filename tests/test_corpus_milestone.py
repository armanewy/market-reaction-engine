from __future__ import annotations

import pandas as pd

from mre.corpus import build_curated_corpus, list_corpus_domains, make_domain_event_template, validate_corpus_csv


def test_domain_template_contains_domain_columns(tmp_path):
    out = tmp_path / "fda_template.csv"
    df = make_domain_event_template("fda", out, tickers=["ABC"], corpus_name="fda_v1")
    assert out.exists()
    assert df.loc[0, "event_family"] == "fda_biotech"
    assert "trial_phase" in df.columns
    assert "drug_or_device" in df.columns
    domains = list_corpus_domains()
    assert "cyber_incident" in set(domains["domain"])


def test_build_and_validate_curated_corpus(tmp_path):
    input_path = tmp_path / "cyber_reviewed.csv"
    rows = [
        {
            "event_id": "cyber_001",
            "ticker": "XYZ",
            "event_time": "2024-05-01T16:05:00",
            "event_type": "cybersecurity",
            "event_subtype": "breach",
            "event_family": "cyber_incident",
            "summary": "Reviewed breach disclosure.",
            "source_type": "sec_8k",
            "source_url": "https://example.com/8k",
            "release_session": "after_close",
            "expectedness": "surprise",
            "surprise_direction": "negative",
            "surprise_magnitude": "medium",
            "materiality": 0.7,
            "sector_benchmark": "XLK",
            "review_status": "reviewed",
            "label_quality": "high",
            "source_doc_ids": "doc1",
            "evidence_status": "verified",
            "incident_type": "breach",
            "customer_data_exposed": True,
            "severity_score": 0.8,
        }
    ]
    pd.DataFrame(rows).to_csv(input_path, index=False)
    out = tmp_path / "corpus.csv"
    df, diag = build_curated_corpus([input_path], out, corpus_name="cyber_v1")
    assert diag.rows_ok == 1
    assert df.loc[0, "corpus_validation_status"] == "ok"
    validated, diag2 = validate_corpus_csv(out, tmp_path / "validated.csv")
    assert diag2.rows_ok == 1
    assert validated.loc[0, "event_family"] == "cyber_incident"
