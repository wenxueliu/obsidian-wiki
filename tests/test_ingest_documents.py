import json
from pathlib import Path

import pytest

from obsidian_wiki.ingest_documents import (
    commit_document,
    plan_ingest_documents,
    read_document,
    run_document_sessions,
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


def test_session_retry_skips_documents_already_committed_from_same_plan(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text("# One\n\nbody\n", encoding="utf-8")
    vault = tmp_path / "vault"
    vault.mkdir()
    plan_path = tmp_path / "plan.json"
    context_path = tmp_path / "wiki-context.json"
    context_path.write_text(json.dumps({"vault_path": str(vault)}), encoding="utf-8")
    plan = plan_ingest_documents(source, vault)
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    commit_document(plan_path, plan["documents"][0]["document_id"])

    report = run_document_sessions(
        plan_path, context_path, claude_executable="definitely-not-an-executable"
    )

    assert report["eligible_documents"] == 0
    assert report["unchanged"] == 1
    assert report["failed"] == 0


def test_document_runner_uses_one_fresh_serial_session_per_document(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text("# Many\n\n" + "durable line\n" * 20, encoding="utf-8")
    vault = tmp_path / "vault"
    vault.mkdir()
    plan_path = tmp_path / "plan.json"
    context_path = tmp_path / "wiki-context.json"
    context_path.write_text(json.dumps({"vault_path": str(vault)}), encoding="utf-8")
    plan = plan_ingest_documents(
        source, vault, target_budget=50, min_budget=25, hard_budget=64
    )
    assert len(plan["documents"]) > 1
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    invocations = tmp_path / "invocations.jsonl"
    fake_claude = tmp_path / "fake-claude"
    fake_claude.write_text(
        """#!/usr/bin/env python3
import json
import pathlib
import sys

args = sys.argv[1:]
required = {"-p", "--dangerously-skip-permissions", "--no-session-persistence", "--disallowed-tools", "Agent,Task"}
if not required.issubset(set(args)):
    raise SystemExit(9)
prompt = next(value for value in args if value.startswith("/wiki-ingest-document "))
payload = json.loads(prompt.split(" ", 1)[1])
plan = json.loads(pathlib.Path(payload["plan_path"]).read_text(encoding="utf-8"))
document = next(item for item in plan["documents"] if item["document_id"] == payload["document_id"])
manifest_path = pathlib.Path(plan["vault_path"]) / ".manifest.json"
manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"version": 1}
records = manifest.setdefault("ingest_documents", {})
records[payload["document_id"]] = {
    "status": "complete",
    "source_path": document["source_path"],
    "source_content_hash": document["source_content_hash"],
    "start_byte": document["start_byte"],
    "end_byte": document["end_byte"],
}
manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
with pathlib.Path(INVOCATIONS).open("a", encoding="utf-8") as stream:
    stream.write(json.dumps({"document_id": payload["document_id"], "cwd": str(pathlib.Path.cwd())}) + "\\n")
""".replace("INVOCATIONS", repr(str(invocations))),
        encoding="utf-8",
    )
    fake_claude.chmod(0o755)

    report = run_document_sessions(
        plan_path, context_path, claude_executable=str(fake_claude)
    )

    calls = [json.loads(line) for line in invocations.read_text(encoding="utf-8").splitlines()]
    assert report["complete"] == len(plan["documents"])
    assert report["failed"] == 0
    assert [item["document_id"] for item in calls] == [
        item["document_id"] for item in plan["documents"]
    ]
    assert len({item["cwd"] for item in calls}) == len(calls)


def test_document_runner_rejects_staged_context_before_starting_workers(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text("# One\n\nbody\n", encoding="utf-8")
    vault = tmp_path / "vault"
    vault.mkdir()
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(plan_ingest_documents(source, vault)), encoding="utf-8"
    )
    context_path = tmp_path / "wiki-context.json"
    context_path.write_text(
        json.dumps({
            "vault_path": str(vault),
            "requested_values": {"WIKI_STAGED_WRITES": True},
        }),
        encoding="utf-8",
    )

    with pytest.raises(PipelineContractError, match="require direct write mode"):
        run_document_sessions(plan_path, context_path)
