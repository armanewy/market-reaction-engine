from __future__ import annotations

import pandas as pd

from mre.timestamp_readiness import classify_release_session_readiness, classify_release_session_readiness_frame


def test_before_open_after_close_and_intraday_are_ok():
    for session in ["before_open", "after_close", "intraday"]:
        result = classify_release_session_readiness(
            {
                "release_session": session,
                "release_time_status": "exact",
                "release_time_confidence": "high",
                "release_time_source_type": "primary_source",
                "timestamp_audit_status": "clear",
                "first_realistic_entry": "next_open",
            }
        )

        assert result["timestamp_readiness_status"] == "ok"
        assert result["timestamp_readiness_issues"] == ""
        assert result["explanatory_only"] is False


def test_unknown_session_is_not_execution_ready():
    result = classify_release_session_readiness({"release_session": "unknown"})

    assert result["timestamp_readiness_status"] == "fail"
    assert "unknown_release_session" in result["timestamp_readiness_issues"]
    assert result["explanatory_only"] is True


def test_missing_session_is_not_execution_ready():
    result = classify_release_session_readiness({})

    assert result["timestamp_readiness_status"] == "fail"
    assert "missing_release_session" in result["timestamp_readiness_issues"]
    assert result["explanatory_only"] is True


def test_timestamp_audit_failure_overrides_known_session():
    result = classify_release_session_readiness({"release_session": "after_close", "timestamp_audit_status": "needs_timestamp_review"})

    assert result["timestamp_readiness_status"] == "fail"
    assert "timestamp_audit_not_clear" in result["timestamp_readiness_issues"]
    assert result["explanatory_only"] is True


def test_low_confidence_release_time_is_warning_not_fail():
    result = classify_release_session_readiness(
        {
            "release_session": "intraday",
            "release_time_status": "exact",
            "release_time_confidence": "low",
        }
    )

    assert result["timestamp_readiness_status"] == "warning"
    assert "release_time_confidence_low:low" in result["timestamp_readiness_issues"]
    assert result["explanatory_only"] is False


def test_post_event_source_type_fails_point_in_time_readiness():
    result = classify_release_session_readiness(
        {
            "release_session": "before_open",
            "release_time_source_type": "price_reaction",
        }
    )

    assert result["timestamp_readiness_status"] == "fail"
    assert "release_time_source_not_point_in_time" in result["timestamp_readiness_issues"]


def test_frame_helper_adds_readiness_columns():
    frame = pd.DataFrame(
        [
            {"event_id": "e1", "release_session": "after_close", "timestamp_audit_status": "clear"},
            {"event_id": "e2", "release_session": "unknown", "timestamp_audit_status": "clear"},
        ]
    )

    out = classify_release_session_readiness_frame(frame)

    assert list(out["timestamp_readiness_status"]) == ["ok", "fail"]
    assert bool(out.loc[1, "explanatory_only"]) is True
