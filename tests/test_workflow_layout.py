from __future__ import annotations

import json
from pathlib import Path

import pytest

from obsidian_wiki.cli import scaffold_vault
from obsidian_wiki.workflow_layout import (
    LayoutContractError,
    active_layout,
    iter_content_pages,
    list_layouts,
    load_layout,
)


def test_lists_only_workflow_layout_contracts() -> None:
    layouts = list_layouts()

    assert set(layouts) == {"default", "software-knowledge"}
    assert layouts["default"].root.name == "default"


def test_scaffold_persists_and_reloads_active_layout(tmp_path: Path) -> None:
    vault = tmp_path / "vault"

    assert scaffold_vault(vault, load_layout("software-knowledge")) is True

    marker = json.loads((vault / "_meta" / "layout.json").read_text())
    assert marker["name"] == "software-knowledge"
    assert active_layout(vault, allow_uninitialized=False).name == "software-knowledge"
    assert (vault / "terms").is_dir()
    assert not (vault / "entities").exists()


def test_initialized_vault_scans_declared_content_roots_only(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    scaffold_vault(vault, load_layout("default"))
    (vault / "concepts" / "kept.md").write_text("# Kept\n")
    (vault / "_raw" / "ignored.md").write_text("# Ignored\n")
    (vault / "custom").mkdir()
    (vault / "custom" / "ignored.md").write_text("# Ignored\n")

    assert [path.relative_to(vault).as_posix() for path in iter_content_pages(vault)] == [
        "concepts/kept.md"
    ]


def test_stale_active_layout_fails_closed(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    scaffold_vault(vault, load_layout("default"))
    marker_path = vault / "_meta" / "layout.json"
    marker = json.loads(marker_path.read_text())
    marker["routing_rules_sha256"] = "sha256:stale"
    marker_path.write_text(json.dumps(marker))

    with pytest.raises(LayoutContractError, match="stale"):
        active_layout(vault)
