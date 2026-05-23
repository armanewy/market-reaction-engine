from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, balanced_accuracy_score, brier_score_loss, log_loss, roc_auc_score
from sklearn.neighbors import NearestNeighbors
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .paths import ensure_parent

CATEGORICAL_FEATURES = [
    "ticker",
    "event_type",
    "event_subtype",
    "event_family",
    "source_type",
    "release_session",
    "expectedness",
    "surprise_direction",
    "surprise_direction_inferred",
    "surprise_magnitude",
    "surprise_magnitude_inferred",
    "sec_form",
    "sec_items",
    "expectation_source_type",
    "expectation_quality",
    "pre_runup_bucket_20d",
    "release_time_status",
    "release_time_confidence",
    "release_time_source_type",
    "implied_move_status",
    "analyst_revision_status",
    "corpus_name",
    "review_status",
    "label_quality",
    "evidence_status",
    "corpus_validation_status",
    "agency",
    "jurisdiction",
    "action_type",
    "affected_business_line",
    "remedy_risk",
    "injunction_risk",
    "novelty",
    "appeal_status",
    "expected_resolution_window",
    "drug_or_device",
    "indication",
    "trial_phase",
    "trial_result",
    "primary_endpoint_met",
    "secondary_endpoint_signal",
    "safety_signal",
    "pdufa_decision",
    "approval_status",
    "incident_type",
    "breach_confirmed",
    "systems_affected",
    "customer_data_exposed",
    "ransomware",
    "operational_disruption",
    "insurance_coverage_known",
    "regulatory_notification_required",
    "product_or_model",
    "recall_class",
    "safety_risk",
    "injuries_or_deaths_reported",
    "remedy_available",
    "production_halt",
    "geography",
]

