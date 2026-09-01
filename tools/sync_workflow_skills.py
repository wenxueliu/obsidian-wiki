#!/usr/bin/env python3
"""Render top-level workflow YAML files as agent-native Markdown skills.

The workflow remains the behavior source of truth. Generated skills translate its
small, deliberately constrained schema into direct Markdown instructions instead
of asking an agent to interpret an embedded YAML document at runtime.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS_DIR = ROOT / "workflows"
SKILLS_DIR = ROOT / ".skills"
BEGIN_MARKER = "<!-- BEGIN GENERATED SKILL INSTRUCTIONS -->"
END_MARKER = "<!-- END GENERATED SKILL INSTRUCTIONS -->"
CURATED_SKILLS = {"wiki-folder-ingest", "wiki-source-text"}

TOP_LEVEL_KEYS = {"description", "auto_reset", "manual_step", "adversarial_check", "steps"}
STEP_KEYS = {
    "id",
    "desc",
    "workflow",
    "input",
    "inputs",
    "output",
    "do",
    "check",
    "check_voting",
    "on_pass",
    "on_fail",
    "max_fail_count",
}


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return json.loads(value)
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    return value


def _dedent_block(lines: list[str], amount: int) -> str:
    prefix = " " * amount
    result = [line[amount:] if line.startswith(prefix) else line for line in lines]
    return "\n".join(result).rstrip()


def _parse_step(lines: list[str], path: Path) -> dict[str, Any]:
    step: dict[str, Any] = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        match = re.match(r"^    ([a-z_]+):(.*)$", line)
        if not match:
            raise ValueError(f"{path}: unsupported step syntax: {line!r}")
        key, raw_value = match.group(1), match.group(2).strip()
        if key not in STEP_KEYS:
            raise ValueError(f"{path}: unsupported step key: {key}")
        index += 1
        nested: list[str] = []
        while index < len(lines) and not re.match(r"^    [a-z_]+:", lines[index]):
            nested.append(lines[index])
            index += 1

        if raw_value == "|":
            step[key] = _dedent_block(nested, 6)
        elif key == "inputs":
            values: dict[str, str] = {}
            nested_index = 0
            while nested_index < len(nested):
                nested_line = nested[nested_index]
                if not nested_line.strip():
                    nested_index += 1
                    continue
                nested_match = re.match(r"^      ([a-z_]+):\s*(.*)$", nested_line)
                if not nested_match:
                    raise ValueError(f"{path}: unsupported inputs syntax: {nested_line!r}")
                input_key, input_value = nested_match.group(1), nested_match.group(2)
                nested_index += 1
                if input_value == "|":
                    block: list[str] = []
                    while nested_index < len(nested) and not re.match(
                        r"^      [a-z_]+:", nested[nested_index]
                    ):
                        block.append(nested[nested_index])
                        nested_index += 1
                    values[input_key] = _dedent_block(block, 8)
                else:
                    values[input_key] = _unquote(input_value)
            step[key] = values
        elif key == "check_voting":
            checks: list[str] = []
            for nested_line in nested:
                if not nested_line.strip():
                    continue
                nested_match = re.match(r"^      - check:\s*(.*)$", nested_line)
                if not nested_match:
                    raise ValueError(f"{path}: unsupported check_voting syntax: {nested_line!r}")
                checks.append(_unquote(nested_match.group(1)))
            step[key] = checks
        else:
            if nested:
                raise ValueError(f"{path}: unexpected nested content for {key}")
            step[key] = _unquote(raw_value)

    missing = {"id", "desc", "input", "output", "on_pass", "on_fail", "max_fail_count"} - step.keys()
    if missing:
        raise ValueError(f"{path}: step is missing keys: {', '.join(sorted(missing))}")
    if "do" not in step and "workflow" not in step:
        raise ValueError(f"{path}: step {step['id']} needs do or workflow")
    if "check" not in step and "check_voting" not in step and "workflow" not in step:
        raise ValueError(f"{path}: step {step['id']} needs check/check_voting")
    return step


def parse_workflow(workflow_text: str, path: Path) -> dict[str, Any]:
    """Parse the intentionally small workflow schema without a runtime YAML dependency."""
    lines = workflow_text.splitlines()
    top_keys = {
        match.group(1)
        for line in lines
        if (match := re.match(r"^([a-z_]+):", line))
    }
    unknown = top_keys - TOP_LEVEL_KEYS
    if unknown:
        raise ValueError(f"{path}: unsupported top-level keys: {', '.join(sorted(unknown))}")

    description_match = re.search(r"^description:\s*(.+)$", workflow_text, re.MULTILINE)
    if not description_match:
        raise ValueError(f"{path}: description must be a non-empty scalar")
    auto_reset_match = re.search(r"^auto_reset:\s*(true|false)$", workflow_text, re.MULTILINE)
    if not auto_reset_match:
        raise ValueError(f"{path}: auto_reset must be true or false")

    manual_steps: list[str] = []
    manual_match = re.search(
        r"^manual_step:\n(?P<body>(?:  - .+\n)+)", workflow_text, re.MULTILINE
    )
    if manual_match:
        manual_steps = [
            _unquote(line.removeprefix("  - "))
            for line in manual_match.group("body").splitlines()
        ]

    audit_match = re.search(
        r"^adversarial_check:\n"
        r"  timeout_ms:\s*(?P<timeout>\d+)\n"
        r"  system_prompt:\s*\|\n"
        r"(?P<prompt>(?:(?:    .*|)\n)+?)"
        r"(?=\nsteps:)",
        workflow_text,
        re.MULTILINE,
    )
    if not audit_match:
        raise ValueError(f"{path}: unsupported adversarial_check syntax")

    step_matches = list(re.finditer(r"^  - id:\s*(.+)$", workflow_text, re.MULTILINE))
    if not step_matches:
        raise ValueError(f"{path}: workflow must contain steps")
    steps: list[dict[str, Any]] = []
    for position, match in enumerate(step_matches):
        end = step_matches[position + 1].start() if position + 1 < len(step_matches) else len(workflow_text)
        first_line = f"    id: {match.group(1)}"
        remainder = workflow_text[match.end() : end].strip("\n").splitlines()
        steps.append(_parse_step([first_line, *remainder], path))

    return {
        "description": _unquote(description_match.group(1)),
        "auto_reset": auto_reset_match.group(1) == "true",
        "manual_steps": manual_steps,
        "audit_timeout_ms": int(audit_match.group("timeout")),
        "audit_prompt": _dedent_block(audit_match.group("prompt").splitlines(), 4),
        "steps": steps,
    }


def _render_step(number: int, step: dict[str, Any]) -> str:
    parts = [f"### {number}. {step['desc']} (`{step['id']}`)"]

    if "workflow" in step:
        parts.extend(
            [
                "#### 执行",
                f"调用 `{step['workflow']}` skill，并把下列输入传给它。以被调用 skill 的验收结果作为本步骤结果。",
            ]
        )
    else:
        parts.extend(["#### 执行", step["do"]])

    parts.extend(["#### 输入", step["input"]])
    if step.get("inputs"):
        parts.append("调用参数：")
        parts.extend(f"- `{key}`: {value}" for key, value in step["inputs"].items())

    parts.extend(["#### 产出", step["output"]])
    if "check" in step:
        parts.extend(["#### 验收", step["check"]])
    elif "check_voting" in step:
        parts.append("#### 验收")
        parts.extend(f"{index}. {check}" for index, check in enumerate(step["check_voting"], 1))
    else:
        parts.extend(["#### 验收", "采用被调用 skill 的验收结论，不在本步骤重复验收。"])

    parts.extend(
        [
            "#### 流程控制",
            f"- 验收通过：转到 `{step['on_pass']}`。",
            f"- 验收失败：返回 `{step['on_fail']}`。",
            f"- 最多连续失败 `{step['max_fail_count']}` 次；达到上限后停止并报告阻塞。",
        ]
    )
    return "\n\n".join(parts)


def render_skill(workflow_path: Path) -> str:
    name = workflow_path.stem
    workflow_text = workflow_path.read_text(encoding="utf-8")
    workflow = parse_workflow(workflow_text, workflow_path)

    body = [
        BEGIN_MARKER,
        "## 执行规则",
        (
            "按下列步骤和流程控制执行。每个步骤只读取其声明的输入，只产生其声明的产出；"
            "执行与独立验收分开进行。修改行为时先编辑权威 workflow，再运行 "
            "`python tools/sync_workflow_skills.py`。"
        ),
        f"- 自动重置：{'开启' if workflow['auto_reset'] else '关闭'}。",
    ]
    if workflow["manual_steps"]:
        body.append("- 人工审批步骤：" + "、".join(f"`{item}`" for item in workflow["manual_steps"]) + "。")
    body.extend(
        [
            "## 独立验收规则",
            workflow["audit_prompt"],
            f"单次验收超时：`{workflow['audit_timeout_ms']}` 毫秒。",
            "## 工作流",
        ]
    )
    body.extend(_render_step(index, step) for index, step in enumerate(workflow["steps"], 1))
    body.append(END_MARKER)

    return (
        "---\n"
        f"name: {name}\n"
        f"description: {json.dumps(workflow['description'], ensure_ascii=False)}\n"
        "---\n\n"
        f"# {name}\n\n"
        f"此 skill 是 `workflows/{workflow_path.name}` 的 Agent Skill 格式投影；workflow 是行为事实来源，"
        "本文件把其字段渲染为可直接执行的 Markdown 指令。\n\n"
        + "\n\n".join(body)
        + "\n"
    )


def expected_skills() -> dict[Path, str]:
    return {
        SKILLS_DIR / workflow_path.stem / "SKILL.md": render_skill(workflow_path)
        for workflow_path in sorted(WORKFLOWS_DIR.glob("*.yaml"))
        if workflow_path.stem not in CURATED_SKILLS
    }


def check() -> list[str]:
    errors: list[str] = []
    for name in sorted(CURATED_SKILLS):
        skill_path = SKILLS_DIR / name / "SKILL.md"
        if not skill_path.is_file():
            errors.append(f"missing curated skill: {skill_path.relative_to(ROOT)}")
    for skill_path, expected in expected_skills().items():
        relative = skill_path.relative_to(ROOT)
        if not skill_path.is_file():
            errors.append(f"missing: {relative}")
            continue
        actual = skill_path.read_text(encoding="utf-8")
        if actual != expected:
            errors.append(f"out of sync: {relative}")
    return errors


def sync() -> list[Path]:
    changed: list[Path] = []
    for skill_path, expected in expected_skills().items():
        actual = skill_path.read_text(encoding="utf-8") if skill_path.exists() else None
        if actual == expected:
            continue
        skill_path.parent.mkdir(parents=True, exist_ok=True)
        skill_path.write_text(expected, encoding="utf-8")
        changed.append(skill_path)
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render authoritative workflows as generated Agent Skills."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report missing or stale generated skills without writing files",
    )
    args = parser.parse_args(argv)

    try:
        if args.check:
            errors = check()
            if errors:
                for error in errors:
                    print(error, file=sys.stderr)
                print("run: python tools/sync_workflow_skills.py", file=sys.stderr)
                return 1
            pair_count = len(expected_skills()) + len(CURATED_SKILLS)
            print(f"workflow/skill parity OK ({pair_count} pairs)")
            return 0

        changed = sync()
        for path in changed:
            print(f"synced: {path.relative_to(ROOT)}")
        errors = check()
        if errors:
            for error in errors:
                print(error, file=sys.stderr)
            return 1
        pair_count = len(expected_skills()) + len(CURATED_SKILLS)
        print(f"workflow/skill parity OK ({pair_count} pairs)")
        return 0
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
