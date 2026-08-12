"""Post-ingest source completeness audit.

Cross-checks the manifest against the vault to detect ingest omissions:

  - a source was ingested but its ``pages_produced`` is empty/missing
  - ``pages_produced`` lists a page that no longer exists on disk
  - a source is expected (passed in) but has no manifest entry at all

Run after Step 7 in ``wiki-ingest`` to confirm every source in the batch was
actually processed and its pages landed.  This is the source-level half of
"did I miss anything" — it does NOT judge whether the extraction covered all
of a document's *content* (that is an LLM-judgment concern; for large docs the
PageIndex structure map gives a section list to eyeball).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from obsidian_wiki.cache import _iter_entries, _load_manifest


def verify_completeness(
    vault: Path,
    source_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Audit manifest↔vault consistency for ingested sources.

    *source_paths*: optional list of source paths from this ingest batch. When
    provided, sources in it that have no manifest entry are reported as
    ``missing_entry``.

    Returns a dict with status and lists of problems.
    """
    manifest_sources = _load_manifest(vault)

    # Build a lookup: stored-key -> entry, and canonical (resolved) path -> entry.
    entries: list[dict[str, Any]] = []
    for stored_key, entry in _iter_entries(manifest_sources):
        entries.append({"stored_key": stored_key, **entry})

    # Collect all pages_produced across the manifest for existence checking.
    missing_entry: list[str] = []
    empty_pages: list[str] = []
    phantom_pages: list[tuple[str, str]] = []

    # 1. Expected sources with no manifest entry.
    if source_paths:
        stored_keys = {e["stored_key"] for e in entries}
        for sp in source_paths:
            # Match loosely: exact string, or resolved path.
            key_hit = sp in stored_keys
            if not key_hit:
                from obsidian_wiki.cache import _same_source
                p = Path(sp)
                key_hit = any(
                    _same_source(e["stored_key"], p, vault) for e in entries
                )
            if not key_hit:
                missing_entry.append(sp)

    # 2. Manifest entries with empty pages_produced, or phantom pages.
    for e in entries:
        key = e["stored_key"] or "(unknown)"
        produced = e.get("pages_produced")
        if not produced:
            empty_pages.append(key)
            continue
        if not isinstance(produced, list):
            produced = [produced]
        for page in produced:
            if not (vault / page).exists():
                phantom_pages.append((key, str(page)))

    problems = {
        "missing_entry": missing_entry,
        "empty_pages": empty_pages,
        "phantom_pages": phantom_pages,
    }
    counts = {k: len(v) for k, v in problems.items()}

    status = "pass" if not any(counts.values()) else "fail"

    return {
        "status": status,
        "stats": {
            "manifest_sources": len(entries),
            "expected_sources": len(source_paths) if source_paths else None,
            "findings": counts,
        },
        "findings": problems,
    }


def print_report(report: dict[str, Any], file: object = None) -> None:
    import sys
    out = file or sys.stdout
    print(f"completeness audit: {report['status']}", file=out)
    stats = report["stats"]
    print(
        f"  manifest sources: {stats['manifest_sources']}"
        + (f"  expected: {stats['expected_sources']}" if stats["expected_sources"] is not None else ""),
        file=out,
    )
    findings = report["findings"]
    if findings["missing_entry"]:
        print(f"\nSources with no manifest entry ({len(findings['missing_entry'])}):", file=out)
        for s in findings["missing_entry"]:
            print(f"  - {s}", file=out)
    if findings["empty_pages"]:
        print(f"\nSources with empty pages_produced ({len(findings['empty_pages'])}):", file=out)
        for s in findings["empty_pages"]:
            print(f"  - {s}", file=out)
    if findings["phantom_pages"]:
        print(f"\nPhantom pages listed but missing on disk ({len(findings['phantom_pages'])}):", file=out)
        for src, page in findings["phantom_pages"]:
            print(f"  - {page}  (from {src})", file=out)


def flatten_sections(structure: list[dict]) -> list[dict]:
    """Flatten a PageIndex structure tree into leaf sections.

    Each leaf becomes ``{title, start, end}``. Intermediate nodes with children
    are recursed into; leaf nodes (no ``nodes``) are kept.
    """
    leaves: list[dict] = []

    def walk(nodes: list[dict]) -> None:
        for n in nodes:
            children = n.get("nodes")
            if children:
                walk(children)
            else:
                leaves.append({
                    "title": n.get("title", ""),
                    "start": n.get("start_index"),
                    "end": n.get("end_index"),
                })

    walk(structure)
    return leaves


def verify_sections(
    structure_path: str | Path,
    produced_pages: list[str] | None = None,
) -> dict[str, Any]:
    """Read a PageIndex ``_structure.json`` and emit a section-coverage checklist.

    This is the content-level half of completeness checking: it does NOT judge
    whether a given section was distilled (that mapping is semantic), but it
    gives a concrete section list + a heuristic hint when the produced page
    count looks small relative to the section count.
    """
    import json

    path = Path(structure_path)
    if not path.exists():
        return {
            "status": "fail",
            "error": f"structure file not found: {path}",
        }

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {"status": "fail", "error": f"unreadable structure file: {exc}"}

    sections = flatten_sections(data.get("structure", []))
    page_span = max((s.get("end") or 0) for s in sections) if sections else 0

    result: dict[str, Any] = {
        "status": "pass",
        "doc_name": data.get("doc_name", path.stem),
        "doc_description": data.get("doc_description", ""),
        "section_count": len(sections),
        "page_span": page_span,
        "sections": sections,
    }

    if produced_pages is not None:
        result["produced_pages"] = len(produced_pages)
        # Heuristic: many more sections than pages suggests under-extraction.
        if len(sections) > 0 and len(produced_pages) == 0:
            result["coverage_hint"] = "no pages produced for this document"
            result["status"] = "fail"
        elif len(sections) > len(produced_pages) * 3:
            result["coverage_hint"] = "section count far exceeds page count — review for under-coverage"
            result["status"] = "warn"
        else:
            result["coverage_hint"] = "ok"

    return result


def print_sections_report(report: dict[str, Any], file: object = None) -> None:
    import sys
    out = file or sys.stdout
    if "error" in report:
        print(f"section coverage: fail — {report['error']}", file=out)
        return
    print(
        f"section coverage: {report['status']}  "
        f"doc={report['doc_name']}  sections={report['section_count']}  "
        f"page_span={report['page_span']}",
        file=out,
    )
    if "coverage_hint" in report:
        print(f"  hint: {report['coverage_hint']}", file=out)
    print("\nSections (eyeball against pages written):", file=out)
    for s in report.get("sections", []):
        rng = f"{s['start']}-{s['end']}" if s.get("start") is not None else "?"
        print(f"  [{rng}] {s['title']}", file=out)

