import json
from pathlib import Path

import pytest

from obsidian_wiki.ingest_documents import (
    commit_document,
    plan_ingest_documents,
    read_document,
)
from obsidian_wiki.ingest_pipeline import PipelineContractError
from obsidian_wiki.text_chunker import SourceChangedError


def test_small_and_large_sources_share_one_document_model(tmp_path: Path) -> None:
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    small = source_dir / "small.md"
    small.write_text("# Small\n\none paragraph\n", encoding="utf-8")
    large = source_dir / "large.md"
    large.write_text("# Large\n\n" + "durable knowledge line\n" * 20, encoding="utf-8")
    vault = tmp_path / "vault"
    vault.mkdir()

    plan = plan_ingest_documents(
        source_dir, vault, target_budget=64, min_budget=32, hard_budget=80
    )

    by_source: dict[str, list[dict]] = {}
    for document in plan["documents"]:
        by_source.setdefault(document["source_path"], []).append(document)
    assert len(by_source[str(small.resolve())]) == 1
    assert len(by_source[str(large.resolve())]) > 1
    assert {item["status"] for item in plan["documents"]} == {"pending"}


def test_completed_document_is_skipped_by_the_next_plan(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text("# One\n\nbody\n", encoding="utf-8")
    vault = tmp_path / "vault"
    vault.mkdir()
    plan_path = tmp_path / "plan.json"
    plan = plan_ingest_documents(source, vault)
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    document = plan["documents"][0]
    page = vault / "concepts" / "one.md"
    page.parent.mkdir()
    page.write_text("# One\n", encoding="utf-8")

    result = commit_document(
        plan_path,
        document["document_id"],
        pages_created=["concepts/one.md", "concepts/one.md"],
    )

    assert result["status"] == "complete"
    manifest = json.loads((vault / ".manifest.json").read_text(encoding="utf-8"))
    stored = manifest["ingest_documents"][document["document_id"]]
    assert stored["pages_produced"] == ["concepts/one.md"]
    repeated = plan_ingest_documents(source, vault)
    assert repeated["counts"] == {
        "sources": 1, "documents": 1, "pending": 0, "unchanged": 1,
    }
    assert repeated["documents"][0]["status"] == "unchanged"


def test_document_read_and_commit_fail_if_source_changed(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text("# One\n\nbody\n", encoding="utf-8")
    vault = tmp_path / "vault"
    vault.mkdir()
    plan_path = tmp_path / "plan.json"
    plan = plan_ingest_documents(source, vault)
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    document_id = plan["documents"][0]["document_id"]
    assert read_document(plan_path, document_id) == "# One\n\nbody\n"

    source.write_text("# One\n\nchanged\n", encoding="utf-8")

    with pytest.raises(SourceChangedError):
        read_document(plan_path, document_id)
    with pytest.raises(SourceChangedError):
        commit_document(plan_path, document_id)
    assert not (vault / ".manifest.json").exists()
