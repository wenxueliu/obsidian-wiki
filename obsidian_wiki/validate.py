"""Post-ingest frontmatter validation.

Checks that newly written or updated wiki pages have all required frontmatter
fields per the page template in llm-wiki/SKILL.md.  Run this after every ingest
before updating index.md / log.md / manifest so missing fields surface as
actionable errors rather than silent omissions.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)
_TOP_FIELD_RE = re.compile(r"^([A-Za-z_][\w-]*):", re.MULTILINE)

# Fields every new wiki page MUST have (per llm-wiki page template).
REQUIRED_FIELDS = (
    "title",
    "category",
    "tags",
    "sources",
    "summary",
    "base_confidence",
    "lifecycle",
    "lifecycle_changed",
    "tier",
    "created",
    "updated",
)

# Fields that should be present but use a nested block format.
BLOCK_FIELDS = ("provenance",)


def _parse_field_names(frontmatter: str) -> set[str]:
    return set(_TOP_FIELD_RE.findall(frontmatter))


def _check_provenance_block(frontmatter: str) -> bool:
    """Return True if frontmatter contains a provenance: block with at least one sub-key."""
    lines = frontmatter.splitlines()
    in_provenance = False
    for line in lines:
        if line.startswith("provenance:") and not line.startswith((" ", "\t")):
            in_provenance = True
            continue
        if in_provenance:
            if line and not line.startswith((" ", "\t")):
                break
            if line.strip().startswith(("extracted:", "inferred:", "ambiguous:")):
                return True
    return False


def validate_page(path: Path) -> dict[str, Any]:
    """Validate a single markdown page. Returns dict with 'path', 'missing', 'warnings'."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return {"path": str(path), "error": str(exc), "missing": [], "warnings": []}

    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {
            "path": str(path),
            "error": "no frontmatter block found",
            "missing": list(REQUIRED_FIELDS),
            "warnings": [],
        }

    frontmatter = match.group(1)
    fields = _parse_field_names(frontmatter)
    missing = [f for f in REQUIRED_FIELDS if f not in fields]
    warnings = []

    if "provenance" not in fields:
        missing.append("provenance")
    elif not _check_provenance_block(frontmatter):
        warnings.append("provenance block present but missing sub-keys (extracted/inferred/ambiguous)")

    # Summary length check
    if "summary" in fields:
        for line in frontmatter.splitlines():
            if line.startswith("summary:"):
                value = line.split(":", 1)[1].strip().strip("'\"")
                if len(value) > 200:
                    warnings.append(f"summary is {len(value)} chars (max 200)")

    return {
        "path": str(path),
        "missing": missing,
        "warnings": warnings,
        "ok": len(missing) == 0 and len(warnings) == 0,
    }


def validate_pages(paths: list[Path], vault_root: Path | None = None) -> dict[str, Any]:
    """Validate a list of page paths. Returns a summary dict suitable for JSON output."""
    results = [validate_page(p) for p in paths]
    failed = [r for r in results if not r.get("ok")]
    all_missing: dict[str, list[str]] = {}
    for r in failed:
        for field in r.get("missing", []):
            all_missing.setdefault(field, []).append(r["path"])

    return {
        "status": "pass" if not failed else "fail",
        "checked": len(results),
        "failed": len(failed),
        "missing_by_field": all_missing,
        "details": failed,
    }


def validate_vault_pages(vault: Path, page_paths: list[str]) -> dict[str, Any]:
    """Validate specific pages within a vault.

    *page_paths* are vault-relative paths (e.g. ``concepts/foo.md``).
    """
    resolved = [vault / p for p in page_paths]
    return validate_pages(resolved, vault_root=vault)


def print_report(report: dict[str, Any], file: object = sys.stdout) -> None:
    """Print a human-readable validation report."""
    print(f"frontmatter validation: {report['status']}", file=file)
    print(f"  checked: {report['checked']}  failed: {report['failed']}", file=file)
    if report["failed"]:
        print("\nMissing fields:", file=file)
        for field, paths in sorted(report.get("missing_by_field", {}).items()):
            print(f"  {field}: {len(paths)} page(s)", file=file)
            for p in paths[:5]:
                print(f"    - {p}", file=file)
            if len(paths) > 5:
                print(f"    ... and {len(paths) - 5} more", file=file)
        print("\nDetails:", file=file)
        for detail in report.get("details", []):
            p = detail["path"]
            missing = detail.get("missing", [])
            warnings = detail.get("warnings", [])
            error = detail.get("error", "")
            if error:
                print(f"  {p}: ERROR — {error}", file=file)
            else:
                parts = []
                if missing:
                    parts.append(f"missing: {', '.join(missing)}")
                if warnings:
                    parts.append(f"warnings: {'; '.join(warnings)}")
                print(f"  {p}: {' | '.join(parts)}", file=file)
