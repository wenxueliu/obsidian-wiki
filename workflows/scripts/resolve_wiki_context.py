#!/usr/bin/env python3
"""Resolve deterministic, non-secret runtime context for Wiki workflows."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
from apply_wiki_layout import inventory as layout_inventory

BOOL_KEYS = {"WIKI_STAGED_WRITES"}


def parse_bool(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    raise ValueError(f"boolean value must be true or false, got: {value!r}")


def parse_config(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def walk_config(source_cwd: Path, requested: set[str]) -> tuple[Path | None, dict[str, str]]:
    relevant = requested - {"OBSIDIAN_VAULT_PATH"}
    if not relevant:
        return None, {}
    current = source_cwd.resolve()
    home = Path.home().resolve()
    while True:
        candidate = current / ".env"
        if candidate.is_file():
            values = parse_config(candidate)
            if relevant.intersection(values):
                return candidate, values
        if current == current.parent or current == home:
            break
        current = current.parent

    base = Path(os.environ.get("LOCALAPPDATA", "")) if os.name == "nt" else home
    global_config = base / ".obsidian-wiki" / "config"
    if global_config.is_file():
        return global_config, parse_config(global_config)
    return None, {}


def csv_set(value: str) -> set[str]:
    return {item.strip() for item in value.split(",") if item.strip()}


def canonical_path(value: str) -> Path:
    expanded = Path(value).expanduser()
    if not expanded.is_absolute():
        raise ValueError("vault path must be absolute")
    return expanded.resolve(strict=False)


def write_outputs(output_dir: Path, context: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "wiki-context.json").write_text(
        json.dumps(context, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# Wiki Context", "",
        f"- Mode: `{context['mode']}`",
        f"- Vault: `{context.get('vault_path', '')}`",
        f"- Config source: `{context.get('config_source') or 'none'}`",
        f"- Setup mode: `{str(context.get('setup_mode', False)).lower()}`",
        f"- Write mode: `{context.get('write_mode', 'direct')}`",
    ]
    if context.get("reason"):
        lines.append(f"- Reason: {context['reason']}")
    active_layout = context.get("optional_metadata", {}).get("active_layout")
    if active_layout:
        lines.append(f"- Active layout: `{active_layout.get('name', 'unknown')}` ({active_layout.get('status', 'unknown')})")
    warnings = context.get("warnings", [])
    if warnings:
        lines.extend(["", "## Warnings", "", *[f"- {warning}" for warning in warnings]])
    lines.extend(["", "## Retrieval order", "", *[
        f"{index}. {value}" for index, value in enumerate(context.get("retrieval_order", []), 1)
    ]])
    (output_dir / "wiki-context.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--source-cwd", required=True, type=Path)
    parser.add_argument("--requested-keys", default="")
    parser.add_argument("--optional-reads", default="")
    parser.add_argument("--setup-mode", choices=("true", "false"), default="false")
    parser.add_argument("--layouts-dir", type=Path, default=Path(__file__).resolve().parent.parent / "layouts")
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    try:
        supplied = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(supplied, dict):
            raise ValueError("vault input must be a JSON object")
        setup_mode = args.setup_mode == "true"
        if supplied.get("mode") == "skipped":
            write_outputs(args.output_dir, {
                "version": 1, "mode": "skipped",
                "reason": str(supplied.get("reason", "run condition was false")),
                "evidence": supplied.get("evidence"), "setup_mode": setup_mode,
                "requested_values": {}, "retrieval_order": [], "warnings": [],
            })
            return 0

        vault = canonical_path(str(supplied.get("vault_path", "")))
        if not setup_mode and not vault.is_dir():
            raise ValueError(f"vault does not exist or is not a directory: {vault}")
        requested = csv_set(args.requested_keys)
        optional_reads = csv_set(args.optional_reads)
        config_path, config_values = walk_config(args.source_cwd, requested)
        overrides = supplied.get("overrides", {})
        if not isinstance(overrides, dict):
            raise ValueError("overrides must be a JSON object")

        values: dict[str, Any] = {}
        for key in requested:
            if key == "OBSIDIAN_VAULT_PATH":
                values[key] = str(vault)
                continue
            raw = overrides.get(key, config_values.get(key))
            if raw is not None:
                values[key] = parse_bool(str(raw)) if key in BOOL_KEYS else raw

        owner_path = vault / "AGENTS.md"
        owner_rules = owner_path.read_text(encoding="utf-8") if owner_path.is_file() else None
        base = Path(os.environ.get("LOCALAPPDATA", "")) if os.name == "nt" else Path.home()
        writing_path = base / ".obsidian-wiki" / "WRITING.md"
        writing_profile = writing_path.read_text(encoding="utf-8") if writing_path.is_file() else None
        optional_targets = {
            "taxonomy": vault / "_meta" / "taxonomy.md", "index": vault / "index.md",
            "hot": vault / "hot.md", "manifest": vault / ".manifest.json",
        }
        optional_metadata: dict[str, Any] = {}
        context_warnings: list[str] = []
        def wants(name: str) -> bool:
            return any(name in item for item in optional_reads)

        for name, path in optional_targets.items():
            if wants(name) and path.is_file():
                stat = path.stat()
                optional_metadata[name] = {"path": str(path), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
        if wants("active layout"):
            marker_path = vault / "_meta" / "layout.json"
            if not vault.is_dir() or not marker_path.is_file():
                optional_metadata["active_layout"] = {
                    "status": "uninitialized" if setup_mode else "missing",
                    "marker_path": str(marker_path),
                }
                if not setup_mode:
                    context_warnings.append("active layout marker is missing; run wiki-setup repair before writing pages")
            else:
                if marker_path.is_symlink():
                    raise ValueError("active layout marker must not be a symlink")
                marker = json.loads(marker_path.read_text(encoding="utf-8"))
                if not isinstance(marker, dict) or marker.get("version") != 1 or not isinstance(marker.get("name"), str):
                    raise ValueError("active layout marker is invalid")
                frozen = layout_inventory(args.layouts_dir, marker["name"])
                expected = {
                    "manifest_sha256": frozen["manifest_sha256"],
                    "inventory_sha256": frozen["inventory_sha256"],
                    "routing_rules_sha256": frozen["routing"]["rules_sha256"],
                    "routing_prompt_sha256": frozen["routing"]["prompt_sha256"],
                }
                mismatches = [key for key, value in expected.items() if marker.get(key) != value]
                status = "matched" if not mismatches else "stale"
                if mismatches:
                    context_warnings.append(
                        "active layout contract is stale (" + ", ".join(mismatches) + "); run an explicit layout repair or migration before writing pages"
                    )
                optional_metadata["active_layout"] = {
                    "status": status, "name": frozen["name"], "version": frozen["version"],
                    "marker_path": str(marker_path), "marker": marker,
                    "categories": frozen["categories"], "directories": frozen["directories"],
                    "routing": frozen["routing"],
                }
        if wants("vault metadata") and vault.exists():
            stat = vault.stat()
            optional_metadata["vault"] = {"path": str(vault), "mtime_ns": stat.st_mtime_ns}
        if wants("QMD collection metadata"):
            qmd_index = Path.home() / ".config" / "qmd" / "index.yml"
            optional_metadata["qmd_collections"] = {
                "index_path": str(qmd_index), "index_exists": qmd_index.is_file()
            }

        context = {
            "version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
            "mode": "interactive", "vault_path": str(vault),
            "source_cwd": str(args.source_cwd.resolve()),
            "config_source": str(config_path) if config_path else None,
            "requested_values": values, "setup_mode": setup_mode,
            "write_mode": "staged" if values.get("WIKI_STAGED_WRITES") is True else "direct",
            "link_format": values.get("OBSIDIAN_LINK_FORMAT", "wikilink"),
            "qmd": {"available": shutil.which("qmd") is not None,
                    "transport": values.get("QMD_TRANSPORT"),
                    "wiki_collection": values.get("QMD_WIKI_COLLECTION"),
                    "papers_collection": values.get("QMD_PAPERS_COLLECTION"),
                    "search_mode": values.get("QMD_CLI_SEARCH_MODE")},
            "owner_rules": {"path": str(owner_path), "content": owner_rules} if owner_rules is not None else None,
            "writing_profile": {"path": str(writing_path), "content": writing_profile} if writing_profile is not None else None,
            "optional_metadata": optional_metadata,
            "retrieval_order": ["index/frontmatter", "summary", "anchored rg section context", "whole page last"],
            "warnings": [f"{key} is not configured" for key in requested - {"OBSIDIAN_VAULT_PATH"} if key not in values] + context_warnings,
        }
        write_outputs(args.output_dir, context)
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.exit(1, f"resolve_wiki_context.py: error: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
