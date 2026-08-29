from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = (
    ROOT / "workflows" / "wiki-context.yaml",
    ROOT / "workflows" / "wiki-setup-contract.yaml",
    ROOT / "workflows" / "wiki-setup.yaml",
)
VALIDATION_TERMS = ("验证", "校验", "检查", "核对", "审计", "重算")


def test_workflow_agents_codifies_producer_verifier_boundary() -> None:
    instructions = (ROOT / "workflows" / "AGENTS.md").read_text(encoding="utf-8")

    assert "Step 单一职责" in instructions
    assert "`do` 是 Producer" in instructions
    assert "`check` 是 Verifier" in instructions
    assert "每个包含本地 `do` 的 step 必须提供 `check` 或 `check_voting`" in instructions
    assert "不得通过再次运行同一个生成器" in instructions


def step_blocks(text: str) -> list[str]:
    starts = [match.start() for match in re.finditer(r"^  - id: ", text, re.MULTILINE)]
    return [
        text[start : starts[index + 1] if index + 1 < len(starts) else len(text)]
        for index, start in enumerate(starts)
    ]


def do_body(step: str) -> str | None:
    match = re.search(
        r"^    do: \|\n(?P<body>(?:(?:^      .*\n)|(?:^\n))*)",
        step,
        re.MULTILINE,
    )
    return match.group("body") if match else None


def test_do_blocks_generate_and_checks_validate() -> None:
    for path in WORKFLOWS:
        for step in step_blocks(path.read_text(encoding="utf-8")):
            body = do_body(step)
            if body is None:
                # Delegated workflow steps own their checks inside the child workflow.
                assert "    workflow:" in step
                continue
            assert "    check:" in step or "    check_voting:" in step
            for term in VALIDATION_TERMS:
                assert term not in body, f"{path.name} do block contains validation term {term}"


def test_setup_splits_independent_mutation_responsibilities() -> None:
    workflow = (ROOT / "workflows" / "wiki-setup.yaml").read_text(encoding="utf-8")
    ids = set(re.findall(r"^  - id: ([a-z0-9_]+)$", workflow, re.MULTILINE))

    assert {"scaffold_vault", "optional_integrations", "verify_setup"}.isdisjoint(ids)
    assert {
        "write_config",
        "initialize_writing_profile",
        "apply_layout",
        "initialize_core",
        "configure_stop_hook",
        "configure_git_sync",
        "configure_qmd_collection",
        "refresh_qmd_index",
        "render_setup_completion",
    }.issubset(ids)


def test_setup_chain_uses_single_concise_checks() -> None:
    for name in ("wiki-context.yaml", "wiki-setup-contract.yaml", "wiki-setup.yaml"):
        workflow = (ROOT / "workflows" / name).read_text(encoding="utf-8")
        assert "check_voting:" not in workflow
        for step in step_blocks(workflow):
            match = re.search(r"^    check: (?P<check>.+)$", step, re.MULTILINE)
            if match:
                assert len(match.group("check")) <= 260

    setup = (ROOT / "workflows" / "wiki-setup.yaml").read_text(encoding="utf-8")
    assert "obsidian-wiki doctor" not in setup


def test_workflow_transitions_target_declared_steps_or_done() -> None:
    for path in WORKFLOWS:
        text = path.read_text(encoding="utf-8")
        ids = set(re.findall(r"^  - id: ([a-z0-9_]+)$", text, re.MULTILINE))
        targets = set(re.findall(r"^    on_(?:pass|fail): ([a-z0-9_]+)$", text, re.MULTILINE))
        assert targets <= ids | {"done"}
