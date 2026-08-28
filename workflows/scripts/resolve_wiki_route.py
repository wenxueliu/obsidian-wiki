#!/usr/bin/env python3
"""Resolve a semantic Wiki page type to a validated layout-relative target."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

from apply_wiki_layout import validate_relative_path, validate_routing


SAFE_VALUE = re.compile(r"^[^/\\\x00]+$")


def unwrap_routing(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("routing input must be a JSON object")
    if "routes" in data:
        return validate_routing(data)
    candidate = data.get("routing")
    if isinstance(candidate, dict) and "rules" in candidate:
        return validate_routing(candidate["rules"])
    active = data.get("active_layout") or data.get("optional_metadata", {}).get("active_layout")
    if isinstance(active, dict) and isinstance(active.get("routing"), dict):
        return validate_routing(active["routing"]["rules"])
    raise ValueError("routing input does not contain routing rules")


def resolve_route(routing: dict[str, Any], page_type: str, values: dict[str, Any]) -> dict[str, str]:
    route_name = page_type or routing["fallback"]
    template = routing["routes"].get(route_name)
    if template is None:
        raise ValueError(f"unknown page type: {route_name!r}")
    needed = {part[1] for part in __import__("string").Formatter().parse(template) if part[1]}
    normalized: dict[str, str] = {}
    for key in needed:
        value = values.get(key)
        if not isinstance(value, str) or not value or not SAFE_VALUE.fullmatch(value) or value in (".", ".."):
            raise ValueError(f"placeholder {key!r} must be a non-empty path-segment value")
        normalized[key] = value
    target = template.format_map(normalized)
    validate_relative_path(target, "resolved route")
    if target.split("/", 1)[0] not in routing["content_roots"]:
        raise ValueError("resolved route is outside content_roots")
    if target in routing["system_paths"]:
        raise ValueError("resolved route targets a reserved system path")
    return {"page_type": route_name, "target": target}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--routing", required=True, type=Path)
    parser.add_argument("--page-type", required=True)
    parser.add_argument("--slug")
    parser.add_argument("--project")
    parser.add_argument("--date")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        routing = unwrap_routing(json.loads(args.routing.read_text(encoding="utf-8")))
        result = resolve_route(routing, args.page_type, {
            "slug": args.slug, "project": args.project, "date": args.date,
        })
        rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        else:
            print(rendered, end="")
        return 0
    except (OSError, ValueError, json.JSONDecodeError, KeyError) as error:
        parser.exit(1, f"resolve_wiki_route.py: error: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
