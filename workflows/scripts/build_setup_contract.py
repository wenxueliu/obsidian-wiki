#!/usr/bin/env python3
"""Build frozen Wiki setup contracts from packaged authoring templates."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
from apply_wiki_layout import inventory as layout_inventory


TEMPLATE_RULES = {
    "WRITING.md": set(),
    "index.md": {"TIMESTAMP", "INDEX_SECTIONS"},
    "log.md": {"TIMESTAMP", "VAULT_PATH", "CATEGORY_LIST"},
    "hot.md": {"TIMESTAMP", "VAULT_PATH"},
    "manifest.json": set(),
    "app.json": set(),
    "appearance.json": set(),
}
TEMPLATE_TARGETS = {
    "WRITING.md": "<GLOBAL_CONFIG_DIR>/WRITING.md",
    "index.md": "index.md",
    "log.md": "log.md",
    "hot.md": "hot.md",
    "manifest.json": ".manifest.json",
    "app.json": ".obsidian/app.json",
    "appearance.json": ".obsidian/appearance.json",
}
PLACEHOLDER = re.compile(r"\{\{([A-Z][A-Z0-9_]*)\}\}")
DEFAULT_CATEGORIES = ["concepts", "entities", "skills", "references", "synthesis", "journal"]
DEFAULT_INDEX_SECTIONS = """## Concepts

*No pages yet. Use `wiki-folder-ingest` to add your first source.*

## Entities

## Skills

## References

## Synthesis

## Journal"""


def sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(content)
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_markdown(name: str, text: str) -> None:
    if name == "WRITING.md":
        if not text.startswith("# Wiki Writing Profile\n"):
            raise ValueError("WRITING.md must start with its canonical heading")
        return
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise ValueError(f"{name} must contain YAML frontmatter")
    expected = {"index.md": "# Wiki Index", "log.md": "# Wiki Log", "hot.md": "# Hot Cache"}[name]
    if expected not in text:
        raise ValueError(f"{name} is missing {expected}")


def render(text: str, values: dict[str, str]) -> str:
    result = text
    for key, value in values.items():
        result = result.replace("{{" + key + "}}", value)
    remaining = PLACEHOLDER.findall(result)
    if remaining:
        raise ValueError(f"unresolved placeholders: {', '.join(sorted(set(remaining)))}")
    return result


