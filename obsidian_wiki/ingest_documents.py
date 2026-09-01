"""Lightweight, manifest-backed text ingestion documents.

Every supported source is deterministically normalized into one or more
independently processable documents.  The module deliberately has no Job,
unit-state, or Packet model: a document is either absent from the permanent
manifest or complete in it.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from obsidian_wiki.ingest_pipeline import PipelineContractError, discover_sources
from obsidian_wiki.text_chunker import (
    CHUNKER_VERSION,
    ChunkUnit,
    TextChunkError,
    plan_text_chunks,
    read_text_chunk,
)


DOCUMENT_PLAN_VERSION = 1
MANIFEST_KEY = "ingest_documents"


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PipelineContractError(f"cannot read JSON object {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PipelineContractError(f"expected JSON object: {path}")
    return value


def _load_manifest(vault: Path) -> dict[str, Any]:
    path = vault / ".manifest.json"
    if not path.exists():
        return {}
    return _load_json_object(path)


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _document_id(source_path: str, unit_id: str) -> str:
    identity = f"{Path(source_path).resolve()}\0{unit_id}".encode("utf-8")
    return f"doc-{hashlib.sha256(identity).hexdigest()}"


def _manifest_documents(vault: Path) -> dict[str, dict[str, Any]]:
    raw = _load_manifest(vault).get(MANIFEST_KEY, {})
    if not isinstance(raw, dict):
        return {}
    return {key: value for key, value in raw.items() if isinstance(value, dict)}


def _is_completed(document: dict[str, Any], prior: dict[str, Any] | None) -> bool:
    return bool(
        prior is not None
        and prior.get("status") == "complete"
        and prior.get("source_path") == document.get("source_path")
        and prior.get("source_content_hash") == document.get("source_content_hash")
        and prior.get("start_byte") == document.get("start_byte")
        and prior.get("end_byte") == document.get("end_byte")
    )


def plan_ingest_documents(
    source_root: Path,
    vault: Path,
    *,
    target_budget: int = 48_000,
    hard_budget: int = 64_000,
    min_budget: int | None = None,
    chunk_strategy: str = "adaptive_sections",
    strategy_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a deterministic lightweight plan without writing vault state."""
    root = Path(source_root).expanduser().resolve()
    resolved_vault = Path(vault).expanduser().resolve()
    completed = _manifest_documents(resolved_vault)
    documents: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []

    for classified in discover_sources(root):
        path = Path(classified["path"]).resolve()
        if not classified["supported"]:
            sources.append({
                "path": str(path),
                "kind": classified["kind"],
                "status": "unsupported",
                "reason": classified["reason"],
                "documents_total": 0,
            })
            continue
        try:
            chunk_plan = plan_text_chunks(
                path,
                target_budget=target_budget,
                hard_budget=hard_budget,
                min_budget=min_budget,
                chunk_strategy=chunk_strategy,
                strategy_options=strategy_options,
            )
        except (OSError, TextChunkError) as exc:
            sources.append({
                "path": str(path), "kind": classified["kind"],
                "status": "failed", "reason": str(exc), "documents_total": 0,
            })
            continue

        source_documents: list[str] = []
        for index, unit in enumerate(chunk_plan.units):
            document_id = _document_id(chunk_plan.source_path, unit.unit_id)
            record = {
                "document_id": document_id,
                "document_index": index,
                "source_path": chunk_plan.source_path,
                "source_content_hash": chunk_plan.content_hash,
                "chunker_version": chunk_plan.chunker_version,
                "budget": chunk_plan.to_dict()["budget"],
                "chunking": chunk_plan.to_dict()["chunking"],
                **unit.to_dict(),
            }
            record["status"] = (
                "unchanged" if _is_completed(record, completed.get(document_id)) else "pending"
            )
            documents.append(record)
            source_documents.append(document_id)

        sources.append({
            "path": chunk_plan.source_path,
            "kind": classified["kind"],
            "content_hash": chunk_plan.content_hash,
            "status": "empty" if not source_documents else "planned",
            "documents_total": len(source_documents),
            "document_ids": source_documents,
        })

    pending = sum(item["status"] == "pending" for item in documents)
    unchanged = sum(item["status"] == "unchanged" for item in documents)
    return {
        "document_plan_version": DOCUMENT_PLAN_VERSION,
        "source_root": str(root),
        "vault_path": str(resolved_vault),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "sources": sources,
        "documents": documents,
        "counts": {
            "sources": len(sources),
            "documents": len(documents),
            "pending": pending,
            "unchanged": unchanged,
        },
    }


