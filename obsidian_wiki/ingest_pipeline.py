"""Minimal V1 contracts for resumable text-ingest jobs and packets.

This module contains deterministic coordinator infrastructure only. Knowledge
extraction and wiki-page integration remain agent-skill responsibilities.
"""

from __future__ import annotations

import codecs
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from obsidian_wiki.batch import SKIP_DIRS
from obsidian_wiki.cache import compute_hash
from obsidian_wiki.text_chunker import (
    CHUNKER_VERSION,
    DEFAULT_CHUNK_STRATEGY,
    DEFAULT_HARD_BUDGET,
    DEFAULT_TARGET_BUDGET,
    SUPPORTED_EXTENSIONS,
    normalize_chunk_settings,
    plan_text_chunks,
    unit_for_range,
)


JOB_VERSION = 1
PACKET_VERSION = 1
JOBS_RELATIVE_DIR = Path("_meta") / "ingest-jobs"
DEFAULT_DIRECT_EXTRACT_MAX_BYTES = 16_000

_KIND_BY_EXTENSION = {
    ".md": "markdown", ".markdown": "markdown", ".mdx": "markdown",
    ".txt": "plain_text", ".rst": "restructured_text",
    ".pdf": "pdf",
    ".doc": "office", ".docx": "office", ".ppt": "office", ".pptx": "office",
    ".xls": "office", ".xlsx": "office", ".odt": "office", ".ods": "office",
    ".odp": "office",
    ".json": "structured_data", ".jsonl": "structured_data", ".csv": "structured_data",
    ".tsv": "structured_data", ".xml": "structured_data", ".yaml": "structured_data",
    ".yml": "structured_data",
    ".html": "html", ".htm": "html",
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".gif": "image",
    ".webp": "image", ".svg": "image",
    ".mp3": "audio", ".wav": "audio", ".m4a": "audio",
    ".mp4": "video", ".mov": "video", ".webm": "video",
    ".zip": "archive", ".tar": "archive", ".gz": "archive", ".bz2": "archive",
    ".7z": "archive", ".rar": "archive",
    ".py": "source_code", ".js": "source_code", ".ts": "source_code",
    ".tsx": "source_code", ".jsx": "source_code", ".go": "source_code",
    ".rs": "source_code", ".java": "source_code", ".c": "source_code",
    ".cpp": "source_code", ".h": "source_code", ".sh": "source_code",
    ".log": "log",
}

_REASONS = {
    "pdf": "PDF processing is not available in text ingest V1",
    "office": "Office and OpenDocument processing is not available in text ingest V1",
    "structured_data": "Structured-data processing is not available in text ingest V1",
    "html": "HTML processing is not available in text ingest V1",
    "image": "Image processing is not available in text ingest V1",
    "audio": "Audio processing is not available in text ingest V1",
    "video": "Video processing is not available in text ingest V1",
    "archive": "Archive processing is not available in text ingest V1",
    "source_code": "Source-code processing is not available in text ingest V1",
    "log": "Log processing is not available in text ingest V1",
    "unknown": "File type is not supported by text ingest V1",
}


class PipelineContractError(ValueError):
    """Raised when a Job or Packet violates the V1 contract."""


def classify_source(path: Path) -> dict[str, Any]:
    """Classify a path without reading its body; unsupported files stay visible."""
    path = Path(path)
    extension = path.suffix.lower()
    kind = _KIND_BY_EXTENSION.get(extension, "unknown")
    supported = extension in SUPPORTED_EXTENSIONS
    result: dict[str, Any] = {
        "path": str(path.resolve()),
        "kind": kind,
        "supported": supported,
    }
    if not supported:
        result["reason"] = _REASONS[kind]
    return result


def discover_sources(source_root: Path) -> list[dict[str, Any]]:
    """Discover every file under *source_root* using the established skip dirs."""
    root = Path(source_root).expanduser().resolve()
    if root.is_file():
        return [classify_source(root)]
    if not root.is_dir():
        raise FileNotFoundError(f"source root does not exist: {root}")
    discovered: list[dict[str, Any]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            name for name in dirnames
            if name not in SKIP_DIRS and not name.startswith(".")
        )
        for filename in sorted(filenames):
            discovered.append(classify_source(Path(dirpath) / filename))
    return discovered


def _source_id(path: str) -> str:
    return f"src_{hashlib.sha256(path.encode('utf-8')).hexdigest()[:12]}"


def _job_id(now: datetime, source_root: Path) -> str:
    suffix = hashlib.sha256(
        f"{source_root}\0{now.isoformat()}".encode("utf-8")
    ).hexdigest()[:4]
    return f"{now.strftime('%Y%m%d-%H%M%S')}-{suffix}"


