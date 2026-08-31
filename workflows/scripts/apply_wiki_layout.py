#!/usr/bin/env python3
"""Validate, inventory, and missing-only copy packaged Knowledge Packs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from string import Formatter
from typing import Any

sys.dont_write_bytecode = True


MAX_FILES = 10_000
MAX_FILE_SIZE = 64 * 1024 * 1024
RESERVED_TARGETS = {
    "index.md", "log.md", "hot.md", ".manifest.json",
    ".obsidian/app.json", ".obsidian/appearance.json",
}
LAYOUT_MARKER = "_meta/layout.json"
SAFE_NAME = re.compile(r"^[A-Za-z0-9_-]+$")
SAFE_ROUTE_KEY = re.compile(r"^[a-z][a-z0-9_]*$")


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return "sha256:" + value.hexdigest()


def atomic_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def validate_relative_path(value: str, label: str) -> None:
    path = Path(value)
    if not value or path.is_absolute() or "\\" in value or any(part in ("", ".", "..") for part in path.parts):
        raise ValueError(f"{label} must be a safe relative POSIX path")


def validate_routing(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("routing rules must be a version 1 JSON object")
    placeholders = data.get("allowed_placeholders")
    if not isinstance(placeholders, list) or not all(SAFE_ROUTE_KEY.fullmatch(item or "") for item in placeholders):
        raise ValueError("allowed_placeholders must be a string array of safe names")
    allowed = set(placeholders)
    if len(allowed) != len(placeholders):
        raise ValueError("allowed_placeholders must not contain duplicates")
    routes = data.get("routes")
    if not isinstance(routes, dict) or not routes:
        raise ValueError("routing routes must be a non-empty object")
    for route_name, template in routes.items():
        if not isinstance(route_name, str) or not SAFE_ROUTE_KEY.fullmatch(route_name):
            raise ValueError(f"invalid route name: {route_name!r}")
        if not isinstance(template, str):
            raise ValueError(f"route {route_name!r} must be a string")
        validate_relative_path(template, f"route {route_name!r}")
        fields = {field for _, field, spec, conversion in Formatter().parse(template) if field}
        if fields - allowed or any(spec or conversion for _, field, spec, conversion in Formatter().parse(template) if field):
            raise ValueError(f"route {route_name!r} contains an unsupported placeholder or format modifier")
    fallback = data.get("fallback")
    if fallback not in routes:
        raise ValueError("routing fallback must name an existing route")
    for key in ("content_roots", "system_dirs", "skip_dirs", "system_paths"):
        values = data.get(key)
        if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
            raise ValueError(f"routing {key} must be a string array")
        for value in values:
            validate_relative_path(value, f"routing {key}")
    roots = set(data["content_roots"])
    if not roots:
        raise ValueError("routing content_roots must not be empty")
    system_dirs = set(data["system_dirs"])
    if roots & system_dirs:
        raise ValueError("routing content_roots and system_dirs must be disjoint")
    if not set(data["skip_dirs"]).issubset(system_dirs):
        raise ValueError("routing skip_dirs must be a subset of system_dirs")
    if LAYOUT_MARKER not in data["system_paths"]:
        raise ValueError(f"routing system_paths must reserve {LAYOUT_MARKER}")
    for route_name, template in routes.items():
        first = template.split("/", 1)[0]
        if first not in roots:
            raise ValueError(f"route {route_name!r} is outside content_roots")
    return data


def validate_string_list(value: Any, label: str, *, allow_empty: bool = False) -> list[str]:
    if (
        not isinstance(value, list)
        or (not allow_empty and not value)
        or not all(isinstance(item, str) and item.strip() for item in value)
    ):
        suffix = "" if allow_empty else " non-empty"
        raise ValueError(f"profile {label} must be a{suffix} string array")
    if len(value) != len(set(value)):
        raise ValueError(f"profile {label} must not contain duplicates")
    return value


def validate_profile(data: Any, name: str, routing: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict) or data.get("version") != 1 or data.get("name") != name:
        raise ValueError("profile version/name mismatch")
    if not isinstance(data.get("description"), str) or not data["description"].strip():
        raise ValueError("profile description must be a non-empty string")
    validate_string_list(data.get("purpose"), "purpose")
    scope = data.get("scope")
    if not isinstance(scope, dict) or scope.get("on_mismatch") not in {"ask", "stage", "reject"}:
        raise ValueError("profile scope must declare on_mismatch=ask|stage|reject")
    validate_string_list(scope.get("include"), "scope.include")
    validate_string_list(scope.get("exclude"), "scope.exclude", allow_empty=True)
    knowledge_types = validate_string_list(data.get("knowledge_types"), "knowledge_types")
    unknown_types = sorted(set(knowledge_types) - set(routing.get("routes", {})))
    if unknown_types:
        raise ValueError(
            "profile knowledge_types are missing layout routes: " + ", ".join(unknown_types)
        )
    for section, keys in {
        "extraction": ("retain", "omit"),
        "verification": ("authorities", "checks"),
        "freshness": ("triggers",),
        "retrieval": ("priorities",),
    }.items():
        value = data.get(section)
        if not isinstance(value, dict):
            raise ValueError(f"profile {section} must be an object")
        for key in keys:
            validate_string_list(value.get(key), f"{section}.{key}")
    return data


def load_layout(layouts_dir: Path, name: str) -> tuple[Path, Path, dict[str, Any]]:
    if not name or not SAFE_NAME.fullmatch(name):
        raise ValueError("layout name must match [A-Za-z0-9_-]+")
    root = layouts_dir.resolve() / name
    manifest_path = root / "layout.json"
    profile_path = root / "profile.json"
    vault_source = root / "vault"
    if (
        root.is_symlink()
        or manifest_path.is_symlink()
        or profile_path.is_symlink()
        or vault_source.is_symlink()
    ):
        raise ValueError("layout root, manifest, profile, and vault source must not be symlinks")
    if not manifest_path.is_file() or not profile_path.is_file() or not vault_source.is_dir():
        raise ValueError(f"layout {name!r} must contain layout.json, profile.json, and vault/")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("version") != 1 or manifest.get("name") != name:
        raise ValueError("layout manifest version/name mismatch")
    if manifest.get("copy_policy") != "missing-only":
        raise ValueError("only copy_policy=missing-only is supported")
    if manifest.get("profile") != "profile.json":
        raise ValueError("layout profile must reference profile.json")
    if manifest.get("core_template_overrides") not in ({}, None):
        raise ValueError("core_template_overrides are reserved for a future version")
    categories = manifest.get("categories")
    if not isinstance(categories, list) or not categories or not all(isinstance(item, str) and item for item in categories):
        raise ValueError("layout categories must be a non-empty string array")
    routing = manifest.get("routing")
    if routing != {"rules": "routing.json", "prompt": "routing.md"}:
        raise ValueError("layout routing must reference routing.json and routing.md")
    return root, vault_source, manifest


def load_routing(root: Path) -> tuple[dict[str, Any], str]:
    rules_path = root / "routing.json"
    prompt_path = root / "routing.md"
    if rules_path.is_symlink() or prompt_path.is_symlink() or not rules_path.is_file() or not prompt_path.is_file():
        raise ValueError("layout routing.json and routing.md must be regular non-symlink files")
    if rules_path.stat().st_size > MAX_FILE_SIZE or prompt_path.stat().st_size > MAX_FILE_SIZE:
        raise ValueError("layout routing file exceeds size limit")
    rules = validate_routing(json.loads(rules_path.read_text(encoding="utf-8")))
    prompt = prompt_path.read_text(encoding="utf-8")
    if not prompt.startswith("# ") or not prompt.strip():
        raise ValueError("routing.md must start with a Markdown heading")
    return rules, prompt


def load_profile(root: Path, name: str, routing: dict[str, Any]) -> dict[str, Any]:
    profile_path = root / "profile.json"
    if profile_path.is_symlink() or not profile_path.is_file():
        raise ValueError("layout profile.json must be a regular non-symlink file")
    if profile_path.stat().st_size > MAX_FILE_SIZE:
        raise ValueError("layout profile.json exceeds size limit")
    return validate_profile(json.loads(profile_path.read_text(encoding="utf-8")), name, routing)


def inventory(layouts_dir: Path, name: str) -> dict[str, Any]:
    root, vault_source, manifest = load_layout(layouts_dir, name)
    routing_rules, routing_prompt = load_routing(root)
    profile = load_profile(root, name, routing_rules)
    ignored = set(manifest.get("ignore", []))
    directories: list[str] = []
    files: list[dict[str, Any]] = []
    for candidate in sorted(vault_source.rglob("*")):
        if candidate.is_symlink():
            raise ValueError(f"layout contains symlink: {candidate}")
        relative = candidate.relative_to(vault_source).as_posix()
        if candidate.is_dir():
            directories.append(relative + "/")
            continue
        if not candidate.is_file() or candidate.name in ignored:
            continue
        if relative in RESERVED_TARGETS:
            raise ValueError(f"layout contains reserved core target: {relative}")
        size = candidate.stat().st_size
        if size > MAX_FILE_SIZE:
            raise ValueError(f"layout file exceeds {MAX_FILE_SIZE} bytes: {relative}")
        files.append({"path": relative, "size": size, "sha256": digest(candidate)})
    if len(files) > MAX_FILES:
        raise ValueError(f"layout contains more than {MAX_FILES} files")
    manifest_bytes = (root / "layout.json").read_bytes()
    frozen = {
        "version": 1, "name": name, "description": manifest.get("description", ""),
        "copy_policy": "missing-only", "categories": manifest["categories"],
        "manifest_path": str(root / "layout.json"),
        "manifest_sha256": "sha256:" + hashlib.sha256(manifest_bytes).hexdigest(),
        "directories": directories, "files": files, "ignored": sorted(ignored),
        "routing": {
            "rules_path": str(root / "routing.json"),
            "rules_sha256": digest(root / "routing.json"),
            "rules": routing_rules,
            "prompt_path": str(root / "routing.md"),
            "prompt_sha256": digest(root / "routing.md"),
            "prompt": routing_prompt,
        },
        "profile": {
            "path": str(root / "profile.json"),
            "sha256": digest(root / "profile.json"),
            "contract": profile,
        },
    }
    portable_inventory = {
        key: value for key, value in frozen.items() if key != "manifest_path"
    }
    portable_inventory["routing"] = {
        key: value for key, value in frozen["routing"].items()
        if key not in ("rules_path", "prompt_path")
    }
    portable_inventory["profile"] = {
        key: value for key, value in frozen["profile"].items() if key != "path"
    }
    frozen["inventory_sha256"] = "sha256:" + hashlib.sha256(
        json.dumps(portable_inventory, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return frozen


def safe_target(vault: Path, relative: str) -> Path:
    target = vault / Path(relative)
    root = vault.resolve(strict=False)
    resolved = target.resolve(strict=False)
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"target escapes vault: {relative}")
    return target


def copy_missing(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}-", suffix=".tmp", dir=target.parent)
    os.close(fd)
    try:
        shutil.copyfile(source, temporary)
        os.chmod(temporary, source.stat().st_mode & 0o777)
        os.replace(temporary, target)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def plan_or_apply(
    layouts_dir: Path, name: str, vault: Path, output_dir: Path, apply: bool,
    refresh_layout_marker: bool = False,
) -> None:
    frozen = inventory(layouts_dir, name)
    _, source_root, _ = load_layout(layouts_dir, name)
    vault = vault.expanduser()
    if not vault.is_absolute():
        raise ValueError("vault path must be absolute")
    if vault.is_symlink():
        raise ValueError("vault root must not be a symlink")
    vault = vault.resolve(strict=False)
    created_dirs: list[str] = []
    created_files: list[str] = []
    preserved_files: list[str] = []
    refreshed_files: list[str] = []
    marker_target = safe_target(vault, LAYOUT_MARKER)

    if apply:
        vault.mkdir(parents=True, exist_ok=True)
    for relative in sorted(frozen["directories"], key=lambda value: (value.count("/"), value)):
        target = safe_target(vault, relative.rstrip("/"))
        if target.is_symlink():
            raise ValueError(f"target directory is a symlink: {relative}")
        if not target.exists():
            created_dirs.append(relative)
            if apply:
                target.mkdir(parents=True, exist_ok=False)
        elif not target.is_dir():
            raise ValueError(f"layout directory conflicts with file: {relative}")

    for record in frozen["files"]:
        relative = record["path"]
        target = safe_target(vault, relative)
        if target.is_symlink():
            raise ValueError(f"target file is a symlink: {relative}")
        if target.exists():
            if not target.is_file():
                raise ValueError(f"layout file conflicts with non-file: {relative}")
            preserved_files.append(relative)
        else:
            created_files.append(relative)
            if apply:
                copy_missing(source_root / relative, target)

    marker = {
        "version": 1, "name": name,
        "manifest_sha256": frozen["manifest_sha256"],
        "inventory_sha256": frozen["inventory_sha256"],
        "routing_rules_sha256": frozen["routing"]["rules_sha256"],
        "routing_prompt_sha256": frozen["routing"]["prompt_sha256"],
        "profile_sha256": frozen["profile"]["sha256"],
    }
    if marker_target.is_symlink():
        raise ValueError("active layout marker must not be a symlink")
    if marker_target.exists():
        if not marker_target.is_file():
            raise ValueError("active layout marker conflicts with a non-file")
        existing_marker = json.loads(marker_target.read_text(encoding="utf-8"))
        if existing_marker != marker:
            if not refresh_layout_marker:
                raise ValueError("vault has a stale or different active layout marker; explicit marker refresh or layout migration is required")
            if existing_marker.get("version") != 1 or existing_marker.get("name") != name:
                raise ValueError("marker refresh cannot switch layouts; use a content-aware layout migration")
            refreshed_files.append(LAYOUT_MARKER)
            if apply:
                atomic_json(marker_target, marker)
        else:
            preserved_files.append(LAYOUT_MARKER)
    else:
        created_files.append(LAYOUT_MARKER)
        if apply:
            atomic_json(marker_target, marker)

    report = {
        "mode": "apply" if apply else "plan", "layout": frozen,
        "vault": str(vault), "created_dirs": created_dirs,
        "created_files": created_files, "preserved_files": preserved_files,
        "refreshed_files": refreshed_files, "overwritten_files": [],
        "layout_marker": marker,
    }
    atomic_json(output_dir / ("layout-apply-report.json" if apply else "layout-plan.json"), report)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("list", "plan", "apply"))
    parser.add_argument("--layouts-dir", required=True, type=Path)
    parser.add_argument("--layout")
    parser.add_argument("--vault", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--refresh-layout-marker", action="store_true")
    args = parser.parse_args()
    try:
        if args.action == "list":
            result = [inventory(args.layouts_dir, path.name) for path in sorted(args.layouts_dir.iterdir()) if path.is_dir()]
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if not args.layout or args.vault is None or args.output_dir is None:
            raise ValueError("plan/apply require --layout, --vault, and --output-dir")
        plan_or_apply(
            args.layouts_dir, args.layout, args.vault, args.output_dir,
            args.action == "apply", args.refresh_layout_marker,
        )
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.exit(1, f"apply_wiki_layout.py: error: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