NUMERIC_FEATURES = [
    "materiality",
    "pre_return_5d",
    "pre_return_20d",
    "pre_return_60d",
    "benchmark_pre_return_5d",
    "benchmark_pre_return_20d",
    "benchmark_pre_return_60d",
    "market_adjusted_pre_return_5d",
    "market_adjusted_pre_return_20d",
    "market_adjusted_pre_return_60d",
    "sector_adjusted_pre_return_5d",
    "sector_adjusted_pre_return_20d",
    "sector_adjusted_pre_return_60d",
    "pre_vol_20d",
    "pre_vol_60d",
    "benchmark_pre_vol_20d",
    "rolling_beta_60d",
    "idiosyncratic_vol_60d",
    "volume_zscore_20d",
    "pre_runup_z_20d",
    "surprise_vs_runup_score",
    "alpha",
    "beta",
    "residual_vol",
    "consensus_eps",
    "actual_eps",
    "reported_eps",
    "estimated_eps",
    "eps_surprise",
    "eps_surprise_pct",
    "eps_abs_surprise_pct",
    "earnings_surprise_abs_max_pct",
    "eps_signal_strength",
    "eps_surprise_sign",
    "eps_has_estimate",
    "consensus_forward_eps",
    "guidance_eps_low",
    "guidance_eps_high",
    "guidance_eps_mid",
    "guidance_eps_surprise",
    "guidance_eps_surprise_pct",
    "consensus_revenue",
    "actual_revenue",
    "revenue_surprise",
    "revenue_surprise_pct",
    "consensus_forward_revenue",
    "guidance_revenue_low",
    "guidance_revenue_high",
    "guidance_revenue_mid",
    "guidance_revenue_surprise",
    "guidance_revenue_surprise_pct",
    "prior_guidance_revenue_mid",
    "actual_vs_prior_management_guidance",
    "actual_vs_prior_management_guidance_pct",
    "management_guidance_surprise_pct",
    "new_guidance_vs_actual",
    "new_guidance_vs_actual_pct",
    "parser_confidence_min",
    "consensus_gross_margin",
    "actual_gross_margin",
    "gross_margin_surprise",
    "gross_margin_surprise_pct",
    "consensus_forward_gross_margin",
    "guidance_gross_margin_low",
    "guidance_gross_margin_high",
    "guidance_gross_margin_mid",
    "guidance_gross_margin_surprise",
    "guidance_gross_margin_surprise_pct",
    "implied_move_pct",
    "implied_move_days_to_expiration",
    "implied_move_strike",
    "implied_move_underlying_price",
    "implied_move_call_mid",
    "implied_move_put_mid",
    "analyst_count",
    "fundamental_surprise_score",
    "surprise_signal_count",
    "analyst_eps_count",
    "analyst_eps_consensus",
    "analyst_eps_dispersion",
    "analyst_eps_revision_count_7d",
    "analyst_eps_revision_mean_7d",
    "analyst_eps_revision_median_7d",
    "analyst_eps_revision_pct_up_7d",
    "analyst_eps_revision_pct_down_7d",
    "analyst_eps_revision_count_30d",
    "analyst_eps_revision_mean_30d",
    "analyst_eps_revision_median_30d",
    "analyst_eps_revision_pct_up_30d",
    "analyst_eps_revision_pct_down_30d",
    "analyst_revenue_count",
    "analyst_revenue_consensus",
    "analyst_revenue_dispersion",
    "analyst_revenue_revision_count_7d",
    "analyst_revenue_revision_mean_7d",
    "analyst_revenue_revision_median_7d",
    "analyst_revenue_revision_pct_up_7d",
    "analyst_revenue_revision_pct_down_7d",
    "analyst_revenue_revision_count_30d",
    "analyst_revenue_revision_mean_30d",
    "analyst_revenue_revision_median_30d",
    "analyst_revenue_revision_pct_up_30d",
    "analyst_revenue_revision_pct_down_30d",
    "analyst_gross_margin_count",
    "analyst_gross_margin_consensus",
    "analyst_gross_margin_dispersion",
    "analyst_gross_margin_revision_count_7d",
    "analyst_gross_margin_revision_mean_7d",
    "analyst_gross_margin_revision_median_7d",
    "analyst_gross_margin_revision_pct_up_7d",
    "analyst_gross_margin_revision_pct_down_7d",
    "analyst_gross_margin_revision_count_30d",
    "analyst_gross_margin_revision_mean_30d",
    "analyst_gross_margin_revision_median_30d",
    "analyst_gross_margin_revision_pct_up_30d",
    "analyst_gross_margin_revision_pct_down_30d",
    "analyst_forward_revenue_count",
    "analyst_forward_revenue_consensus",
    "analyst_forward_revenue_dispersion",
    "analyst_forward_revenue_revision_count_7d",
    "analyst_forward_revenue_revision_mean_7d",
    "analyst_forward_revenue_revision_median_7d",
    "analyst_forward_revenue_revision_pct_up_7d",
    "analyst_forward_revenue_revision_pct_down_7d",
    "analyst_forward_revenue_revision_count_30d",
    "analyst_forward_revenue_revision_mean_30d",
    "analyst_forward_revenue_revision_median_30d",
    "analyst_forward_revenue_revision_pct_up_30d",
    "analyst_forward_revenue_revision_pct_down_30d",
    "expected_abs_move_h1_realized_vol_20d",
    "expected_abs_move_h3_realized_vol_20d",
    "expected_abs_move_h10_realized_vol_20d",
    "market_size_estimate",
    "pipeline_concentration_pct",
    "cash_runway_months",
    "prior_probability",
    "fine_or_penalty_amount",
    "disclosure_delay_days",
    "estimated_cost",
    "severity_score",
    "recall_units",
    "affected_revenue_pct",
]


def _one_hot_encoder() -> OneHotEncoder:
    try:
        return OneHotEncoder(handle_unknown="ignore", sparse_output=True)
    except TypeError:  # pragma: no cover - older scikit-learn
        return OneHotEncoder(handle_unknown="ignore", sparse=True)


def prepare_feature_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in NUMERIC_FEATURES:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    for col in CATEGORICAL_FEATURES:
        if col in out.columns:
            out[col] = out[col].fillna("unknown").astype(str)
    return out


