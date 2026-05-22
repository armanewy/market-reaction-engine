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
from sklearn.metrics import accuracy_score, balanced_accuracy_score, log_loss, roc_auc_score
from sklearn.neighbors import NearestNeighbors
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .paths import ensure_parent

CATEGORICAL_FEATURES = [
    "ticker",
    "event_type",
    "event_subtype",
    "source_type",
    "release_session",
    "expectedness",
    "surprise_direction",
    "surprise_magnitude",
]

NUMERIC_FEATURES = [
    "materiality",
    "pre_return_5d",
    "pre_return_20d",
    "pre_vol_20d",
    "benchmark_pre_return_20d",
    "benchmark_pre_vol_20d",
    "alpha",
    "beta",
    "residual_vol",
]


def _one_hot_encoder() -> OneHotEncoder:
    try:
        return OneHotEncoder(handle_unknown="ignore", sparse_output=True)
    except TypeError:  # pragma: no cover - older scikit-learn
        return OneHotEncoder(handle_unknown="ignore", sparse=True)


def available_features(df: pd.DataFrame) -> tuple[list[str], list[str]]:
    cat = [c for c in CATEGORICAL_FEATURES if c in df.columns]
    num = [c for c in NUMERIC_FEATURES if c in df.columns]
    return cat, num


def make_preprocessor(df: pd.DataFrame) -> ColumnTransformer:
    cat, num = available_features(df)
    transformers = []
    if cat:
        transformers.append(
            (
                "cat",
                Pipeline(
                    steps=[
                        ("imputer", SimpleImputer(strategy="constant", fill_value="unknown")),
                        ("onehot", _one_hot_encoder()),
                    ]
                ),
                cat,
            )
        )
    if num:
        transformers.append(
            (
                "num",
                Pipeline(steps=[("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler())]),
                num,
            )
        )
    if not transformers:
        raise ValueError("No modeling features are available in this frame")
    return ColumnTransformer(transformers=transformers)


def load_event_study(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "reaction_start" in df.columns:
        df["reaction_start"] = pd.to_datetime(df["reaction_start"], errors="coerce")
    return df


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
    y = clean[target].astype(str).str.lower().map({"true": 1, "false": 0, "1": 1, "0": 0})
    if y.isna().any():
        y = clean[target].astype(bool).astype(int)
    else:
        y = y.astype(int)
    return clean, y


def chronological_split(df: pd.DataFrame, y: pd.Series, test_size: float = 0.3) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
    if "reaction_start" in df.columns:
        order = df["reaction_start"].sort_values(kind="mergesort").index
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
    pre = make_preprocessor(frame)
    model = Pipeline(
        steps=[
            ("preprocessor", pre),
            (
                "classifier",
                LogisticRegression(max_iter=2000, class_weight="balanced", solver="liblinear"),
            ),
        ]
    )

    report: dict[str, Any] = {
        "horizon": horizon,
        "n_events": int(len(frame)),
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "categorical_features": cat,
        "numeric_features": num,
        "target": f"target_positive_h{horizon}",
        "warnings": [],
    }

    if len(frame) < 30:
        report["warnings"].append(
            "Very small sample. Treat metrics as a plumbing check, not evidence of predictive edge."
        )
    if y.nunique() < 2:
        raise ValueError("Target has only one class; cannot train a direction classifier")
    if y_train.nunique() < 2:
        # Logistic regression cannot train on one class. Fall back to fitting on all data
        # and skip honest test metrics.
        report["warnings"].append(
            "Chronological train split had one class; fitted on full data and skipped out-of-sample metrics."
        )
        model.fit(frame, y)
        report["metrics"] = {}
    else:
        model.fit(X_train, y_train)
        metrics: dict[str, Any] = {}
        if len(X_test) > 0:
            pred = model.predict(X_test)
            metrics["accuracy"] = float(accuracy_score(y_test, pred))
            metrics["balanced_accuracy"] = float(balanced_accuracy_score(y_test, pred))
            if hasattr(model, "predict_proba") and y_test.nunique() == 2:
                proba = model.predict_proba(X_test)[:, 1]
                metrics["roc_auc"] = float(roc_auc_score(y_test, proba))
                metrics["log_loss"] = float(log_loss(y_test, proba, labels=[0, 1]))
            else:
                report["warnings"].append("Test set had one class; ROC/log-loss skipped.")
        report["metrics"] = metrics

    if out_model:
        p = ensure_parent(out_model)
        joblib.dump(
            {
                "pipeline": model,
                "horizon": horizon,
                "categorical_features": cat,
                "numeric_features": num,
                "target": f"target_positive_h{horizon}",
            },
            p,
        )
        report["model_path"] = str(p)
    if out_report:
        p = ensure_parent(out_report)
        p.write_text(json.dumps(report, indent=2, default=str))
        report["report_path"] = str(p)
    return report


def predict_direction(
    model_path: str | Path,
    event_study_path: str | Path,
    out_path: str | Path | None = None,
) -> pd.DataFrame:
    bundle = joblib.load(model_path)
    pipeline = bundle["pipeline"]
    df = load_event_study(event_study_path)
    usable = df[df.get("event_status", "ok") == "ok"].copy()
    proba = pipeline.predict_proba(usable)[:, 1]
    pred = pipeline.predict(usable)
    usable["predicted_positive_probability"] = proba
    usable["predicted_direction"] = np.where(pred == 1, "up", "down")
    if out_path:
        p = ensure_parent(out_path)
        usable.to_csv(p, index=False)
    return usable


def find_analogs(
    event_study_path: str | Path,
    event_id: str,
    k: int = 5,
    horizon: int = 1,
    out_path: str | Path | None = None,
) -> pd.DataFrame:
    df = load_event_study(event_study_path)
    frame = df[df.get("event_status", "ok") == "ok"].copy().reset_index(drop=True)
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
        "similarity",
        "event_id",
        "ticker",
        "reaction_start",
        "event_type",
        "event_subtype",
        "summary",
        f"car_market_model_h{horizon}",
        f"z_h{horizon}",
        f"target_direction_h{horizon}",
        f"significant_95_h{horizon}",
    ]
    cols = [c for c in preferred if c in out.columns] + [c for c in out.columns if c not in preferred]
    out = out[cols]
    if out_path:
        p = ensure_parent(out_path)
        out.to_csv(p, index=False)
    return out
