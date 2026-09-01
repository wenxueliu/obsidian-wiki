"""Bounded Claude Code workers for packet-transport text-ingest units.

The coordinator owns Job state.  Each Claude process sees only the three
identifiers accepted by ``wiki-source-text`` and writes its result to the
pre-planned Packet path on disk.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from obsidian_wiki.ingest_pipeline import (
    PipelineContractError,
    load_job,
    resolve_packet_path,
    validate_packet,
    write_job,
)


DEFAULT_MAX_WORKERS = 4
MAX_WORKERS = 32


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_component(value: str) -> str:
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
    if not value or any(character not in allowed for character in value):
        raise PipelineContractError(f"unsafe worker identifier: {value!r}")
    return value


def _find_unit(
    job: dict[str, Any], source_id: str, unit_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    source = next(
        (item for item in job.get("sources", []) if item.get("source_id") == source_id),
        None,
    )
    if source is None:
        raise PipelineContractError(f"unknown Job source: {source_id}")
    unit = next(
        (item for item in source.get("units", []) if item.get("unit_id") == unit_id),
        None,
    )
    if unit is None:
        raise PipelineContractError(f"unknown Job unit: {unit_id}")
    return source, unit


def _validate_planned_packet(
    job_dir: Path, source: dict[str, Any], unit: dict[str, Any]
) -> Path:
    packet_path = resolve_packet_path(job_dir, unit.get("packet_path", ""))
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    if not isinstance(packet, dict):
        raise PipelineContractError("Packet must be a JSON object")
    validate_packet(packet, job_source=source)
    if packet.get("unit", {}).get("unit_id") != unit.get("unit_id"):
        raise PipelineContractError("Packet unit does not match the claimed unit")
    return packet_path


@dataclass(frozen=True)
class WorkerTask:
    source_id: str
    unit_id: str
    worker_dir: Path


@dataclass(frozen=True)
class WorkerResult:
    task: WorkerTask
    returncode: int
    timed_out: bool
    error: str | None


def _run_worker(
    task: WorkerTask,
    *,
    job_dir: Path,
    source_skill_dir: Path,
    claude_executable: str,
    timeout_seconds: int,
) -> WorkerResult:
    try:
        task.worker_dir.mkdir(parents=True, exist_ok=True)
        project_skills = task.worker_dir / ".claude" / "skills"
        project_skills.mkdir(parents=True, exist_ok=True)
        worker_skill = project_skills / "wiki-source-text"
        try:
            worker_skill.symlink_to(source_skill_dir, target_is_directory=True)
        except OSError:
            # Windows and restricted filesystems may disallow symlinks.  Each
            # attempt has a fresh directory, so a private copy is equally isolated.
            shutil.copytree(source_skill_dir, worker_skill)
    except OSError:
        return WorkerResult(task, 127, False, "cannot prepare isolated worker skill")
    prompt = (
        "/wiki-source-text "
        + json.dumps(
            {
                "job_directory": str(job_dir),
                "source_id": task.source_id,
                "unit_id": task.unit_id,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
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
            cwd=task.worker_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=timeout_seconds,
        )
        error = None if completed.returncode == 0 else f"claude exited {completed.returncode}"
        return WorkerResult(task, completed.returncode, False, error)
    except subprocess.TimeoutExpired:
        return WorkerResult(task, 124, True, f"claude timed out after {timeout_seconds}s")
    except OSError as exc:
        return WorkerResult(task, 127, False, f"cannot start claude: {exc}")


def _packet_candidates(job: dict[str, Any]) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    for source in job.get("sources", []):
        for unit in source.get("units", []):
            if unit.get("transport", "packet") != "packet":
                continue
            if unit.get("status") in {"pending", "failed"}:
                candidates.append((str(source.get("source_id")), str(unit.get("unit_id"))))
    return candidates


def _bundled_source_skill() -> Path:
    package_dir = Path(__file__).resolve().parent
    for candidate in (
        package_dir / "_data" / "skills" / "wiki-source-text",
        package_dir.parent / ".skills" / "wiki-source-text",
    ):
        if (candidate / "SKILL.md").is_file():
            return candidate.resolve()
    raise PipelineContractError("bundled wiki-source-text skill is missing")


def _acquire_lock(lock_path: Path) -> int:
    """Acquire the single-coordinator lock, reclaiming a provably stale owner."""
    for _attempt in range(2):
        try:
            return os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            try:
                age = time.time() - lock_path.stat().st_mtime
                content = lock_path.read_text(encoding="utf-8")
                pid_line = next(
                    (line for line in content.splitlines() if line.startswith("pid=")), ""
                )
                pid = int(pid_line.removeprefix("pid=")) if pid_line else None
            except (OSError, ValueError):
                age, pid = 0.0, None
            # A just-created empty lock belongs to a coordinator that has not
            # yet flushed its PID.  Do not race it by treating it as stale.
            if age < 30:
                raise PipelineContractError(
                    f"another extraction coordinator owns {lock_path}"
                ) from exc
            alive = False
            if pid is not None:
                try:
                    os.kill(pid, 0)
                    alive = True
                except PermissionError:
                    alive = True
                except ProcessLookupError:
                    pass
                except OSError:
                    pass
            if alive:
                raise PipelineContractError(
                    f"another extraction coordinator owns {lock_path}"
                ) from exc
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass
    raise PipelineContractError(f"could not acquire extraction coordinator lock: {lock_path}")


def run_claude_extraction_pool(
    job_dir: Path,
    *,
    max_workers: int = DEFAULT_MAX_WORKERS,
    timeout_seconds: int = 3600,
    claude_executable: str = "claude",
) -> dict[str, Any]:
    """Extract every currently eligible Packet unit once with bounded concurrency."""
    directory = Path(job_dir).expanduser().resolve()
    if not 1 <= max_workers <= MAX_WORKERS:
        raise PipelineContractError(f"max_workers must be between 1 and {MAX_WORKERS}")
    if timeout_seconds <= 0:
        raise PipelineContractError("timeout_seconds must be positive")

    job = load_job(directory)
    source_skill_dir = _bundled_source_skill()
    lock_path = directory / ".claude-extraction.lock"
    lock_fd = _acquire_lock(lock_path)

    reports: list[dict[str, Any]] = []
    reconciled: list[dict[str, str]] = []
    try:
        with os.fdopen(lock_fd, "w", encoding="utf-8") as stream:
            stream.write(f"pid={os.getpid()}\nstarted_at={_now()}\n")
            stream.flush()
            os.fsync(stream.fileno())

        # A prior coordinator may have stopped after the worker wrote its Packet
        # but before the Job transition.  Reconcile that durable boundary first.
        for source in job.get("sources", []):
            for unit in source.get("units", []):
                if (
                    unit.get("transport", "packet") != "packet"
                    or unit.get("status") != "extracting"
                ):
                    continue
                try:
                    _validate_planned_packet(directory, source, unit)
                    unit["status"] = "packet_ready"
                    unit.pop("reason", None)
                    outcome = "packet_ready"
                except (
                    OSError,
                    ValueError,
                    json.JSONDecodeError,
                    PipelineContractError,
                ) as exc:
                    unit["status"] = "failed"
                    unit["reason"] = f"stale extraction reconciliation: {exc}"
                    outcome = "failed"
                reconciled.append({
                    "source_id": str(source.get("source_id")),
                    "unit_id": str(unit.get("unit_id")),
                    "status": outcome,
                })
        if reconciled:
            write_job(directory, job)

        pending = _packet_candidates(job)
        pending_index = 0
        active: dict[Future[WorkerResult], WorkerTask] = {}

        def claim_next() -> WorkerTask | None:
            nonlocal pending_index
            if pending_index >= len(pending):
                return None
            source_id, unit_id = pending[pending_index]
            pending_index += 1
            source, unit = _find_unit(job, source_id, unit_id)
            if unit.get("status") not in {"pending", "failed"}:
                return claim_next()
            unit["status"] = "extracting"
            unit.pop("reason", None)
            unit["attempt"] = int(unit.get("attempt", 0)) + 1
            unit["extraction_started_at"] = _now()
            if source.get("status") == "failed":
                source["status"] = "processing"
            worker_dir = (
                directory
                / "workers"
                / _safe_component(source_id)
                / _safe_component(unit_id)
                / f"attempt-{unit['attempt']:04d}"
            )
            return WorkerTask(source_id, unit_id, worker_dir)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            initial_tasks: list[WorkerTask] = []
            while len(initial_tasks) < max_workers:
                task = claim_next()
                if task is None:
                    break
                initial_tasks.append(task)
            if initial_tasks:
                # Persist every claim before any worker can observe job.json.
                write_job(directory, job)
            for task in initial_tasks:
                active[executor.submit(
                    _run_worker,
                    task,
                    job_dir=directory,
                    source_skill_dir=source_skill_dir,
                    claude_executable=claude_executable,
                    timeout_seconds=timeout_seconds,
                )] = task

            while active:
                completed_futures, _ = wait(active, return_when=FIRST_COMPLETED)
                for future in completed_futures:
                    task = active.pop(future)
                    try:
                        result = future.result()
                    except Exception as exc:  # defensive boundary around one worker slot
                        result = WorkerResult(
                            task, 1, False, f"worker coordinator error: {type(exc).__name__}"
                        )
                    source, unit = _find_unit(job, task.source_id, task.unit_id)
                    packet_path: str | None = None
                    error = result.error
                    if result.returncode == 0:
                        try:
                            validated = _validate_planned_packet(directory, source, unit)
                            validation_report = task.worker_dir / "packet-validation.md"
                            if not validation_report.is_file():
                                raise PipelineContractError(
                                    "worker did not write packet-validation.md"
                                )
                            packet_path = validated.relative_to(directory).as_posix()
                        except (
                            OSError,
                            ValueError,
                            json.JSONDecodeError,
                            PipelineContractError,
                        ) as exc:
                            error = f"Packet validation failed: {exc}"
                    if error is None:
                        unit["status"] = "packet_ready"
                        unit.pop("reason", None)
                        status = "packet_ready"
                    else:
                        unit["status"] = "failed"
                        unit["reason"] = error
                        status = "failed"
                    unit["extraction_finished_at"] = _now()
                    report = {
                        "source_id": task.source_id,
                        "unit_id": task.unit_id,
                        "status": status,
                        "packet_path": packet_path,
                        "packet_validation_report": str(
                            task.worker_dir / "packet-validation.md"
                        ),
                        "worker_dir": str(task.worker_dir),
                        "attempt": unit.get("attempt"),
                        "timed_out": result.timed_out,
                    }
                    if error is not None:
                        report["error"] = error
                    reports.append(report)

                replacements: list[WorkerTask] = []
                while len(active) + len(replacements) < max_workers:
                    replacement = claim_next()
                    if replacement is None:
                        break
                    replacements.append(replacement)
                # Completion and replacement claims are committed together,
                # before replacement workers are allowed to inspect the Job.
                write_job(directory, job)
                for replacement in replacements:
                    active[executor.submit(
                        _run_worker,
                        replacement,
                        job_dir=directory,
                        source_skill_dir=source_skill_dir,
                        claude_executable=claude_executable,
                        timeout_seconds=timeout_seconds,
                    )] = replacement

        failures = sum(item["status"] == "failed" for item in reports)
        return {
            "status": "failed" if failures else "complete",
            "job_dir": str(directory),
            "worker_backend": "claude-print",
            "skill": "wiki-source-text",
            "max_workers": max_workers,
            "dangerously_skip_permissions": True,
            "eligible_units": len(pending),
            "packet_ready": len(reports) - failures,
            "failed": failures,
            "reconciled": reconciled,
            "units": reports,
        }
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass
