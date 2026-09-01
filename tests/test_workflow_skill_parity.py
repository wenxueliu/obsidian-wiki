from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / "workflows"
SKILLS = ROOT / ".skills"
BEGIN_MARKER = "<!-- BEGIN GENERATED SKILL INSTRUCTIONS -->"
END_MARKER = "<!-- END GENERATED SKILL INSTRUCTIONS -->"
CURATED_SKILLS = {"wiki-folder-ingest", "wiki-source-text"}


def load_sync_module():
    spec = importlib.util.spec_from_file_location(
        "sync_workflow_skills", ROOT / "tools" / "sync_workflow_skills.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_top_level_workflow_has_a_matching_skill() -> None:
    missing = [
        workflow.stem
        for workflow in sorted(WORKFLOWS.glob("*.yaml"))
        if not (SKILLS / workflow.stem / "SKILL.md").is_file()
    ]
    assert missing == []


def test_matching_skills_render_the_authoritative_workflow_as_markdown() -> None:
    sync_module = load_sync_module()
    for workflow in sorted(WORKFLOWS.glob("*.yaml")):
        if workflow.stem in CURATED_SKILLS:
            continue
        skill = (SKILLS / workflow.stem / "SKILL.md").read_text(encoding="utf-8")
        assert skill.count(BEGIN_MARKER) == 1, workflow.name
        assert skill.count(END_MARKER) == 1, workflow.name
        assert skill == sync_module.render_skill(workflow), workflow.name
        assert "````yaml" not in skill, workflow.name
        assert "\n    do:" not in skill, workflow.name
        assert "\n    input:" not in skill, workflow.name
        assert "\n    output:" not in skill, workflow.name
        assert "\n    check:" not in skill, workflow.name
        assert "#### 执行" in skill, workflow.name
        assert "#### 输入" in skill, workflow.name
        assert "#### 产出" in skill, workflow.name
        assert "#### 验收" in skill, workflow.name


def test_wiki_setup_renders_every_step_and_approval_gate() -> None:
    sync_module = load_sync_module()
    workflow_path = WORKFLOWS / "wiki-setup.yaml"
    contract = sync_module.parse_workflow(
        workflow_path.read_text(encoding="utf-8"), workflow_path
    )
    skill = (SKILLS / "wiki-setup" / "SKILL.md").read_text(encoding="utf-8")

    assert "人工审批步骤：`approve_setup`" in skill
    assert skill.count("#### 输入") == len(contract["steps"])
    assert skill.count("#### 产出") == len(contract["steps"])
    assert skill.count("#### 验收") == len(contract["steps"])
    for step in contract["steps"]:
        assert f"(`{step['id']}`)" in skill
        assert step["input"] in skill
        assert step["output"] in skill


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
        "所有 integration 均不并发",
        "wiki-finalize-sources",
        "obsidian-wiki text-ingest-report",
        "本 skill 不调用它",
        "<promise>done</promise>",
    ):
        assert behavior in skill


def test_lightweight_wiki_ingest_is_skill_only() -> None:
    skill = (SKILLS / "wiki-ingest" / "SKILL.md").read_text(encoding="utf-8")

    assert not (WORKFLOWS / "wiki-ingest.yaml").exists()
    for behavior in (
        "本 skill 不依赖 workflow",
        "obsidian-wiki text-document-plan",
        "obsidian-wiki text-document-run",
        "wiki-ingest-document",
        "Wiki writes 严格串行",
        "text-document-commit",
        "不创建 Job、unit 状态机、Packet",
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
    assert "claude -p --dangerously-skip-permissions" in adapter
    assert "直接调用 `/wiki-source-text`" in adapter
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
