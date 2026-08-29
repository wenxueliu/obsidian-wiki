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

    planned = run_cli(
        "text-ingest-plan", str(source_dir),
        "--vault", str(vault),
        "--write-mode", "staged",
        "--output", str(plan_path),
        "--pretty",
        cwd=tmp_path,
    )

    assert planned.returncode == 0, planned.stderr
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    assert plan["write_mode"] == "staged"
    assert plan["source_counts"]["unsupported"] == 1
    assert plan["next_unit"]["source_path"].endswith("one.md")

    status_path = artifacts / "job-status.json"
    status = run_cli(
        "text-ingest-status", plan["job_dir"],
        "--output", str(status_path),
        "--pretty",
        cwd=tmp_path,
    )

    assert status.returncode == 0, status.stderr
    assert json.loads(status_path.read_text(encoding="utf-8"))["job_id"] == plan["job_id"]


def test_folder_workflow_uses_unprefixed_subworkflows_and_cli_coordination() -> None:
    workflow = (ROOT / "workflows" / "wiki-folder-ingest.yaml").read_text(encoding="utf-8")
    skill = (ROOT / ".skills" / "wiki-folder-ingest" / "SKILL.md").read_text(encoding="utf-8")
    packet = (ROOT / "workflows" / "wiki-packet-integrate.yaml").read_text(encoding="utf-8")

    assert "obsidian-wiki text-ingest-plan" in workflow
    assert "WIKI_TEXT_CHUNK_TARGET_BYTES" in workflow
    assert "WIKI_TEXT_CHUNK_HARD_MAX_BYTES" in workflow
    assert '--target-budget "<configured-or-48000>"' in workflow
    assert '--hard-budget "<configured-or-64000>"' in workflow
    assert "obsidian-wiki text-ingest-status" in workflow
    assert "wiki/" not in workflow
    assert ".cac/" not in workflow
    assert "按输入文档建立独立调度 lane" in workflow
    assert "每个 planned unit 使用一个 fresh isolated subagent" in workflow
    assert workflow.count("check_voting:") == 0
    assert "workflow: wiki-page-contract" in workflow
    assert workflow.count("workflow: wiki-finalize-sources") == 1
    assert "wiki-packet-integrate" in workflow
    assert "obsidian-wiki text-ingest-plan" in skill
    assert "WIKI_TEXT_CHUNK_TARGET_BYTES" in skill
    assert "WIKI_TEXT_CHUNK_HARD_MAX_BYTES" in skill
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
        "text-ingest-plan", str(source), "--vault", str(vault), cwd=tmp_path
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
        "--write-mode", "staged", cwd=tmp_path,
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
