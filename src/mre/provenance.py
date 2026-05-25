from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from pathlib import Path
from typing import Any

from . import __version__
from .paths import ensure_parent


def file_sha256(path: str | Path) -> str:
    """Return the SHA-256 digest for a local file."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)
    if not p.is_file():
        raise IsADirectoryError(p)

    digest = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_json_default)


def json_sha256(obj: Any) -> str:
    """Return a deterministic SHA-256 digest for a JSON-serializable object."""
    return hashlib.sha256(_canonical_json(obj).encode("utf-8")).hexdigest()


def collect_git_sha(repo_root: Path | None = None) -> str | None:
    """Return the current git commit SHA, or None outside git / without git."""
    cwd = Path(repo_root) if repo_root is not None else None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None


def build_run_manifest(
    config: dict,
    input_paths: list[str | Path],
    extra: dict | None = None,
) -> dict:
    """Build a deterministic run manifest without writing it to disk."""
    input_file_hashes: dict[str, str] = {}
    missing_input_paths: list[str] = []
    for raw_path in input_paths:
        path = Path(raw_path)
        key = str(path)
        try:
            input_file_hashes[key] = file_sha256(path)
        except FileNotFoundError:
            missing_input_paths.append(key)

    manifest = {
        "git_sha": collect_git_sha(),
        "package_version": __version__,
        "python_version": platform.python_version(),
        "config_hash": json_sha256(config),
        "input_file_hashes": input_file_hashes,
        "missing_input_paths": missing_input_paths,
    }
    if extra:
        manifest["extra"] = extra
    return manifest


def write_run_manifest(path: str | Path, manifest: dict) -> Path:
    """Write a manifest as stable, sorted JSON and return its path."""
    out = ensure_parent(path)
    out.write_text(_canonical_json(manifest) + "\n", encoding="utf-8")
    return out
