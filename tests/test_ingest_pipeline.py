from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from obsidian_wiki.ingest_pipeline import (
    PipelineContractError,
    classify_source,
    create_job,
    create_or_resume_job,
    discover_sources,
    mark_unit_integrated,
    mark_unit_staged,
    next_pending_unit,
    resolve_packet_path,
    record_staging_decision,
    validate_packet,
    write_packet,
)


def test_discovery_keeps_unsupported_visible_and_skips_generated_dirs(tmp_path):
    (tmp_path / "ok.md").write_text("# ok", encoding="utf-8")
    (tmp_path / "report.pdf").write_bytes(b"pdf")
    (tmp_path / "data.json").write_text("{}", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "hidden.md").write_text("hidden", encoding="utf-8")

    sources = discover_sources(tmp_path)

    assert {Path(item["path"]).name for item in sources} == {"ok.md", "report.pdf", "data.json"}
    pdf = next(item for item in sources if item["kind"] == "pdf")
    assert pdf["supported"] is False
    assert "not available" in pdf["reason"]
    assert classify_source(tmp_path / "fake.pdf")["supported"] is False


def test_create_job_contains_ranges_not_source_bodies(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    sources = tmp_path / "sources"
    sources.mkdir()
    secret = "UNIQUE SOURCE BODY THAT MUST NOT ENTER JOB"
    (sources / "large.md").write_text("# A\n\n" + secret + "\n" * 20, encoding="utf-8")
    (sources / "report.pdf").write_bytes(b"pdf")

    job_dir, job = create_job(
        sources, vault, target_budget=48, hard_budget=64,
        now=datetime(2026, 8, 26, 6, 30, 12, tzinfo=timezone.utc),
    )

    serialized = (job_dir / "job.json").read_text(encoding="utf-8")
    assert secret not in serialized
    assert job["status"] == "incomplete"
    supported = next(item for item in job["sources"] if item["kind"] == "markdown")
    assert supported["chunk_plan"]["units_total"] > 1
    assert all("data" not in unit and "content" not in unit for unit in supported["units"])
    assert next(item for item in job["sources"] if item["kind"] == "pdf")["status"] == "unsupported"


def test_matching_complete_manifest_source_is_unchanged(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    source = tmp_path / "source.txt"
    source.write_text("hello", encoding="utf-8")
    import hashlib
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    (vault / ".manifest.json").write_text(json.dumps({"sources": [{
        "path": str(source), "content_hash": f"sha256:{digest}", "chunker_version": 1,
        "units_total": 1, "units_integrated": 1,
    }]}), encoding="utf-8")

    _, job = create_job(source, vault)
    assert job["sources"][0]["status"] == "unchanged"
    assert job["status"] == "complete"


def _packet_for(source, unit):
    return {
        "packet_version": 1,
        "packet_id": f"pkt_{source['source_id']}_{unit['unit_id']}",
        "source": {key: source[key] for key in ("source_id", "path", "content_hash")},
        "unit": {key: unit[key] for key in (
            "unit_id", "heading_path", "start_line", "end_line", "start_byte", "end_byte"
        )},
        "extracted": {
            "summary": "summary", "concepts": [], "claims": [], "entities": [],
            "relationships": [], "questions": [],
        },
        "warnings": [],
    }


def test_packet_validation_and_serial_integration(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    source_path = tmp_path / "source.txt"
    source_path.write_text("para\n\n" * 20, encoding="utf-8")
    _, job = create_job(source_path, vault, target_budget=20, hard_budget=24)
    source = job["sources"][0]
    first, second = source["units"][:2]

    validate_packet(_packet_for(source, first), job_source=source)
    bad = _packet_for(source, first)
    bad["unit"]["end_byte"] += 1
    with pytest.raises(PipelineContractError, match="does not match"):
        validate_packet(bad, job_source=source)

    with pytest.raises(PipelineContractError, match="serially"):
        mark_unit_integrated(job, source["source_id"], second["unit_id"], second["packet_path"])
    mark_unit_integrated(job, source["source_id"], first["unit_id"], first["packet_path"])
    pending_source, pending_unit = next_pending_unit(job)
    assert pending_source is source
    assert pending_unit["unit_id"] == second["unit_id"]


def test_resume_matching_job_and_invalidate_changed_source(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    source = tmp_path / "source.md"
    source.write_text("# Original\n\nbody\n" * 10, encoding="utf-8")
    first_dir, first_job, resumed = create_or_resume_job(
        source, vault, target_budget=30, hard_budget=40
    )
    assert resumed is False

    resumed_dir, resumed_job, resumed = create_or_resume_job(
        source, vault, target_budget=30, hard_budget=40
    )
    assert resumed is True
    assert resumed_dir == first_dir
    assert resumed_job["job_id"] == first_job["job_id"]

    source.write_text("# Changed\n\nreplacement\n", encoding="utf-8")
    new_dir, _, resumed = create_or_resume_job(source, vault, target_budget=30, hard_budget=40)
    assert resumed is False
    assert new_dir != first_dir
    assert json.loads((first_dir / "job.json").read_text())["status"] == "invalidated"


def test_packet_paths_cannot_escape_job_directory(tmp_path):
    job_dir = tmp_path / "job"
    (job_dir / "packets").mkdir(parents=True)
    with pytest.raises(PipelineContractError, match="escapes"):
        resolve_packet_path(job_dir, "../outside.json")

    packet = {
        "packet_version": 1, "packet_id": "pkt", "source": {
            "source_id": "src", "path": "/source.md", "content_hash": "sha256:x"
        },
        "unit": {"unit_id": "unit", "start_line": 1, "end_line": 1,
                 "start_byte": 0, "end_byte": 1},
        "extracted": {"summary": "", "concepts": [], "claims": [], "entities": [],
                      "relationships": [], "questions": []},
        "warnings": [],
    }
    target = write_packet(job_dir, "packets/source-unit.json", packet)
    assert target.parent == (job_dir / "packets").resolve()
    assert json.loads(target.read_text())["packet_id"] == "pkt"


def test_staged_units_do_not_integrate_until_artifacts_are_accepted(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    source_path = tmp_path / "source.txt"
    source_path.write_text("para\n\n" * 20, encoding="utf-8")
    _, job = create_job(source_path, vault, target_budget=20, hard_budget=24)
    source = job["sources"][0]
    first, second = source["units"][:2]

    mark_unit_staged(job, source["source_id"], first["unit_id"], ["_staging/a.md"])
    mark_unit_staged(job, source["source_id"], second["unit_id"], ["_staging/b.md"])
    assert source["chunk_plan"]["units_integrated"] == 0
    assert source["chunk_plan"]["units_staged"] == 2

    advanced = record_staging_decision(job, "_staging/b.md", accepted=True)
    assert advanced == []
    assert second["status"] == "approved_waiting_order"
    assert source["chunk_plan"]["units_integrated"] == 0

    advanced = record_staging_decision(job, "_staging/a.md", accepted=True)
    assert (source["source_id"], first["unit_id"]) in advanced
    assert (source["source_id"], second["unit_id"]) in advanced
    assert source["chunk_plan"]["units_integrated"] == 2


def test_rejected_staged_artifact_keeps_source_incomplete(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    source_path = tmp_path / "source.md"
    source_path.write_text("# Heading\n\nbody\n", encoding="utf-8")
    _, job = create_job(source_path, vault)
    source = job["sources"][0]
    unit = source["units"][0]
    mark_unit_staged(job, source["source_id"], unit["unit_id"], ["_staging/page.md"])

    assert record_staging_decision(job, "_staging/page.md", accepted=False) == []
    assert unit["status"] == "review_rejected"
    assert source["status"] == "incomplete"
    assert job["status"] == "incomplete"
    assert source["chunk_plan"]["units_integrated"] == 0
