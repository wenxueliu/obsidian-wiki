"""Behavior tests for wiki-ingest's platform-independent hash fallback."""

import hashlib
import subprocess
import sys
from pathlib import Path

from obsidian_wiki.cache import compute_hash


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / ".skills" / "wiki-ingest" / "scripts" / "hash_source.py"


def run_hash(source: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(source)],
        capture_output=True,
        text=True,
    )


def test_hashes_file_with_sha256_prefix(tmp_path):
    source = tmp_path / "文档.md"
    content = b"content\n"
    source.write_bytes(content)

    result = run_hash(source)

    assert result.returncode == 0
    assert result.stdout.strip() == f"sha256:{hashlib.sha256(content).hexdigest()}"


def test_directory_hash_is_stable_and_changes_with_content(tmp_path):
    source = tmp_path / "source"
    (source / "nested").mkdir(parents=True)
    (source / "a.md").write_text("alpha", encoding="utf-8")
    nested = source / "nested" / "b.md"
    nested.write_text("beta", encoding="utf-8")

    first = run_hash(source)
    second = run_hash(source)
    nested.write_text("changed", encoding="utf-8")
    changed = run_hash(source)

    assert first.returncode == second.returncode == changed.returncode == 0
    assert first.stdout == second.stdout
    assert first.stdout != changed.stdout
    assert changed.stdout.strip() == f"sha256:{compute_hash(source)}"


def test_missing_source_fails(tmp_path):
    result = run_hash(tmp_path / "missing.md")

    assert result.returncode == 1
    assert "source does not exist" in result.stderr
