from __future__ import annotations

import pandas as pd

from mre.features import FeatureSpec, available_feature_specs, specs_from_names, split_feature_specs


def test_specs_from_names_preserves_categorical_and_numeric_order():
    specs = specs_from_names(["ticker", "event_type"], ["materiality", "pre_return_20d"])

    assert [spec.name for spec in specs] == ["ticker", "event_type", "materiality", "pre_return_20d"]
    assert specs[0].dtype == "categorical"
    assert specs[-1].dtype == "numeric"


def test_available_feature_specs_filters_missing_disallowed_and_all_null_numeric():
    df = pd.DataFrame({"ticker": ["AAA"], "materiality": [0.8], "empty_numeric": [None], "future_return": [0.12]})
    specs = [
        FeatureSpec("ticker", "categorical", "event_metadata"),
        FeatureSpec("materiality", "numeric", "manual_review"),
        FeatureSpec("empty_numeric", "numeric", "derived"),
        FeatureSpec("missing", "categorical", "event_metadata"),
        FeatureSpec("future_return", "numeric", "derived", allowed_for_modeling=False),
    ]

    available = available_feature_specs(df, specs)

    assert [spec.name for spec in available] == ["ticker", "materiality"]


def test_high_leakage_features_excluded_by_default():
    df = pd.DataFrame({"ticker": ["AAA"], "future_return": [0.12]})
    specs = [
        FeatureSpec("ticker", "categorical", "event_metadata"),
        FeatureSpec("future_return", "numeric", "derived", leakage_risk="high"),
    ]

    assert [spec.name for spec in available_feature_specs(df, specs)] == ["ticker"]
    assert [spec.name for spec in available_feature_specs(df, specs, allow_high_leakage=True)] == ["ticker", "future_return"]


def test_split_feature_specs_treats_boolean_as_numeric():
    specs = [
        FeatureSpec("release_session", "categorical", "event_metadata"),
        FeatureSpec("materiality", "numeric", "manual_review"),
        FeatureSpec("item_105_flag", "boolean", "source_doc"),
    ]

    categorical, numeric = split_feature_specs(specs)

    assert categorical == ["release_session"]
    assert numeric == ["materiality", "item_105_flag"]


def test_feature_spec_validates_metadata():
    try:
        FeatureSpec("", "numeric", "derived")
    except ValueError as exc:
        assert "non-empty" in str(exc)
    else:
        raise AssertionError("Expected ValueError")
