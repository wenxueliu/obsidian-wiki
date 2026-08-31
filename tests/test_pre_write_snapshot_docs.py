"""Contract tests for destructive-skill pre-write snapshots."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATHS = (
    "workflows/cross-linker.yaml",
    ".skills/wiki-dedup/SKILL.md",
    "workflows/wiki-lint-consolidate.yaml",
)


def _contract_texts() -> list[tuple[str, str]]:
    return [
        (path, (ROOT / path).read_text(encoding="utf-8"))
        for path in CONTRACT_PATHS
    ]


def test_snapshot_only_runs_for_standalone_vault_repositories() -> None:
    for path, text in _contract_texts():
        assert "rev-parse --show-toplevel" in text or "vault 是否自身就是 Git root" in text, path
        assert "standalone" in text or "更大 repo 的子目录" in text, path


def test_snapshot_distinguishes_clean_repository_from_commit_failure() -> None:
    for path, text in _contract_texts():
        if path.endswith("wiki-dedup/SKILL.md"):
            assert "diff --quiet" in text, path
            assert "diff --cached --quiet" in text, path
        else:
            assert "clean" in text and "dirty" in text, path
        assert "git add -A" in text, path
        assert "snapshot" in text, path
        assert (
            "写入前停止" in text
            or "首次 vault 编辑前停止" in text
            or "without writing any vault files" in text
        ), path


def test_snapshot_records_an_actionable_rollback_point() -> None:
    for path, text in _contract_texts():
        assert "snapshot SHA" in text or "SNAPSHOT_SHA=" in text, path
        if path.endswith("wiki-dedup/SKILL.md"):
            assert 'reset --hard "$SNAPSHOT_SHA"' in text, path
            assert "clean -fd" in text, path
        else:
            assert "rollback" in text.lower() or "回滚" in text or "恢复 SHA" in text, path
