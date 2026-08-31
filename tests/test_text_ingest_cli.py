from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    return subprocess.run(
        [sys.executable, "-m", "obsidian_wiki", *args],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_text_ingest_plan_and_status_are_cwd_independent(tmp_path: Path) -> None:
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    (source_dir / "one.md").write_text("# One\n\nbody\n", encoding="utf-8")
    (source_dir / "unsupported.pdf").write_bytes(b"pdf")
    vault = tmp_path / "vault"
    vault.mkdir()
    artifacts = tmp_path / "artifacts"
    plan_path = artifacts / "job-plan.json"
    options_path = artifacts / "chunk-options.json"
    options_path.parent.mkdir()
    options_path.write_text('{"owner":"workflow"}', encoding="utf-8")

    planned = run_cli(
        "text-ingest-plan", str(source_dir),
        "--vault", str(vault),
        "--write-mode", "staged",
        "--target-budget", "16",
        "--min-budget", "8",
        "--hard-budget", "24",
        "--direct-extract-max-bytes", "0",
        "--chunk-strategy", "strict_sections",
        "--strategy-options-file", str(options_path),
        "--output", str(plan_path),
        "--pretty",
        cwd=tmp_path,
    )

    assert planned.returncode == 0, planned.stderr
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    assert plan["write_mode"] == "staged"
    assert plan["source_counts"]["unsupported"] == 1
    assert plan["next_unit"]["source_path"].endswith("one.md")
    job = json.loads(Path(plan["job_path"]).read_text(encoding="utf-8"))
    planned_source = next(source for source in job["sources"] if "budget" in source)
    assert planned_source["budget"] == {
        "mode": "utf8_bytes", "target": 16, "min": 8, "hard_max": 24,
    }
    assert planned_source["chunking"] == {
        "strategy": "strict_sections", "options": {"owner": "workflow"},
    }

    status_path = artifacts / "job-status.json"
    status = run_cli(
        "text-ingest-status", plan["job_dir"],
        "--output", str(status_path),
        "--pretty",
        cwd=tmp_path,
    )

    assert status.returncode == 0, status.stderr
    assert json.loads(status_path.read_text(encoding="utf-8"))["job_id"] == plan["job_id"]


def test_text_ingest_plan_help_exposes_chunk_and_inline_options(tmp_path: Path) -> None:
    result = run_cli("text-ingest-plan", "--help", cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert "--min-budget" in result.stdout
    assert "--chunk-strategy" in result.stdout
    assert "--direct-extract-max-bytes" in result.stdout
    assert "adaptive_sections" in result.stdout


def test_folder_workflow_uses_unprefixed_subworkflows_and_cli_coordination() -> None:
    workflow = (ROOT / "workflows" / "wiki-folder-ingest.yaml").read_text(encoding="utf-8")
    skill = (ROOT / ".skills" / "wiki-folder-ingest" / "SKILL.md").read_text(encoding="utf-8")
    packet = (ROOT / "workflows" / "wiki-packet-integrate.yaml").read_text(encoding="utf-8")

    assert "obsidian-wiki text-ingest-plan" in workflow
    assert "WIKI_TEXT_CHUNK_TARGET_BYTES" in workflow
    assert "WIKI_TEXT_CHUNK_MIN_BYTES" in workflow
    assert "WIKI_TEXT_CHUNK_HARD_MAX_BYTES" in workflow
    assert "WIKI_TEXT_CHUNK_STRATEGY" in workflow
    assert "WIKI_TEXT_CHUNK_OPTIONS" in workflow
    assert "WIKI_FOLDER_INGEST_MAX_EXTRACTION_WORKERS" in workflow
    assert "WIKI_TEXT_DIRECT_EXTRACT_MAX_BYTES" in workflow
    assert '--target-budget "<text_chunking.target_bytes>"' in workflow
    assert '--min-budget "<text_chunking.min_bytes>"' in workflow
    assert '--hard-budget "<text_chunking.hard_max_bytes>"' in workflow
    assert '--chunk-strategy "<text_chunking.strategy>"' in workflow
    assert '--direct-extract-max-bytes "<text_ingest.direct_extract_max_bytes>"' in workflow
    assert "--strategy-options-file" in workflow
    assert "obsidian-wiki text-ingest-status" in workflow
    assert "wiki/" not in workflow
    assert ".cac/" not in workflow
    assert "同一文档的多个 packet unit 也可并行" in workflow
    assert "text_ingest.max_extraction_workers" in workflow
    assert "integration 均不并发" in workflow
    assert workflow.count("check_voting:") == 0
    assert "workflow: wiki-page-contract" in workflow
    assert workflow.count("workflow: wiki-finalize-sources") == 1
    assert "wiki-packet-integrate" in workflow
    assert "obsidian-wiki text-ingest-plan" in skill
    assert "WIKI_TEXT_CHUNK_TARGET_BYTES" in skill
    assert "WIKI_TEXT_CHUNK_MIN_BYTES" in skill
    assert "WIKI_TEXT_CHUNK_HARD_MAX_BYTES" in skill
    assert "WIKI_TEXT_CHUNK_STRATEGY" in skill
    assert "WIKI_FOLDER_INGEST_MAX_EXTRACTION_WORKERS" in skill
    assert "WIKI_TEXT_DIRECT_EXTRACT_MAX_BYTES" in skill
    assert "同一文档的多个 packet unit 也可并行提取" in skill
    assert "所有页面 integration 均不并发" in skill
    assert ".cac/" not in skill
    assert "`wiki/" not in skill
    assert not (ROOT / "workflows" / "wiki-ingest.yaml").exists()
    assert "workflow: wiki-context" not in packet
    assert "workflow: wiki-page-contract" not in packet
    assert "workflow: wiki-finalize-sources" not in packet
    assert "check_voting:" not in packet
    assert "resolve_wiki_route.py" not in packet
    assert "obsidian-wiki wiki-route-resolve" in packet
    assert "obsidian-wiki text-ingest-packet-check" in packet
    assert "obsidian-wiki text-ingest-unit-advance" in packet
    assert "obsidian-wiki text-ingest-inline-check" in packet
    assert "obsidian-wiki text-ingest-inline-advance" in packet


def _write_planned_packet(job_dir: Path) -> tuple[Path, dict, dict]:
    job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    source = job["sources"][0]
    unit = source["units"][0]
    packet_path = job_dir / unit["packet_path"]
    packet = {
        "packet_version": 1,
        "packet_id": "pkt-1",
        "source": {
            "source_id": source["source_id"],
            "path": source["path"],
            "content_hash": source["content_hash"],
        },
        "unit": {
            key: unit[key]
            for key in ("unit_id", "start_line", "end_line", "start_byte", "end_byte")
        },
        "extracted": {
            "summary": "",
            "concepts": [],
            "claims": [],
            "entities": [],
            "relationships": [],
            "questions": [],
        },
        "warnings": [],
    }
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    return packet_path, source, unit


def test_packet_check_and_direct_advance_are_atomic_cli_operations(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text("# One\n\nbody\n", encoding="utf-8")
    vault = tmp_path / "vault"
    vault.mkdir()
    planned = run_cli(
        "text-ingest-plan", str(source), "--vault", str(vault),
        "--direct-extract-max-bytes", "0", cwd=tmp_path
    )
    assert planned.returncode == 0, planned.stderr
    job_dir = Path(json.loads(planned.stdout)["job_dir"])
    packet_path, source_record, unit = _write_planned_packet(job_dir)

    checked = run_cli(
        "text-ingest-packet-check", str(job_dir), str(packet_path), cwd=tmp_path
    )
    assert checked.returncode == 0, checked.stderr
    assert json.loads(checked.stdout)["unit_id"] == unit["unit_id"]

    advanced = run_cli(
        "text-ingest-unit-advance", str(job_dir), str(packet_path),
        "--mode", "direct", cwd=tmp_path,
    )
    assert advanced.returncode == 0, advanced.stderr
    result = json.loads(advanced.stdout)
    assert result["advanced"]["status"] == "integrated"
    job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    assert job["sources"][0]["source_id"] == source_record["source_id"]
    assert job["sources"][0]["units"][0]["status"] == "integrated"

    duplicate = run_cli(
        "text-ingest-packet-check", str(job_dir), str(packet_path), cwd=tmp_path
    )
    assert duplicate.returncode == 1
    assert "already advanced" in duplicate.stderr


def test_staged_advance_requires_artifacts_and_never_integrates(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("body\n", encoding="utf-8")
    vault = tmp_path / "vault"
    vault.mkdir()
    planned = run_cli(
        "text-ingest-plan", str(source), "--vault", str(vault),
        "--write-mode", "staged", "--direct-extract-max-bytes", "0", cwd=tmp_path,
    )
    assert planned.returncode == 0, planned.stderr
    job_dir = Path(json.loads(planned.stdout)["job_dir"])
    packet_path, _source_record, _unit = _write_planned_packet(job_dir)

    missing = run_cli(
        "text-ingest-unit-advance", str(job_dir), str(packet_path),
        "--mode", "staged", cwd=tmp_path,
    )
    assert missing.returncode == 1
    advanced = run_cli(
        "text-ingest-unit-advance", str(job_dir), str(packet_path),
        "--mode", "staged", "--artifact", "_staging/page.md", cwd=tmp_path,
    )
    assert advanced.returncode == 0, advanced.stderr
    result = json.loads(advanced.stdout)
    assert result["advanced"]["status"] == "staged"
    assert result["units"]["integrated"] == 0
    assert result["units"]["staged"] == 1


def test_inline_check_and_direct_advance_require_no_packet(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text("# Small\n\nBody.\n", encoding="utf-8")
    vault = tmp_path / "vault"
    vault.mkdir()

    planned = run_cli(
        "text-ingest-plan", str(source), "--vault", str(vault),
        "--direct-extract-max-bytes", "16000", cwd=tmp_path,
    )
    assert planned.returncode == 0, planned.stderr
    summary = json.loads(planned.stdout)
    assert summary["next_unit"]["transport"] == "inline"
    assert "packet_path" not in summary["next_unit"]
    job_dir = Path(summary["job_dir"])
    job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    source_record = job["sources"][0]
    unit = source_record["units"][0]
    assert not any((job_dir / "packets").iterdir())

    checked = run_cli(
        "text-ingest-inline-check", str(job_dir),
        "--source-id", source_record["source_id"],
        "--unit-id", unit["unit_id"], cwd=tmp_path,
    )
    assert checked.returncode == 0, checked.stderr
    assert json.loads(checked.stdout)["transport"] == "inline"

    advanced = run_cli(
        "text-ingest-inline-advance", str(job_dir),
        "--source-id", source_record["source_id"],
        "--unit-id", unit["unit_id"], "--mode", "direct", cwd=tmp_path,
    )
    assert advanced.returncode == 0, advanced.stderr
    result = json.loads(advanced.stdout)
    assert result["advanced"]["transport"] == "inline"
    stored = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    assert stored["sources"][0]["units"][0]["integrated_via"] == "inline"
    assert not any((job_dir / "packets").iterdir())


def test_inline_advance_rechecks_source_hash(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text("small\n", encoding="utf-8")
    vault = tmp_path / "vault"
    vault.mkdir()
    planned = run_cli(
        "text-ingest-plan", str(source), "--vault", str(vault), cwd=tmp_path,
    )
    summary = json.loads(planned.stdout)
    job_dir = Path(summary["job_dir"])
    job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    source_record = job["sources"][0]
    unit = source_record["units"][0]
    source.write_text("changed\n", encoding="utf-8")

    advanced = run_cli(
        "text-ingest-inline-advance", str(job_dir),
        "--source-id", source_record["source_id"],
        "--unit-id", unit["unit_id"], "--mode", "direct", cwd=tmp_path,
    )
    assert advanced.returncode == 1
    assert "hash changed" in advanced.stderr


def test_inline_staged_advance_requires_review_artifact(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("small\n", encoding="utf-8")
    vault = tmp_path / "vault"
    vault.mkdir()
    planned = run_cli(
        "text-ingest-plan", str(source), "--vault", str(vault),
        "--write-mode", "staged", cwd=tmp_path,
    )
    summary = json.loads(planned.stdout)
    job_dir = Path(summary["job_dir"])
    job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    source_record = job["sources"][0]
    unit = source_record["units"][0]

    missing = run_cli(
        "text-ingest-inline-advance", str(job_dir),
        "--source-id", source_record["source_id"],
        "--unit-id", unit["unit_id"], "--mode", "staged", cwd=tmp_path,
    )
    assert missing.returncode == 1
    advanced = run_cli(
        "text-ingest-inline-advance", str(job_dir),
        "--source-id", source_record["source_id"],
        "--unit-id", unit["unit_id"], "--mode", "staged",
        "--artifact", "_staging/page.md", cwd=tmp_path,
    )
    assert advanced.returncode == 0, advanced.stderr
    assert json.loads(advanced.stdout)["advanced"]["status"] == "staged"