def load_document(plan_path: Path, document_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load and validate one document binding from a serialized plan."""
    plan = _load_json_object(Path(plan_path).expanduser().resolve())
    if plan.get("document_plan_version") != DOCUMENT_PLAN_VERSION:
        raise PipelineContractError("unsupported ingest-document plan version")
    matches = [
        item for item in plan.get("documents", [])
        if isinstance(item, dict) and item.get("document_id") == document_id
    ]
    if len(matches) != 1:
        raise PipelineContractError(f"plan must contain exactly one document {document_id}")
    document = matches[0]
    expected_id = _document_id(str(document.get("source_path")), str(document.get("unit_id")))
    if expected_id != document_id:
        raise PipelineContractError("ingest-document identity does not match its source binding")
    return plan, document


def read_document(plan_path: Path, document_id: str) -> str:
    """Read exactly one planned document after verifying the whole source hash."""
    _plan, document = load_document(plan_path, document_id)
    unit = ChunkUnit.from_dict(document, source_hash=str(document["source_content_hash"]))
    return read_text_chunk(Path(document["source_path"]), unit)


def commit_document(
    plan_path: Path,
    document_id: str,
    *,
    pages_created: list[str] | None = None,
    pages_updated: list[str] | None = None,
) -> dict[str, Any]:
    """Atomically mark one successfully integrated document complete."""
    plan, document = load_document(plan_path, document_id)
    content = read_document(plan_path, document_id)
    created = list(dict.fromkeys(pages_created or []))
    updated = list(dict.fromkeys(pages_updated or []))
    pages = list(dict.fromkeys(created + updated))
    vault = Path(plan["vault_path"]).expanduser().resolve()
    for raw_page in pages:
        page = Path(raw_page)
        if page.is_absolute() or page.suffix.lower() != ".md":
            raise PipelineContractError(f"document page must be a vault-relative Markdown path: {raw_page}")
        resolved_page = (vault / page).resolve()
        try:
            resolved_page.relative_to(vault)
        except ValueError as exc:
            raise PipelineContractError(f"document page escapes the vault: {raw_page}") from exc
        if not resolved_page.is_file():
            raise PipelineContractError(f"document page does not exist: {raw_page}")
    manifest = _load_manifest(vault)
    manifest.setdefault("version", 1)
    records = manifest.get(MANIFEST_KEY)
    if not isinstance(records, dict):
        records = {}
    records[document_id] = {
        "status": "complete",
        "source_path": document["source_path"],
        "source_content_hash": document["source_content_hash"],
        "document_hash": f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()}",
        "document_index": document["document_index"],
        "unit_id": document["unit_id"],
        "start_line": document["start_line"],
        "end_line": document["end_line"],
        "start_byte": document["start_byte"],
        "end_byte": document["end_byte"],
        "heading_path": document.get("heading_path", []),
        "chunker_version": document.get("chunker_version", CHUNKER_VERSION),
        "budget": document["budget"],
        "chunking": document["chunking"],
        "pages_created": created,
        "pages_updated": updated,
        "pages_produced": pages,
        "last_ingested": datetime.now(timezone.utc).isoformat(),
    }
    manifest[MANIFEST_KEY] = records
    _atomic_write_json(vault / ".manifest.json", manifest)
    return {
        "document_id": document_id,
        "status": "complete",
        "manifest_path": str(vault / ".manifest.json"),
        "pages_created": created,
        "pages_updated": updated,
        "pages_produced": pages,
    }


def _bundled_document_skill() -> Path:
    package_dir = Path(__file__).resolve().parent
    for candidate in (
        package_dir / "_data" / "skills" / "wiki-ingest-document",
        package_dir.parent / ".skills" / "wiki-ingest-document",
    ):
        if (candidate / "SKILL.md").is_file():
            return candidate.resolve()
    raise PipelineContractError("bundled wiki-ingest-document skill is missing")


def run_document_sessions(
    plan_path: Path,
    context_path: Path,
    *,
    claude_executable: str = "claude",
    timeout_seconds: int = 3600,
) -> dict[str, Any]:
    """Run every pending document in a fresh, serialized Claude session."""
    if timeout_seconds <= 0:
        raise PipelineContractError("timeout_seconds must be positive")
    resolved_plan = Path(plan_path).expanduser().resolve()
    resolved_context = Path(context_path).expanduser().resolve()
    plan = _load_json_object(resolved_plan)
    if plan.get("document_plan_version") != DOCUMENT_PLAN_VERSION:
        raise PipelineContractError("unsupported ingest-document plan version")
    context = _load_json_object(resolved_context)
    context_vault = context.get("vault_path")
    if not isinstance(context_vault, str) or not context_vault.strip():
        raise PipelineContractError("wiki context has no canonical vault_path")
    vault = Path(plan["vault_path"]).expanduser().resolve()
    if Path(context_vault).expanduser().resolve() != vault:
        raise PipelineContractError("document plan vault does not match wiki context")
    requested = context.get("requested_values", {})
    staged = requested.get("WIKI_STAGED_WRITES", False) if isinstance(requested, dict) else False
    if staged is True or (isinstance(staged, str) and staged.strip().lower() in {"1", "true", "yes", "on"}):
        raise PipelineContractError("lightweight ingest documents require direct write mode")
    skill_dir = _bundled_document_skill()
    reports: list[dict[str, Any]] = []

    for document in plan.get("documents", []):
        if not isinstance(document, dict) or document.get("status") != "pending":
            continue
        document_id = str(document.get("document_id", ""))
        if _is_completed(document, _manifest_documents(vault).get(document_id)):
            reports.append({
                "document_id": document_id,
                "status": "unchanged",
                "reason": "complete manifest record already exists",
            })
            continue
        with tempfile.TemporaryDirectory(prefix=f"wiki-ingest-{document_id[:16]}-") as raw_dir:
            worker_dir = Path(raw_dir)
            skills = worker_dir / ".claude" / "skills"
            skills.mkdir(parents=True)
            target = skills / "wiki-ingest-document"
            try:
                target.symlink_to(skill_dir, target_is_directory=True)
            except OSError:
                shutil.copytree(skill_dir, target)
            prompt = "/wiki-ingest-document " + json.dumps(
                {
                    "plan_path": str(resolved_plan),
                    "document_id": document_id,
                    "wiki_context_path": str(resolved_context),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            command = [
                claude_executable,
                "-p",
                "--dangerously-skip-permissions",
                "--no-session-persistence",
                "--disallowed-tools",
                "Agent,Task",
                "--output-format",
                "json",
                prompt,
            ]
            try:
                completed = subprocess.run(
                    command,
                    cwd=worker_dir,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=timeout_seconds,
                )
                returncode = completed.returncode
                error = None if returncode == 0 else f"claude exited {returncode}"
            except subprocess.TimeoutExpired:
                returncode = 124
                error = f"claude timed out after {timeout_seconds}s"
            except OSError as exc:
                returncode = 127
                error = f"cannot start claude: {exc}"

        committed = _is_completed(document, _manifest_documents(vault).get(document_id))
        if returncode == 0 and not committed:
            error = "worker exited successfully without committing the document"
        reports.append({
            "document_id": document_id,
            "status": "complete" if committed else "failed",
            "returncode": returncode,
            **({"error": error} if error else {}),
        })

    complete = sum(item["status"] == "complete" for item in reports)
    unchanged = sum(item["status"] == "unchanged" for item in reports)
    failed = sum(item["status"] == "failed" for item in reports)
    return {
        "session_backend": "claude-print",
        "session_isolation": "fresh-per-document",
        "serialized_writes": True,
        "considered_documents": len(reports),
        "eligible_documents": complete + failed,
        "complete": complete,
        "unchanged": unchanged,
        "failed": failed,
        "documents": reports,
    }
