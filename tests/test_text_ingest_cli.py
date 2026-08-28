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

    assert "obsidian-wiki text-ingest-plan" in workflow
    assert "obsidian-wiki text-ingest-status" in workflow
    assert "wiki/" not in workflow
    assert ".cac/" not in workflow
    assert "按输入文档建立独立调度 lane" in workflow
    assert "每个 planned unit 使用一个 fresh isolated subagent" in workflow
    assert workflow.count("check_voting:") == 0
    assert "obsidian-wiki text-ingest-plan" in skill
    assert ".cac/" not in skill
    assert "`wiki/" not in skill
