#!/usr/bin/env python3
"""Generate Agent Skill contracts from top-level workflow YAML files.

Most generated skills embed their workflow byte-for-byte.  Curated skills are
maintained as agent-native instructions and intentionally excluded from this
mechanical sync.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS_DIR = ROOT / "workflows"
SKILLS_DIR = ROOT / ".skills"
BEGIN_MARKER = "<!-- BEGIN GENERATED WORKFLOW CONTRACT -->"
END_MARKER = "<!-- END GENERATED WORKFLOW CONTRACT -->"
CURATED_SKILLS = {"wiki-folder-ingest"}


def workflow_description(workflow_text: str, path: Path) -> str:
    first_line = workflow_text.splitlines()[0] if workflow_text else ""
    prefix = "description:"
    if not first_line.startswith(prefix):
        raise ValueError(f"{path}: first line must be a scalar description")
    description = first_line[len(prefix) :].strip()
    if not description:
        raise ValueError(f"{path}: description must not be empty")
    return description


def render_skill(workflow_path: Path) -> str:
    name = workflow_path.stem
    workflow_text = workflow_path.read_text(encoding="utf-8")
    if not workflow_text.endswith("\n"):
        workflow_text += "\n"
    description = workflow_description(workflow_text, workflow_path)

    return (
        "---\n"
        f"name: {name}\n"
        f"description: {json.dumps(description, ensure_ascii=False)}\n"
        "---\n\n"
        f"# {name}\n\n"
        f"此 skill 直接执行下方从 `workflows/{workflow_path.name}` 同步的完整契约。"
        "内嵌 YAML 是实际指令，不是摘要或外部参考；按 `steps`、输入输出、检查、"
        "跳转、失败上限和人工审批要求逐项执行。\n\n"
        "发生任何冲突时，以内嵌 workflow 契约为准。不要用历史 skill 文案补写、"
        "弱化或覆盖它。修改行为时先编辑 workflow，再运行 "
        "`python tools/sync_workflow_skills.py`。\n\n"
        f"{BEGIN_MARKER}\n"
        "````yaml\n"
        f"{workflow_text}"
        "````\n"
        f"{END_MARKER}\n"
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
        description="Synchronize generated Agent Skills from authoritative workflows."
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
                print(
                    "run: python tools/sync_workflow_skills.py",
                    file=sys.stderr,
                )
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
