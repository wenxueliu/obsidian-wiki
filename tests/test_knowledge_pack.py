from __future__ import annotations

import json
from pathlib import Path

import pytest

from obsidian_wiki.cli import scaffold_vault
from obsidian_wiki.knowledge_pack import (
    KnowledgePackContractError,
    active_knowledge_pack,
    iter_content_pages,
    list_knowledge_packs,
    load_knowledge_pack,
)


def test_lists_only_knowledge_pack_contracts() -> None:
    packs = list_knowledge_packs()

    assert set(packs) == {"default", "software-knowledge", "book-knowledge"}
    assert packs["default"].root.name == "default"
    assert packs["default"].root.parent.name == "knowledge-packs"
    assert packs["software-knowledge"].profile["name"] == "software-knowledge"
    assert "decision" in packs["software-knowledge"].profile["knowledge_types"]
    assert packs["book-knowledge"].profile["scope"]["on_mismatch"] == "ask"


def test_scaffold_persists_and_reloads_active_knowledge_pack(tmp_path: Path) -> None:
    vault = tmp_path / "vault"

    assert scaffold_vault(vault, load_knowledge_pack("software-knowledge")) is True

    marker = json.loads((vault / "_meta" / "knowledge-pack.json").read_text())
    assert marker["name"] == "software-knowledge"
    assert marker["profile_sha256"].startswith("sha256:")
    assert active_knowledge_pack(vault, allow_uninitialized=False).name == "software-knowledge"
    assert (vault / "terms").is_dir()
    assert not (vault / "entities").exists()


def test_book_pack_scaffold_has_book_roots(tmp_path: Path) -> None:
    vault = tmp_path / "vault"

    assert scaffold_vault(vault, load_knowledge_pack("book-knowledge")) is True

    assert (vault / "books").is_dir()
    assert (vault / "reading").is_dir()
    assert (vault / "arguments").is_dir()
    assert not (vault / "projects").exists()


def test_initialized_vault_scans_declared_content_roots_only(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    scaffold_vault(vault, load_knowledge_pack("default"))
    (vault / "concepts" / "kept.md").write_text("# Kept\n")
    (vault / "_raw" / "ignored.md").write_text("# Ignored\n")
    (vault / "custom").mkdir()
    (vault / "custom" / "ignored.md").write_text("# Ignored\n")

    assert [path.relative_to(vault).as_posix() for path in iter_content_pages(vault)] == [
        "concepts/kept.md"
    ]


def test_stale_active_knowledge_pack_fails_closed(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    scaffold_vault(vault, load_knowledge_pack("default"))
    marker_path = vault / "_meta" / "knowledge-pack.json"
    marker = json.loads(marker_path.read_text())
    marker["routing_rules_sha256"] = "sha256:stale"
    marker_path.write_text(json.dumps(marker))

    with pytest.raises(KnowledgePackContractError, match="stale"):
        active_knowledge_pack(vault)


def test_stale_knowledge_profile_fails_closed(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    scaffold_vault(vault, load_knowledge_pack("default"))
    marker_path = vault / "_meta" / "knowledge-pack.json"
    marker = json.loads(marker_path.read_text())
    marker["profile_sha256"] = "sha256:stale"
    marker_path.write_text(json.dumps(marker))

    with pytest.raises(KnowledgePackContractError, match="profile_sha256"):
        active_knowledge_pack(vault)


def test_scaffold_can_explicitly_refresh_same_knowledge_pack_marker(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    pack = load_knowledge_pack("default")
    scaffold_vault(vault, pack)
    marker_path = vault / "_meta" / "knowledge-pack.json"
    marker = json.loads(marker_path.read_text())
    marker["profile_sha256"] = "sha256:stale"
    marker_path.write_text(json.dumps(marker))

    with pytest.raises(KnowledgePackContractError, match="stale or different"):
        scaffold_vault(vault, pack)

    assert scaffold_vault(vault, pack, refresh_knowledge_pack_marker=True) is False
    assert active_knowledge_pack(vault, allow_uninitialized=False).name == "default"


def test_scaffold_marker_refresh_cannot_switch_knowledge_packs(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    scaffold_vault(vault, load_knowledge_pack("default"))

    with pytest.raises(KnowledgePackContractError, match="cannot switch Knowledge Packs"):
        scaffold_vault(
            vault,
            load_knowledge_pack("software-knowledge"),
            refresh_knowledge_pack_marker=True,
        )