def build_core(templates_dir: Path, layouts_dir: Path, output_dir: Path) -> None:
    templates: dict[str, Any] = {}
    for name, allowed in TEMPLATE_RULES.items():
        path = templates_dir / name
        data = path.read_bytes()
        text = data.decode("utf-8")
        found = set(PLACEHOLDER.findall(text))
        if found != allowed:
            raise ValueError(f"{name} placeholders {sorted(found)} != expected {sorted(allowed)}")
        if name.endswith(".json"):
            load_json(path)
        else:
            validate_markdown(name, text)
        templates[name] = {
            "source": str(path), "target": TEMPLATE_TARGETS[name],
            "sha256": sha256(data), "content": text,
            "allowed_placeholders": sorted(allowed),
        }

    default_values = {
        "TIMESTAMP": "TIMESTAMP",
        "VAULT_PATH": "OBSIDIAN_VAULT_PATH",
        "CATEGORY_LIST": ",".join(DEFAULT_CATEGORIES),
        "INDEX_SECTIONS": DEFAULT_INDEX_SECTIONS,
    }
    default_rendered = {
        name: render(record["content"], default_values)
        for name, record in templates.items()
    }
    layouts = {
        path.name: layout_inventory(layouts_dir, path.name)
        for path in sorted(layouts_dir.iterdir()) if path.is_dir()
    }
    if "default" not in layouts:
        raise ValueError("layouts directory must contain a default layout")

    core = {
        "version": 1,
        "config_defaults": {
            "OBSIDIAN_VAULT_PATH": "~/Documents/obsidian-wiki-vault",
            "OBSIDIAN_SOURCES_DIR": "~/Documents",
            "CLAUDE_HISTORY_PATH": "auto-discover ~/.claude",
            "QMD_TRANSPORT": "mcp",
            "QMD_CLI_SEARCH_MODE": "quality",
            "QMD_WIKI_COLLECTION": None,
            "QMD_PAPERS_COLLECTION": None,
            "WIKI_TOKEN_WARN_THRESHOLD": 100000,
            "WIKI_STAGED_WRITES": False,
            "WIKI_FOLDER_INGEST_MAX_EXTRACTION_WORKERS": 4,
            "WIKI_TEXT_DIRECT_EXTRACT_MAX_BYTES": 16000,
            "WIKI_TEXT_CHUNK_TARGET_BYTES": 48000,
            "WIKI_TEXT_CHUNK_MIN_BYTES": 24000,
            "WIKI_TEXT_CHUNK_HARD_MAX_BYTES": 64000,
            "WIKI_TEXT_CHUNK_STRATEGY": "adaptive_sections",
            "WIKI_TEXT_CHUNK_OPTIONS": {},
        },
        "writing_profile": {
            "unix_path": "~/.obsidian-wiki/WRITING.md",
            "windows_path": "~/.obsidian-wiki/WRITING.md",
            "create_only_when_missing": True,
            "template": "WRITING.md",
        },
        "layout": {
            "implementation": "load one bundled Knowledge Pack; recursively copy layouts/<name>/vault with missing-only semantics; bind profile.json and routing.json/routing.md hashes in _meta/layout.json",
            "default": "default",
            "available": layouts,
            "default_dirs": layouts["default"]["directories"],
            "always_create": [".obsidian/", "_staging/"],
            "preserve_custom_dirs": True,
            "profile_policy": "profile.json defines the vault purpose, scope, knowledge types, extraction policy, evidence checks, freshness triggers, and retrieval priorities; scope mismatch follows the profile action instead of switching domains",
            "routing_policy": "the model selects a profile-compatible declared page type using routing.md; resolve_wiki_route.py validates and expands routing.json; workflows must not hard-code layout directories",
            "purposes": {
                "projects/": "per-project knowledge",
                "_archives/": "rebuild and restore snapshots",
                "_raw/": "unprocessed drafts",
                "_staging/": "staged-write review queue",
                "_meta/": "trust, taxonomy and dashboard metadata",
                "_readouts/": "narrative readouts"
            },
        },
        "templates": templates,
        "default_render_values": default_values,
        "default_rendered": default_rendered,
        "repair_policy": "minimal repair only; preserve owner frontmatter, history, unknown JSON keys and manifest data",
        "config_policy": "create a missing .env from frozen defaults and user choices; repair read-modify-write while preserving comments, unknown fields and existing values",
        "write_policy": "validate sibling candidate then atomically replace; timestamps must be timezone-aware",
    }
    payload = json.dumps(core, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    core["core_contract_hash"] = sha256(payload)
    atomic_write(output_dir / "setup-core-contract.json", json.dumps(core, ensure_ascii=False, indent=2) + "\n")

    lines = ["# Wiki Setup Core Contract", "", f"Core hash: `{core['core_contract_hash']}`", ""]
    for name, record in templates.items():
        lines.extend([f"## `{name}`", "", f"Template hash: `{record['sha256']}`", "", "```", record["content"].rstrip("\n"), "```", ""])
    atomic_write(output_dir / "setup-core-contract.md", "\n".join(lines))


def finalize(templates_dir: Path, layouts_dir: Path, output_dir: Path) -> None:
    core_path = output_dir / "setup-core-contract.json"
    core = load_json(core_path)
    integration_path = templates_dir / "integrations.json"
    integrations = load_json(integration_path)
    contract = dict(core)
    contract["integrations"] = integrations
    contract["integration_source"] = {"path": str(integration_path), "sha256": sha256(integration_path.read_bytes())}
    payload = json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    contract["contract_hash"] = sha256(payload)
    atomic_write(output_dir / "setup-contract.json", json.dumps(contract, ensure_ascii=False, indent=2) + "\n")

    core_md = (output_dir / "setup-core-contract.md").read_text(encoding="utf-8").rstrip()
    integration_json = json.dumps(integrations, ensure_ascii=False, indent=2)
    final_md = f"{core_md}\n\n# Optional Integrations and Handoff\n\nIntegration hash: `{contract['integration_source']['sha256']}`\n\n```json\n{integration_json}\n```\n\nFinal contract hash: `{contract['contract_hash']}`\n"
    atomic_write(output_dir / "setup-contract.md", final_md)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("core", "finalize"))
    parser.add_argument("--templates-dir", required=True, type=Path)
    parser.add_argument("--layouts-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.phase == "core":
            build_core(args.templates_dir, args.layouts_dir, args.output_dir)
        else:
            finalize(args.templates_dir, args.layouts_dir, args.output_dir)
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.exit(1, f"build_setup_contract.py: error: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