def available_features(df: pd.DataFrame) -> tuple[list[str], list[str]]:
    cat = [c for c in CATEGORICAL_FEATURES if c in df.columns]
    # Avoid feeding all-null numeric columns into SimpleImputer; newer scikit-learn
    # warns and silently drops them.  A feature with no observed values cannot help
    # the model and can make report/debug output noisy.
    num = [
        c
        for c in NUMERIC_FEATURES
        if c in df.columns and pd.to_numeric(df[c], errors="coerce").notna().any()
    ]
    return cat, num


def make_preprocessor(df: pd.DataFrame) -> ColumnTransformer:
    df = prepare_feature_frame(df)
    cat, num = available_features(df)
    transformers: list[tuple[str, Pipeline, list[str]]] = []
    if cat:
        transformers.append(("cat", Pipeline([("imputer", SimpleImputer(strategy="constant", fill_value="unknown")), ("onehot", _one_hot_encoder())]), cat))
    if num:
        transformers.append(("num", Pipeline([("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler())]), num))
    if not transformers:
        raise ValueError("No modeling features are available in this frame")
    return ColumnTransformer(transformers=transformers)


def make_direction_pipeline(df: pd.DataFrame) -> Pipeline:
    return Pipeline([
        ("preprocessor", make_preprocessor(df)),
        ("classifier", LogisticRegression(max_iter=2000, class_weight="balanced", solver="liblinear")),
    ])


def load_event_study(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "reaction_start" in df.columns:
        df["reaction_start"] = pd.to_datetime(df["reaction_start"], errors="coerce")
    if "event_time" in df.columns:
        df["event_time"] = pd.to_datetime(df["event_time"], errors="coerce")
    return df


def _target_series(series: pd.Series) -> pd.Series:
    y = series.astype(str).str.lower().map({"true": 1, "false": 0, "1": 1, "0": 0})
    if y.isna().any():
        y = series.astype(bool).astype(int)
    else:
        y = y.astype(int)
    return y


def modeling_frame(df: pd.DataFrame, horizon: int = 1) -> tuple[pd.DataFrame, pd.Series]:
    target = f"target_positive_h{horizon}"
    car = f"car_market_model_h{horizon}"
    required = ["event_status", target, car]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns for modeling: {missing}")
    clean = df[(df["event_status"] == "ok") & df[target].notna() & df[car].notna()].copy()
    if clean.empty:
        raise ValueError("No usable event-study rows for modeling")
    clean = prepare_feature_frame(clean)
    y = _target_series(clean[target])
    return clean, y


def chronological_split(df: pd.DataFrame, y: pd.Series, test_size: float = 0.3) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
    if "reaction_start" in df.columns:
        order = pd.to_datetime(df["reaction_start"], errors="coerce").sort_values(kind="mergesort").index
    elif "event_time" in df.columns:
        order = pd.to_datetime(df["event_time"], errors="coerce").sort_values(kind="mergesort").index
    else:
        order = df.index
    ordered_df = df.loc[order].reset_index(drop=True)
    ordered_y = y.loc[order].reset_index(drop=True)
    n = len(ordered_df)
    split = max(1, int(round(n * (1.0 - test_size))))
    split = min(split, n - 1) if n > 1 else n
    return ordered_df.iloc[:split], ordered_df.iloc[split:], ordered_y.iloc[:split], ordered_y.iloc[split:]


def _classification_metrics(y_true: pd.Series, proba: np.ndarray, pred: np.ndarray) -> dict[str, Any]:
    y_true = pd.Series(y_true).astype(int)
    proba = np.clip(np.asarray(proba, dtype=float), 1e-6, 1.0 - 1e-6)
    pred = np.asarray(pred, dtype=int)
    metrics: dict[str, Any] = {
        "accuracy": float(accuracy_score(y_true, pred)),
        "brier_score": float(brier_score_loss(y_true, proba)),
    }
    if y_true.nunique() == 2:
        metrics["balanced_accuracy"] = float(balanced_accuracy_score(y_true, pred))
        metrics["roc_auc"] = float(roc_auc_score(y_true, proba))
        metrics["log_loss"] = float(log_loss(y_true, proba, labels=[0, 1]))
    return metrics


def train_direction_model(
    event_study_path: str | Path,
    horizon: int = 1,
    out_model: str | Path | None = None,
    out_report: str | Path | None = None,
    test_size: float = 0.3,
) -> dict[str, Any]:
    df = load_event_study(event_study_path)
    frame, y = modeling_frame(df, horizon=horizon)
    cat, num = available_features(frame)
    X_train, X_test, y_train, y_test = chronological_split(frame, y, test_size=test_size)
    model = make_direction_pipeline(frame)
    report: dict[str, Any] = {
        "horizon": horizon,
        "n_events": int(len(frame)),
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "categorical_features": cat,
        "numeric_features": num,
        "target": f"target_positive_h{horizon}",
        "warnings": ["Baseline model only. Treat metrics as a plumbing diagnostic until validated with placebos and walk-forward tests."],
    }
    if len(frame) < 30:
        report["warnings"].append("Very small sample. Metrics are unstable.")
    if y.nunique() < 2:
        raise ValueError("Target has only one class; cannot train a direction classifier")
    if y_train.nunique() < 2:
        report["warnings"].append("Chronological train split had one class; fitted on full data and skipped out-of-sample metrics.")
        model.fit(frame, y)
        report["metrics"] = {}
    else:
        model.fit(X_train, y_train)
        if len(X_test) > 0:
            pred = model.predict(X_test)
            proba = model.predict_proba(X_test)[:, 1]
            report["metrics"] = _classification_metrics(y_test, proba, pred)
        else:
            report["metrics"] = {}
    if out_model:
        p = ensure_parent(out_model)
        joblib.dump({"pipeline": model, "horizon": horizon, "categorical_features": cat, "numeric_features": num, "target": f"target_positive_h{horizon}"}, p)
        report["model_path"] = str(p)
    if out_report:
        p = ensure_parent(out_report)
        p.write_text(json.dumps(report, indent=2, default=str))
        report["report_path"] = str(p)
    return report


def predict_direction(model_path: str | Path, event_study_path: str | Path, out_path: str | Path | None = None) -> pd.DataFrame:
    bundle = joblib.load(model_path)
    pipeline = bundle["pipeline"]
    df = load_event_study(event_study_path)
    usable = df[df.get("event_status", "ok") == "ok"].copy()
    usable = prepare_feature_frame(usable)
    proba = pipeline.predict_proba(usable)[:, 1]
    pred = pipeline.predict(usable)
    usable["predicted_positive_probability"] = proba
    usable["predicted_direction"] = np.where(pred == 1, "up", "down")
    if out_path:
        p = ensure_parent(out_path)
        usable.to_csv(p, index=False)
    return usable


def walk_forward_direction_model(
    event_study_path: str | Path,
    horizon: int = 1,
    min_train: int = 40,
    out_predictions: str | Path | None = None,
    out_report: str | Path | None = None,
) -> dict[str, Any]:
    """Run an expanding-window walk-forward direction model."""
    df = load_event_study(event_study_path)
    frame, y = modeling_frame(df, horizon=horizon)
    if "reaction_start" in frame.columns:
        order = pd.to_datetime(frame["reaction_start"], errors="coerce").sort_values(kind="mergesort").index
    elif "event_time" in frame.columns:
        order = pd.to_datetime(frame["event_time"], errors="coerce").sort_values(kind="mergesort").index
    else:
        order = frame.index
    frame = frame.loc[order].reset_index(drop=True)
    y = y.loc[order].reset_index(drop=True)
    min_train = max(2, int(min_train))
    if len(frame) <= min_train:
        raise ValueError(f"Need more than min_train={min_train} usable events for walk-forward validation")

    rows: list[dict[str, Any]] = []
    for i in range(min_train, len(frame)):
        X_train = frame.iloc[:i].copy()
        y_train = y.iloc[:i].copy()
        X_one = frame.iloc[[i]].copy()
        base_rate = float(np.clip(y_train.mean(), 1e-6, 1.0 - 1e-6))
        if y_train.nunique() < 2:
            proba = base_rate
            pred = int(proba >= 0.5)
            status = "fallback_base_rate_one_class_train"
        else:
            model = make_direction_pipeline(X_train)
            model.fit(X_train, y_train)
            proba = float(model.predict_proba(X_one)[:, 1][0])
            pred = int(proba >= 0.5)
            status = "ok"
        row = frame.iloc[i]
        rows.append(
            {
                "row_number": i,
                "event_id": row.get("event_id", ""),
                "ticker": row.get("ticker", ""),
                "reaction_start": row.get("reaction_start", ""),
                "event_type": row.get("event_type", ""),
                "event_subtype": row.get("event_subtype", ""),
                "y_true": int(y.iloc[i]),
                "actual_positive": int(y.iloc[i]),
                "predicted_positive_probability": proba,
                "predicted_positive": pred,
                "baseline_positive_probability": base_rate,
                "model_status": status,
                f"car_market_model_h{horizon}": row.get(f"car_market_model_h{horizon}", np.nan),
            }
        )
    pred_df = pd.DataFrame(rows)
    y_true = pred_df["y_true"].astype(int)
    proba = pred_df["predicted_positive_probability"].astype(float).to_numpy()
    pred = pred_df["predicted_positive"].astype(int).to_numpy()
    base = np.clip(pred_df["baseline_positive_probability"].astype(float).to_numpy(), 1e-6, 1.0 - 1e-6)
    report: dict[str, Any] = {
        "horizon": horizon,
        "n_events": int(len(frame)),
        "min_train": int(min_train),
        "n_predictions": int(len(pred_df)),
        "categorical_features": available_features(frame)[0],
        "numeric_features": available_features(frame)[1],
        "warnings": ["Walk-forward metrics are a research diagnostic, not evidence of tradable alpha."],
        "metrics": _classification_metrics(y_true, proba, pred),
        "baseline_metrics": {
            "brier_score": float(brier_score_loss(y_true, base)),
            "log_loss": float(log_loss(y_true, base, labels=[0, 1])) if y_true.nunique() == 2 else None,
        },
    }
    if out_predictions:
        p = ensure_parent(out_predictions)
        pred_df.to_csv(p, index=False)
        report["predictions_path"] = str(p)
    if out_report:
        p = ensure_parent(out_report)
        p.write_text(json.dumps(report, indent=2, default=str))
        report["report_path"] = str(p)
    return report


def find_analogs(event_study_path: str | Path, event_id: str, k: int = 5, horizon: int = 1, out_path: str | Path | None = None) -> pd.DataFrame:
    df = load_event_study(event_study_path)
    frame = df[df.get("event_status", "ok") == "ok"].copy().reset_index(drop=True)
    frame = prepare_feature_frame(frame)
    if frame.empty:
        raise ValueError("No ok event-study rows available")
    matches = frame.index[frame["event_id"].astype(str) == str(event_id)].tolist()
    if not matches:
        raise ValueError(f"event_id not found in ok rows: {event_id}")
    idx = matches[0]
    pre = make_preprocessor(frame)
    X = pre.fit_transform(frame)
    n_neighbors = min(k + 1, len(frame))
    nn = NearestNeighbors(n_neighbors=n_neighbors, metric="cosine")
    nn.fit(X)
    distances, indices = nn.kneighbors(X[idx:idx + 1])
    rows = []
    for distance, j in zip(distances[0], indices[0]):
        if int(j) == int(idx):
            continue
        src = frame.iloc[int(j)].copy()
        src["similarity"] = float(1.0 - distance)
        rows.append(src)
        if len(rows) >= k:
            break
    out = pd.DataFrame(rows)
    preferred = [
        "similarity", "event_id", "ticker", "reaction_start", "event_type", "event_subtype", "summary",
        "fundamental_surprise_score", "surprise_direction_inferred", f"car_market_model_h{horizon}",
        f"z_h{horizon}", f"target_direction_h{horizon}", f"significant_95_h{horizon}",
    ]
    cols = [c for c in preferred if c in out.columns] + [c for c in out.columns if c not in preferred]
    out = out[cols]
    if out_path:
        p = ensure_parent(out_path)
        out.to_csv(p, index=False)
    return out