def _manifest_entries(vault: Path) -> Iterator[dict[str, Any]]:
    path = vault / ".manifest.json"
    if not path.is_file():
        return
    try:
        sources = json.loads(path.read_text(encoding="utf-8")).get("sources", {})
    except (OSError, json.JSONDecodeError, AttributeError):
        return
    if isinstance(sources, dict):
        for key, value in sources.items():
            if isinstance(value, dict):
                yield {"path": key, **value}
    elif isinstance(sources, list):
        for value in sources:
            if isinstance(value, dict):
                yield value


def _matching_manifest_entry(vault: Path, source: Path) -> dict[str, Any] | None:
    for entry in _manifest_entries(vault):
        raw = entry.get("path")
        if not isinstance(raw, str):
            continue
        candidate = Path(raw)
        candidate = candidate if candidate.is_absolute() else vault / candidate
        try:
            if candidate.resolve() == source.resolve():
                return entry
        except OSError:
            continue
    return None


def create_job(
    source_root: Path,
    vault: Path,
    *,
    target_budget: int = DEFAULT_TARGET_BUDGET,
    hard_budget: int = DEFAULT_HARD_BUDGET,
    min_budget: int | None = None,
    chunk_strategy: str = DEFAULT_CHUNK_STRATEGY,
    strategy_options: dict[str, Any] | None = None,
    direct_extract_max_bytes: int | None = None,
    write_mode: str = "direct",
    now: datetime | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Create and atomically persist one minimal V1 Job.

    The coordinator records only paths, hashes, range metadata, statuses, and
    artifact paths. Source bodies are never placed in the Job.
    """
    root = Path(source_root).expanduser().resolve()
    vault = Path(vault).expanduser().resolve()
    if write_mode not in {"direct", "staged"}:
        raise PipelineContractError("write_mode must be direct or staged")
    if direct_extract_max_bytes is None:
        direct_extract_max_bytes = min(DEFAULT_DIRECT_EXTRACT_MAX_BYTES, hard_budget)
    if direct_extract_max_bytes < 0:
        raise PipelineContractError("direct_extract_max_bytes must be zero or positive")
    if direct_extract_max_bytes > hard_budget:
        raise PipelineContractError(
            "direct_extract_max_bytes cannot exceed hard_budget"
        )
    timestamp = now or datetime.now(timezone.utc)
    effective_min_budget, chunk_strategy, effective_options = normalize_chunk_settings(
        target_budget=target_budget,
        hard_budget=hard_budget,
        min_budget=min_budget,
        chunk_strategy=chunk_strategy,
        strategy_options=strategy_options,
    )
    expected_budget = {
        "mode": "utf8_bytes", "target": target_budget,
        "hard_max": hard_budget, "min": effective_min_budget,
    }
    expected_chunking = {
        "strategy": chunk_strategy, "options": effective_options,
    }
    job_id = _job_id(timestamp, root)
    job_dir = vault / JOBS_RELATIVE_DIR / job_id
    sources: list[dict[str, Any]] = []

    for classified in discover_sources(root):
        path = Path(classified["path"])
        if not classified["supported"]:
            sources.append({
                "path": classified["path"], "kind": classified["kind"],
                "status": "unsupported", "reason": classified["reason"],
            })
            continue
        content_hash = f"sha256:{compute_hash(path)}"
        existing = _matching_manifest_entry(vault, path)
        existing_hash = str(existing.get("content_hash", "")) if existing else ""
        if existing_hash and ":" not in existing_hash:
            existing_hash = f"sha256:{existing_hash}"
        if (
            existing_hash == content_hash
            and existing is not None
            and existing.get("chunker_version") == CHUNKER_VERSION
            and existing.get("budget") == expected_budget
            and existing.get("chunking") == expected_chunking
        ):
            sources.append({
                "source_id": _source_id(str(path)), "path": str(path),
                "content_hash": content_hash, "kind": classified["kind"],
                "status": "unchanged",
            })
            continue
        try:
            plan = plan_text_chunks(
                path,
                target_budget=target_budget,
                hard_budget=hard_budget,
                min_budget=min_budget,
                chunk_strategy=chunk_strategy,
                strategy_options=effective_options,
            )
        except (OSError, ValueError) as exc:
            sources.append({
                "source_id": _source_id(str(path)), "path": str(path),
                "content_hash": content_hash, "kind": classified["kind"],
                "status": "failed", "reason": str(exc),
            })
            continue
        units = []
        inline = direct_extract_max_bytes > 0 and 0 < plan.size_bytes <= direct_extract_max_bytes
        planned_units = plan.units
        if inline:
            coverage_start = 3 if plan.encoding == "utf-8-sig" else 0
            planned_units = (
                unit_for_range(
                    start_byte=coverage_start,
                    end_byte=plan.size_bytes,
                    expected_hash=plan.content_hash,
                    start_line=1,
                    end_line=max(1, plan.line_count),
                ),
            )
        for unit in planned_units:
            value = unit.to_dict()
            value["status"] = "pending"
            value["transport"] = "inline" if inline else "packet"
            if not inline:
                value["packet_path"] = str(
                    Path("packets") / f"{_source_id(str(path))}-{unit.unit_id}.json"
                )
            units.append(value)
        sources.append({
            "source_id": _source_id(str(path)), "path": str(path),
            "content_hash": content_hash, "kind": classified["kind"],
            "status": "processing" if units else "ready_to_commit",
            "chunker_version": CHUNKER_VERSION,
            "budget": plan.to_dict()["budget"],
            "chunking": plan.to_dict()["chunking"],
            "execution": {"mode": "inline" if inline else "packet"},
            "units": units,
            "chunk_plan": {
                "units_total": len(units), "units_integrated": 0,
                "next_unit": units[0]["unit_id"] if units else None,
            },
            **({"warnings": list(plan.warnings)} if plan.warnings else {}),
        })

    active = any(source["status"] in {"processing", "failed"} for source in sources)
    ready = any(source["status"] == "ready_to_commit" for source in sources)
    job: dict[str, Any] = {
        "job_version": JOB_VERSION,
        "job_id": job_id,
        "source_root": str(root),
        "write_mode": write_mode,
        "execution": {"direct_extract_max_bytes": direct_extract_max_bytes},
        "status": "incomplete" if active else ("ready_to_commit" if ready else "complete"),
        "created_at": timestamp.isoformat(),
        "sources": sources,
    }
    job_dir.mkdir(parents=True, exist_ok=False)
    (job_dir / "packets").mkdir()
    write_job(job_dir, job)
    return job_dir, job


def write_job(job_dir: Path, job: dict[str, Any]) -> None:
    """Validate and atomically replace the coordinator-owned job.json."""
    if job.get("job_version") != JOB_VERSION or not isinstance(job.get("sources"), list):
        raise PipelineContractError("invalid V1 Job")
    directory = Path(job_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "job.json"
    fd, temporary = tempfile.mkstemp(prefix=".job-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(job, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def load_job(job_dir: Path) -> dict[str, Any]:
    """Load and minimally validate one V1 Job."""
    try:
        value = json.loads((Path(job_dir) / "job.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PipelineContractError(f"cannot read Job: {exc}") from exc
    if not isinstance(value, dict) or value.get("job_version") != JOB_VERSION:
        raise PipelineContractError("invalid V1 Job")
    return value


def _job_matches_current_sources(job: dict[str, Any]) -> bool:
    for source in job.get("sources", []):
        expected = source.get("content_hash")
        if not expected:
            continue
        path = Path(str(source.get("path", "")))
        if not path.is_file():
            return False
        actual = f"sha256:{compute_hash(path)}"
        normalised = str(expected) if ":" in str(expected) else f"sha256:{expected}"
        if actual != normalised or source.get("chunker_version") != CHUNKER_VERSION:
            return False
    return True


def find_resumable_job(
    source_root: Path,
    vault: Path,
    *,
    target_budget: int | None = None,
    hard_budget: int | None = None,
    min_budget: int | None = None,
    chunk_strategy: str | None = None,
    strategy_options: dict[str, Any] | None = None,
    direct_extract_max_bytes: int | None = None,
    write_mode: str | None = None,
) -> tuple[Path, dict[str, Any]] | None:
    """Find the newest incomplete, source-compatible Job for one canonical root."""
    root = str(Path(source_root).expanduser().resolve())
    jobs_root = Path(vault).expanduser().resolve() / JOBS_RELATIVE_DIR
    if not jobs_root.is_dir():
        return None
    for job_file in sorted(jobs_root.glob("*/job.json"), reverse=True):
        try:
            job = load_job(job_file.parent)
        except PipelineContractError:
            continue
        if job.get("source_root") != root or job.get("status") not in {
            "incomplete", "ready_to_commit"
        }:
            continue
        if write_mode is not None and job.get("write_mode", "direct") != write_mode:
            continue
        if (
            direct_extract_max_bytes is not None
            and job.get("execution", {}).get("direct_extract_max_bytes", 0)
            != direct_extract_max_bytes
        ):
            continue
        planned_sources = [source for source in job.get("sources", []) if source.get("budget")]
        if target_budget is not None and any(
            source["budget"].get("target") != target_budget for source in planned_sources
        ):
            continue
        if hard_budget is not None and any(
            source["budget"].get("hard_max") != hard_budget for source in planned_sources
        ):
            continue
        if min_budget is not None and any(
            source["budget"].get("min") != min_budget for source in planned_sources
        ):
            continue
        if chunk_strategy is not None and any(
            source.get("chunking", {}).get("strategy") != chunk_strategy
            for source in planned_sources
        ):
            continue
        if strategy_options is not None and any(
            source.get("chunking", {}).get("options", {}) != strategy_options
            for source in planned_sources
        ):
            continue
        if _job_matches_current_sources(job):
            return job_file.parent, job
    return None


def create_or_resume_job(
    source_root: Path,
    vault: Path,
    *,
    target_budget: int = DEFAULT_TARGET_BUDGET,
    hard_budget: int = DEFAULT_HARD_BUDGET,
    min_budget: int | None = None,
    chunk_strategy: str = DEFAULT_CHUNK_STRATEGY,
    strategy_options: dict[str, Any] | None = None,
    direct_extract_max_bytes: int | None = None,
    write_mode: str = "direct",
) -> tuple[Path, dict[str, Any], bool]:
    """Resume a compatible Job, otherwise create a fresh source-version plan.

    The boolean result is true when an existing Job was resumed.
    """
    if write_mode not in {"direct", "staged"}:
        raise PipelineContractError("write_mode must be direct or staged")
    if direct_extract_max_bytes is None:
        direct_extract_max_bytes = min(DEFAULT_DIRECT_EXTRACT_MAX_BYTES, hard_budget)
    if direct_extract_max_bytes < 0:
        raise PipelineContractError("direct_extract_max_bytes must be zero or positive")
    if direct_extract_max_bytes > hard_budget:
        raise PipelineContractError(
            "direct_extract_max_bytes cannot exceed hard_budget"
        )
    effective_min_budget, chunk_strategy, effective_options = normalize_chunk_settings(
        target_budget=target_budget,
        hard_budget=hard_budget,
        min_budget=min_budget,
        chunk_strategy=chunk_strategy,
        strategy_options=strategy_options,
    )
    resumable = find_resumable_job(
        source_root, vault, target_budget=target_budget, hard_budget=hard_budget,
        min_budget=effective_min_budget, chunk_strategy=chunk_strategy,
        strategy_options=effective_options,
        direct_extract_max_bytes=direct_extract_max_bytes,
        write_mode=write_mode,
    )
    if resumable is not None:
        return resumable[0], resumable[1], True
    root = str(Path(source_root).expanduser().resolve())
    jobs_root = Path(vault).expanduser().resolve() / JOBS_RELATIVE_DIR
    if jobs_root.is_dir():
        for job_file in sorted(jobs_root.glob("*/job.json"), reverse=True):
            try:
                previous = load_job(job_file.parent)
            except PipelineContractError:
                continue
            if (
                previous.get("source_root") == root
                and previous.get("status") in {"incomplete", "ready_to_commit"}
            ):
                previous["status"] = "invalidated"
                previous["invalidated_reason"] = (
                    "source path, content hash, chunk settings, chunker version, "
                    "direct extraction threshold, or write mode changed after planning"
                )
                write_job(job_file.parent, previous)
                break
    job_dir, job = create_job(
        source_root, vault, target_budget=target_budget, hard_budget=hard_budget,
        min_budget=effective_min_budget, chunk_strategy=chunk_strategy,
        strategy_options=effective_options,
        direct_extract_max_bytes=direct_extract_max_bytes,
        write_mode=write_mode,
    )
    return job_dir, job, False


def summarize_job(job_dir: Path, job: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a deterministic coordinator summary without reading source bodies."""
    directory = Path(job_dir).expanduser().resolve()
    current = load_job(directory) if job is None else job
    source_counts: dict[str, int] = {}
    sources: list[dict[str, Any]] = []
    units_total = units_integrated = units_staged = 0
    for source in current.get("sources", []):
        status = str(source.get("status", "unknown"))
        source_counts[status] = source_counts.get(status, 0) + 1
        units = source.get("units", [])
        units_total += len(units)
        units_integrated += sum(unit.get("status") == "integrated" for unit in units)
        units_staged += sum(
            unit.get("status") in {"staged", "approved_waiting_order"} for unit in units
        )
        sources.append({
            "source_id": source.get("source_id"),
            "path": source.get("path"),
            "kind": source.get("kind"),
            "status": status,
            "reason": source.get("reason"),
            "units_total": len(units),
            "execution_mode": source.get("execution", {}).get("mode", "packet"),
        })

    pending = next_pending_unit(current)
    next_unit = None
    if pending is not None:
        source, unit = pending
        next_unit = {
            "source_id": source.get("source_id"),
            "source_path": source.get("path"),
            "unit_id": unit.get("unit_id"),
            "transport": unit.get("transport", "packet"),
        }
        if unit.get("transport", "packet") == "packet":
            next_unit["packet_path"] = str(
                resolve_packet_path(directory, unit.get("packet_path", ""))
            )
    complete_statuses = {"complete", "unchanged", "unsupported"}
    live_complete = bool(current.get("sources")) and all(
        source.get("status") in complete_statuses for source in current.get("sources", [])
    )
    return {
        "job_id": current.get("job_id"),
        "job_dir": str(directory),
        "job_path": str(directory / "job.json"),
        "status": current.get("status"),
        "write_mode": current.get("write_mode", "direct"),
        "execution": current.get("execution", {"direct_extract_max_bytes": 0}),
        "source_counts": source_counts,
        "sources": sources,
        "units": {
            "total": units_total,
            "integrated": units_integrated,
            "staged": units_staged,
        },
        "next_unit": next_unit,
        "live_complete": live_complete,
    }


def build_completion_report(
    job_dir: Path, job: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Build a deterministic, read-only completion report for one ingest Job."""
    directory = Path(job_dir).expanduser().resolve()
    current = load_job(directory) if job is None else job
    summary = summarize_job(directory, current)
    vault = directory.parent.parent.parent

    source_paths: dict[str, list[str]] = {}
    unit_counts: dict[str, int] = {}
    failures: list[dict[str, Any]] = []
    manifest_commits: list[dict[str, str]] = []
    exact_manifest_entries: list[dict[str, str]] = []
    missing_manifest_entries: list[str] = []
    next_unit: dict[str, Any] | None = None

    for source in current.get("sources", []):
        source_status = str(source.get("status", "unknown"))
        source_path = str(source.get("path", ""))
        source_paths.setdefault(source_status, []).append(source_path)
        if source_status == "failed":
            failures.append({
                "scope": "source",
                "source_id": source.get("source_id"),
                "path": source_path,
                "reason": source.get("reason") or source.get("error") or "unknown error",
            })

        for unit in source.get("units", []):
            unit_status = str(unit.get("status", "unknown"))
            unit_counts[unit_status] = unit_counts.get(unit_status, 0) + 1
            if next_unit is None and unit_status not in {
                "integrated", "staged", "approved_waiting_order"
            }:
                next_unit = {
                    "source_id": source.get("source_id"),
                    "source_path": source_path,
                    "unit_id": unit.get("unit_id"),
                    "status": unit_status,
                    "transport": unit.get("transport", "packet"),
                }
                if unit.get("transport", "packet") == "packet":
                    next_unit["packet_path"] = str(
                        resolve_packet_path(directory, unit.get("packet_path", ""))
                    )
            if unit_status == "failed":
                failures.append({
                    "scope": "unit",
                    "source_id": source.get("source_id"),
                    "path": source_path,
                    "unit_id": unit.get("unit_id"),
                    "reason": unit.get("reason") or unit.get("error") or "unknown error",
                    **({"attempt": unit["attempt"]} if "attempt" in unit else {}),
                })

        if source_status not in {"complete", "unchanged"} or not source_path:
            continue
        entry = _matching_manifest_entry(vault, Path(source_path))
        expected_hash = str(source.get("content_hash", ""))
        if expected_hash and ":" not in expected_hash:
            expected_hash = f"sha256:{expected_hash}"
        actual_hash = str(entry.get("content_hash", "")) if entry else ""
        if actual_hash and ":" not in actual_hash:
            actual_hash = f"sha256:{actual_hash}"
        if entry is not None and actual_hash == expected_hash:
            exact_entry = {
                "path": source_path,
                "content_hash": expected_hash,
                "source_status": source_status,
            }
            exact_manifest_entries.append(exact_entry)
            if source_status == "complete":
                manifest_commits.append(exact_entry)
        else:
            missing_manifest_entries.append(source_path)

    live_complete = summary["live_complete"] and not missing_manifest_entries
    if next_unit is not None:
        action_by_status = {
            "extracting": "reconcile_extraction",
            "packet_ready": "integrate_unit",
            "review_rejected": "review_rejected_artifact",
            "failed": "retry_failed_unit_or_source",
        }
        next_action = {
            "kind": action_by_status.get(str(next_unit.get("status")), "process_unit"),
            "source_id": next_unit.get("source_id"),
            "unit_id": next_unit.get("unit_id"),
            "transport": next_unit.get("transport"),
        }
    elif any(status in source_paths for status in ("awaiting_review",)) or any(
        status in unit_counts for status in ("staged", "approved_waiting_order")
    ):
        next_action = {"kind": "review_staged_writes"}
    elif any(status in source_paths for status in ("ready_to_commit",)):
        next_action = {"kind": "finalize_sources"}
    elif live_complete:
        next_action = {"kind": "none"}
    elif failures:
        next_action = {"kind": "retry_failed_unit_or_source"}
    else:
        next_action = {"kind": "inspect_incomplete_job"}

    return {
        "report_version": 1,
        "job_id": summary.get("job_id"),
        "job_dir": summary.get("job_dir"),
        "job_path": summary.get("job_path"),
        "status": summary.get("status"),
        "write_mode": summary.get("write_mode"),
        "live_complete": live_complete,
        "source_counts": summary["source_counts"],
        "source_paths": source_paths,
        "unit_counts": unit_counts,
        "units": summary["units"],
        "next_unit": next_unit,
        "next_action": next_action,
        "manifest": {
            "committed": manifest_commits,
            "exact_hash_entries": exact_manifest_entries,
            "missing_for_live_sources": missing_manifest_entries,
        },
        "failures": failures,
        "optional_postprocessing": {
            "cross_linker": {
                "eligible": live_complete,
                "run_by_ingest": False,
            }
        },
    }


def render_completion_report_markdown(report: dict[str, Any]) -> str:
    """Render the human-readable form of :func:`build_completion_report`."""
    lines = [
        "# Folder Ingest Completion",
        "",
        f"- Job: `{report.get('job_path')}`",
        f"- Status: `{report.get('status')}`",
        f"- Write mode: `{report.get('write_mode')}`",
        f"- Live complete: `{'yes' if report.get('live_complete') else 'no'}`",
        "",
        "## Sources",
        "",
    ]
    source_counts = report.get("source_counts", {})
    source_paths = report.get("source_paths", {})
    if not source_counts:
        lines.append("- None")
    for status, count in source_counts.items():
        lines.append(f"- `{status}`: {count}")
        for path in source_paths.get(status, []):
            lines.append(f"  - `{path}`")

    lines.extend(["", "## Units", ""])
    unit_counts = report.get("unit_counts", {})
    if not unit_counts:
        lines.append("- None")
    else:
        for status, count in unit_counts.items():
            lines.append(f"- `{status}`: {count}")

    lines.extend(["", "## Manifest", ""])
    committed = report.get("manifest", {}).get("committed", [])
    missing = report.get("manifest", {}).get("missing_for_live_sources", [])
    lines.append(f"- Exact-hash committed sources: {len(committed)}")
    for item in committed:
        lines.append(f"  - `{item.get('path')}`")
    if missing:
        lines.append(f"- Live sources missing an exact-hash manifest entry: {len(missing)}")
        for path in missing:
            lines.append(f"  - `{path}`")

    lines.extend(["", "## Failures", ""])
    failures = report.get("failures", [])
    if not failures:
        lines.append("- None")
    else:
        for failure in failures:
            locator = failure.get("unit_id") or failure.get("source_id") or failure.get("path")
            lines.append(f"- `{locator}`: {failure.get('reason')}")

    lines.extend(["", "## Next action", ""])
    action = report.get("next_action", {})
    lines.append(f"- `{action.get('kind', 'inspect_incomplete_job')}`")
    next_unit = report.get("next_unit")
    if next_unit:
        lines.append(
            f"- Next unit: `{next_unit.get('source_id')}/{next_unit.get('unit_id')}` "
            f"via `{next_unit.get('transport')}`"
        )

    cross_linker = report.get("optional_postprocessing", {}).get("cross_linker", {})
    lines.extend(["", "## Optional post-processing", ""])
    if cross_linker.get("eligible"):
        lines.append("- `cross-linker` may be run separately; ingest does not run it.")
    else:
        lines.append("- `cross-linker` is deferred until the Job is live complete.")
    return "\n".join(lines) + "\n"


def resolve_packet_path(job_dir: Path, relative_path: str | Path) -> Path:
    """Resolve a Job-derived Packet path without permitting directory escape."""
    job_root = Path(job_dir).expanduser().resolve()
    packets_root = (job_root / "packets").resolve()
    candidate = (job_root / relative_path).resolve()
    if candidate.parent != packets_root:
        raise PipelineContractError("Packet path escapes the Job packets directory")
    return candidate


def write_packet(
    job_dir: Path,
    relative_path: str | Path,
    packet: dict[str, Any],
    *,
    job_source: dict[str, Any] | None = None,
) -> Path:
    """Validate and atomically write one worker-owned Packet artifact."""
    validate_packet(packet, job_source=job_source)
    target = resolve_packet_path(job_dir, relative_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".packet-", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(packet, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return target


def validate_packet(packet: dict[str, Any], *, job_source: dict[str, Any] | None = None) -> None:
    """Validate one bounded Packet and optionally bind it to a Job source/unit."""
    if packet.get("packet_version") != PACKET_VERSION:
        raise PipelineContractError("packet_version must be 1")
    for key in ("packet_id", "source", "unit", "extracted", "warnings"):
        if key not in packet:
            raise PipelineContractError(f"Packet is missing {key}")
    source = packet["source"]
    unit = packet["unit"]
    extracted = packet["extracted"]
    if not isinstance(source, dict) or not isinstance(unit, dict) or not isinstance(extracted, dict):
        raise PipelineContractError("Packet source, unit, and extracted values must be objects")
    for key in ("source_id", "path", "content_hash"):
        if not isinstance(source.get(key), str) or not source[key]:
            raise PipelineContractError(f"Packet source.{key} must be a non-empty string")
    for key in ("unit_id", "start_line", "end_line", "start_byte", "end_byte"):
        if key not in unit:
            raise PipelineContractError(f"Packet unit is missing {key}")
    if not isinstance(unit["unit_id"], str):
        raise PipelineContractError("Packet unit.unit_id must be a string")
    if not isinstance(unit.get("heading_path", []), list):
        raise PipelineContractError("Packet unit.heading_path must be a list")
    if not (isinstance(unit["start_line"], int) and isinstance(unit["end_line"], int)):
        raise PipelineContractError("Packet line offsets must be integers")
    if unit["start_line"] < 1 or unit["end_line"] < unit["start_line"]:
        raise PipelineContractError("Packet line range is invalid")
    if not (isinstance(unit["start_byte"], int) and isinstance(unit["end_byte"], int)):
        raise PipelineContractError("Packet byte offsets must be integers")
    if unit["start_byte"] < 0 or unit["end_byte"] <= unit["start_byte"]:
        raise PipelineContractError("Packet byte range is invalid")
    for key in ("concepts", "claims", "entities", "relationships", "questions"):
        if not isinstance(extracted.get(key), list):
            raise PipelineContractError(f"Packet extracted.{key} must be a list")
    if not isinstance(extracted.get("summary"), str) or not isinstance(packet["warnings"], list):
        raise PipelineContractError("Packet summary must be a string and warnings must be a list")

    if job_source is None:
        return
    for key in ("source_id", "path", "content_hash"):
        if source[key] != job_source.get(key):
            raise PipelineContractError(f"Packet source.{key} does not match the Job")
    planned = next(
        (candidate for candidate in job_source.get("units", [])
         if candidate.get("unit_id") == unit["unit_id"]),
        None,
    )
    if planned is None:
        raise PipelineContractError("Packet unit is not present in the Job")
    for key in ("start_line", "end_line", "start_byte", "end_byte"):
        if unit[key] != planned.get(key):
            raise PipelineContractError(f"Packet unit.{key} does not match the Job")


def next_pending_unit(job: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Return the first pending/failed unit in stable source order."""
    for source in job.get("sources", []):
        if source.get("status") not in {"processing", "failed"}:
            continue
        for unit in source.get("units", []):
            if unit.get("status") in {"pending", "failed"}:
                return source, unit
    return None


def _find_source_and_unit(
    job: dict[str, Any], source_id: str, unit_id: str
) -> tuple[dict[str, Any], dict[str, Any], int]:
    source = next(
        (item for item in job.get("sources", []) if item.get("source_id") == source_id), None
    )
    if source is None:
        raise PipelineContractError(f"unknown Job source: {source_id}")
    units = source.get("units", [])
    target_index = next(
        (index for index, unit in enumerate(units) if unit.get("unit_id") == unit_id), None
    )
    if target_index is None:
        raise PipelineContractError(f"unknown Job unit: {unit_id}")
    return source, units[target_index], target_index


def bind_inline_unit(
    job: dict[str, Any], source_id: str, unit_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate one full-source inline unit against current Job and source bytes."""
    source, unit, target_index = _find_source_and_unit(job, source_id, unit_id)
    if source.get("execution", {}).get("mode") != "inline":
        raise PipelineContractError("Job source is not planned for inline extraction")
    if unit.get("transport") != "inline" or "packet_path" in unit:
        raise PipelineContractError("inline unit must not declare a Packet path")
    if target_index != 0 or len(source.get("units", [])) != 1:
        raise PipelineContractError("inline extraction requires exactly one full-source unit")
    if unit.get("status") not in {"pending", "failed"}:
        raise PipelineContractError("inline unit has already advanced")
    path = Path(str(source.get("path", "")))
    if not path.is_file():
        raise PipelineContractError("inline source is missing")
    expected_hash = str(source.get("content_hash", ""))
    if expected_hash and ":" not in expected_hash:
        expected_hash = f"sha256:{expected_hash}"
    actual_hash = f"sha256:{compute_hash(path)}"
    if actual_hash != expected_hash:
        raise PipelineContractError("inline source hash changed after planning")
    threshold = job.get("execution", {}).get("direct_extract_max_bytes", 0)
    if not isinstance(threshold, int) or threshold <= 0 or path.stat().st_size > threshold:
        raise PipelineContractError("inline source exceeds the frozen direct extraction threshold")
    with path.open("rb") as stream:
        coverage_start = 3 if stream.read(3) == codecs.BOM_UTF8 else 0
    if (
        unit.get("start_byte") != coverage_start
        or unit.get("end_byte") != path.stat().st_size
    ):
        raise PipelineContractError("inline unit does not cover the complete source")
    return source, unit


def mark_unit_staged(
    job: dict[str, Any], source_id: str, unit_id: str, artifact_paths: list[str]
) -> None:
    """Record review artifacts without claiming that the unit is integrated."""
    if not artifact_paths or any(not isinstance(path, str) or not path for path in artifact_paths):
        raise PipelineContractError("a staged unit requires non-empty artifact paths")
    source, target, target_index = _find_source_and_unit(job, source_id, unit_id)
    units = source.get("units", [])
    if any(
        unit.get("status") not in {"staged", "approved_waiting_order", "integrated"}
        for unit in units[:target_index]
    ):
        raise PipelineContractError("Units must be staged serially in source order")
    if target.get("status") == "integrated":
        return
    existing = {
        artifact.get("path"): artifact
        for artifact in target.get("staging_artifacts", [])
        if isinstance(artifact, dict) and isinstance(artifact.get("path"), str)
    }
    all_paths = list(existing)
    all_paths.extend(path for path in artifact_paths if path not in existing)
    target["staging_artifacts"] = [
        existing.get(path, {"path": path, "status": "pending"}) for path in all_paths
    ]
    target["status"] = "staged"
    staged = sum(
        unit.get("status") in {"staged", "approved_waiting_order"} for unit in units
    )
    integrated = sum(unit.get("status") == "integrated" for unit in units)
    pending = next(
        (unit for unit in units if unit.get("status") in {"pending", "failed"}), None
    )
    source["chunk_plan"].update({
        "units_staged": staged,
        "units_integrated": integrated,
        "next_unit": pending.get("unit_id") if pending else None,
    })
    if pending is None and integrated < len(units):
        source["status"] = "awaiting_review"
    active_statuses = {
        item.get("status") for item in job.get("sources", [])
        if item.get("status") not in {"unchanged", "unsupported", "complete"}
    }
    if active_statuses and active_statuses <= {"awaiting_review", "ready_to_commit"}:
        job["status"] = "awaiting_review"


def record_staging_decision(
    job: dict[str, Any], artifact_path: str, *, accepted: bool
) -> list[tuple[str, str]]:
    """Record one review decision and advance only contiguous accepted units.

    Returns ``(source_id, unit_id)`` pairs newly promoted to ``integrated``.
    Page application and validation must succeed before callers record an
    accepted decision.
    """
    matched = False
    for source in job.get("sources", []):
        for unit in source.get("units", []):
            for artifact in unit.get("staging_artifacts", []):
                if artifact.get("path") == artifact_path:
                    artifact["status"] = "accepted" if accepted else "rejected"
                    matched = True
                    if not accepted:
                        unit["status"] = "review_rejected"
                        source["status"] = "incomplete"
                        job["status"] = "incomplete"
    if not matched:
        raise PipelineContractError(f"staged artifact is not present in the Job: {artifact_path}")
    if not accepted:
        return []

    advanced: list[tuple[str, str]] = []
    for source in job.get("sources", []):
        units = source.get("units", [])
        prefix_integrated = True
        for unit in units:
            if unit.get("status") == "integrated":
                continue
            artifacts = unit.get("staging_artifacts", [])
            all_accepted = bool(artifacts) and all(
                artifact.get("status") == "accepted" for artifact in artifacts
            )
            if all_accepted and prefix_integrated:
                unit["status"] = "integrated"
                advanced.append((str(source.get("source_id")), str(unit.get("unit_id"))))
            elif all_accepted:
                unit["status"] = "approved_waiting_order"
                prefix_integrated = False
            else:
                prefix_integrated = False
        integrated = sum(unit.get("status") == "integrated" for unit in units)
        staged = sum(
            unit.get("status") in {"staged", "approved_waiting_order"} for unit in units
        )
        source.get("chunk_plan", {}).update({
            "units_integrated": integrated,
            "units_staged": staged,
            "next_unit": None,
        })
        if units and integrated == len(units):
            source["status"] = "ready_to_commit"
        elif source.get("status") != "incomplete":
            source["status"] = "awaiting_review"
    if all(
        source.get("status") in {"unchanged", "unsupported", "ready_to_commit", "complete"}
        for source in job.get("sources", [])
    ):
        job["status"] = "ready_to_commit"
    elif job.get("status") != "incomplete":
        job["status"] = "awaiting_review"
    return advanced


def mark_unit_integrated(
    job: dict[str, Any], source_id: str, unit_id: str, packet_path: str | None = None
) -> None:
    """Advance exactly the next source unit, enforcing serial integration order."""
    source, target, target_index = _find_source_and_unit(job, source_id, unit_id)
    units = source.get("units", [])
    if any(unit.get("status") != "integrated" for unit in units[:target_index]):
        raise PipelineContractError("Packets must integrate serially in source order")
    transport = target.get("transport", "packet")
    if transport == "inline":
        if packet_path is not None:
            raise PipelineContractError("inline unit advance does not accept a Packet path")
        target["integrated_via"] = "inline"
    else:
        if not packet_path:
            raise PipelineContractError("Packet unit advance requires a Packet path")
        target["packet_path"] = packet_path
    target["status"] = "integrated"
    integrated = sum(unit.get("status") == "integrated" for unit in units)
    pending = next((unit for unit in units if unit.get("status") != "integrated"), None)
    source["chunk_plan"].update({
        "units_integrated": integrated,
        "next_unit": pending.get("unit_id") if pending else None,
    })
    if integrated == len(units):
        source["status"] = "ready_to_commit"
    if all(item.get("status") in {"unchanged", "unsupported", "ready_to_commit"}
           for item in job.get("sources", [])):
        job["status"] = "ready_to_commit"
