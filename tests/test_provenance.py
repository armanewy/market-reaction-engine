from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from mre import provenance
from mre.provenance import build_run_manifest, collect_git_sha, file_sha256, json_sha256, write_run_manifest


def test_file_sha256_matches_hashlib(tmp_path: Path):
    path = tmp_path / "input.csv"
    path.write_text("ticker,event_time\nABC,2024-01-01\n", encoding="utf-8")

    assert file_sha256(path) == hashlib.sha256(path.read_bytes()).hexdigest()


def test_file_sha256_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        file_sha256(tmp_path / "missing.csv")


def test_json_sha256_is_deterministic_for_key_order():
    left = {"b": [2, 1], "a": {"z": True, "path": Path("data/events.csv")}}
    right = {"a": {"path": Path("data/events.csv"), "z": True}, "b": [2, 1]}

    assert json_sha256(left) == json_sha256(right)


def test_collect_git_sha_returns_none_when_git_unavailable(monkeypatch):
    def missing_git(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(provenance.subprocess, "run", missing_git)

    assert collect_git_sha() is None


def test_collect_git_sha_returns_none_on_non_git_directory(monkeypatch):
    result = subprocess.CompletedProcess(args=["git"], returncode=128, stdout="", stderr="not a repo")

    monkeypatch.setattr(provenance.subprocess, "run", lambda *args, **kwargs: result)

    assert collect_git_sha() is None


def test_build_run_manifest_hashes_inputs_and_records_missing(tmp_path: Path, monkeypatch):
    input_path = tmp_path / "events.csv"
    missing_path = tmp_path / "missing.csv"
    input_path.write_text("event_id,ticker\ne1,ABC\n", encoding="utf-8")
    monkeypatch.setattr(provenance, "collect_git_sha", lambda repo_root=None: "abc123")

    manifest = build_run_manifest(
        {"domain": "earnings_guidance", "thresholds": {"min_rows": 80}},
        [input_path, missing_path],
        extra={"created_at": "2026-05-25T09:00:00Z"},
    )

    assert manifest["git_sha"] == "abc123"
    assert manifest["package_version"]
    assert manifest["python_version"]
    assert manifest["config_hash"] == json_sha256({"domain": "earnings_guidance", "thresholds": {"min_rows": 80}})
    assert manifest["input_file_hashes"] == {str(input_path): file_sha256(input_path)}
    assert manifest["missing_input_paths"] == [str(missing_path)]
    assert manifest["extra"] == {"created_at": "2026-05-25T09:00:00Z"}
    json.dumps(manifest)


def test_write_run_manifest_writes_stable_json(tmp_path: Path):
    out = tmp_path / "nested" / "manifest.json"
    manifest = {"b": 2, "a": {"z": 1}}

    written = write_run_manifest(out, manifest)

    assert written == out
    assert json.loads(out.read_text(encoding="utf-8")) == manifest
    assert out.read_text(encoding="utf-8") == '{"a":{"z":1},"b":2}\n'
