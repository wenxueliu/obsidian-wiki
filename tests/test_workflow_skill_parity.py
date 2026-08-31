from __future__ import annotations

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / "workflows"
SKILLS = ROOT / ".skills"
BEGIN_MARKER = "<!-- BEGIN GENERATED WORKFLOW CONTRACT -->\n````yaml\n"
END_MARKER = "````\n<!-- END GENERATED WORKFLOW CONTRACT -->\n"
CURATED_SKILLS = {"wiki-folder-ingest", "wiki-source-text"}


def test_every_top_level_workflow_has_a_matching_skill() -> None:
    missing = [
        workflow.stem
        for workflow in sorted(WORKFLOWS.glob("*.yaml"))
        if not (SKILLS / workflow.stem / "SKILL.md").is_file()
    ]
    assert missing == []


def test_matching_skills_embed_the_authoritative_workflow_verbatim() -> None:
    for workflow in sorted(WORKFLOWS.glob("*.yaml")):
        if workflow.stem in CURATED_SKILLS:
            continue
        skill = (SKILLS / workflow.stem / "SKILL.md").read_text(encoding="utf-8")
        assert skill.count(BEGIN_MARKER) == 1, workflow.name
        assert skill.count(END_MARKER) == 1, workflow.name
        embedded = skill.split(BEGIN_MARKER, 1)[1].split(END_MARKER, 1)[0]
        expected = workflow.read_text(encoding="utf-8")
        if not expected.endswith("\n"):
            expected += "\n"
        assert embedded == expected, workflow.name


def test_curated_folder_ingest_skill_preserves_workflow_behavior() -> None:
    skill = (SKILLS / "wiki-folder-ingest" / "SKILL.md").read_text(encoding="utf-8")

    assert BEGIN_MARKER not in skill
    assert END_MARKER not in skill
    for behavior in (
        "Coordinator 只持有 metadata 和 artifacts",
        "obsidian-wiki text-ingest-plan",
        "wiki-page-contract",
        "text_ingest.max_extraction_workers",
        "wiki-source-text",
        "wiki-packet-integrate",
        "integration 全局有序串行",
        "wiki-finalize-sources",
        "obsidian-wiki text-ingest-report",
        "本 skill 不调用它",
        "<promise>done</promise>",
    ):
        assert behavior in skill


def test_curated_source_text_skill_is_an_isolated_worker_contract() -> None:
    skill = (SKILLS / "wiki-source-text" / "SKILL.md").read_text(encoding="utf-8")
    adapter = (WORKFLOWS / "wiki-source-text.yaml").read_text(encoding="utf-8")

    assert BEGIN_MARKER not in skill
    assert END_MARKER not in skill
    for behavior in (
        "canonical Job directory",
        "exact `source_id`",
        "exact `unit_id`",
        "text-chunk-read",
        "whole-source `content_hash`",
        "references/extraction-frame.md",
        "validate_packet",
        "Do not modify `job.json`",
        "never call `wiki-packet-integrate`",
    ):
        assert behavior in skill
    assert "fresh isolated subagent" in adapter
    assert "明确要求读取并执行 `wiki-source-text` skill" in adapter
    assert "不得在 adapter 内降级读取 source 或执行 extraction" in adapter
    assert adapter.count("  - id:") == 1
    assert "obsidian-wiki text-chunk-read" not in adapter


def test_sync_checker_reports_clean_repository_contracts() -> None:
    result = subprocess.run(
        [sys.executable, "tools/sync_workflow_skills.py", "--check"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "workflow/skill parity OK" in result.stdout
