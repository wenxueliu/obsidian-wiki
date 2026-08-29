"""Read the vault layout contract published with the Wiki workflows.

Layout definitions live exclusively under ``workflows/layouts``.  A vault
persists its selected definition in ``_meta/layout.json``; environment files
only locate the vault and never select its structure.

This module is a runtime adapter for Python commands that need to enumerate
live knowledge pages.  It deliberately does not provide user-level layout
overrides or a second configuration format.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


LAYOUT_MARKER = Path("_meta/layout.json")
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_-]+$")
_UNINITIALIZED_SKIP_DIRS = frozenset({"_archived", "_bootstrap", ".git"})


class LayoutContractError(RuntimeError):
    """The selected workflow layout is missing, invalid, or stale."""


def layouts_dir() -> Path:
    """Locate workflow layout definitions in a wheel or source checkout."""
    package = Path(__file__).resolve().parent
    for candidate in (
        package / "_data" / "workflows" / "layouts",
        package.parent / "workflows" / "layouts",
    ):
        if candidate.is_dir():
            return candidate
    raise LayoutContractError(
        "workflow layouts are unavailable; reinstall obsidian-wiki"
    )


@dataclass(frozen=True)
class WorkflowLayout:
    name: str
    description: str
    categories: tuple[str, ...]
    root: Path
    vault_template: Path
    routing: dict[str, Any]

    @property
    def content_roots(self) -> tuple[str, ...]:
        return tuple(self.routing["content_roots"])

    @property
    def skip_dirs(self) -> frozenset[str]:
        return frozenset(self.routing["skip_dirs"])

    @property
    def system_dirs(self) -> frozenset[str]:
        return frozenset(self.routing["system_dirs"])

    @property
    def system_paths(self) -> frozenset[str]:
        return frozenset(self.routing["system_paths"])

    @property
    def directories(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                path.relative_to(self.vault_template).as_posix()
                for path in self.vault_template.rglob("*")
                if path.is_dir() and not path.is_symlink()
            )
        )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LayoutContractError(f"invalid layout file: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise LayoutContractError(f"layout file must contain a JSON object: {path}")
    return value


def _layout_root(name: str) -> Path:
    if not _SAFE_NAME.fullmatch(name):
        raise LayoutContractError("layout name must match [A-Za-z0-9_-]+")
    root = layouts_dir() / name
    if root.is_symlink() or not root.is_dir():
        raise LayoutContractError(f"unknown workflow layout: {name}")
    return root


def load_layout(name: str) -> WorkflowLayout:
    """Load one named workflow layout and its routing contract."""
    root = _layout_root(name)
    manifest = _read_json(root / "layout.json")
    routing = _read_json(root / "routing.json")
    vault_template = root / "vault"
    if manifest.get("version") != 1 or manifest.get("name") != name:
        raise LayoutContractError(f"layout manifest identity mismatch: {name}")
    if manifest.get("copy_policy") != "missing-only":
        raise LayoutContractError(f"unsupported copy policy for layout: {name}")
    if not vault_template.is_dir() or vault_template.is_symlink():
        raise LayoutContractError(f"layout vault template is unavailable: {name}")
    for key in ("routes", "content_roots", "system_dirs", "skip_dirs", "system_paths"):
        if key not in routing:
            raise LayoutContractError(f"layout routing is missing {key!r}: {name}")
    categories = manifest.get("categories")
    if not isinstance(categories, list) or not all(isinstance(item, str) for item in categories):
        raise LayoutContractError(f"layout categories are invalid: {name}")
    return WorkflowLayout(
        name=name,
        description=str(manifest.get("description", "")),
        categories=tuple(categories),
        root=root,
        vault_template=vault_template,
        routing=routing,
    )


def list_layouts() -> dict[str, WorkflowLayout]:
    """Return every valid bundled workflow layout keyed by name."""
    result: dict[str, WorkflowLayout] = {}
    for candidate in sorted(layouts_dir().iterdir()):
        if candidate.is_dir() and not candidate.is_symlink():
            result[candidate.name] = load_layout(candidate.name)
    return result


def _digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _inventory_hash(layout: WorkflowLayout) -> str:
    """Reproduce the portable inventory hash written by the workflow copier."""
    manifest = _read_json(layout.root / "layout.json")
    ignored = set(manifest.get("ignore", []))
    files: list[dict[str, Any]] = []
    directories: list[str] = []
    for candidate in sorted(layout.vault_template.rglob("*")):
        relative = candidate.relative_to(layout.vault_template).as_posix()
        if candidate.is_dir():
            directories.append(relative + "/")
        elif candidate.is_file() and candidate.name not in ignored:
            files.append({
                "path": relative,
                "size": candidate.stat().st_size,
                "sha256": _digest(candidate),
            })
    routing_path = layout.root / "routing.json"
    prompt_path = layout.root / "routing.md"
    portable = {
        "version": 1,
        "name": layout.name,
        "description": layout.description,
        "copy_policy": "missing-only",
        "categories": list(layout.categories),
        "manifest_sha256": _digest(layout.root / "layout.json"),
        "directories": directories,
        "files": files,
        "ignored": sorted(ignored),
        "routing": {
            "rules_sha256": _digest(routing_path),
            "rules": layout.routing,
            "prompt_sha256": _digest(prompt_path),
            "prompt": prompt_path.read_text(encoding="utf-8"),
        },
    }
    encoded = json.dumps(portable, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def active_layout(vault: Path, *, allow_uninitialized: bool = True) -> WorkflowLayout:
    """Resolve and validate the layout selected by a vault marker.

    Read-only Python commands may inspect an uninitialized vault using the
    bundled ``default`` contract.  Initialized vaults always use their marker,
    and a stale marker fails closed.
    """
    vault = Path(vault)
    marker_path = vault / LAYOUT_MARKER
    if not marker_path.is_file():
        if allow_uninitialized:
            return load_layout("default")
        raise LayoutContractError(
            f"active layout marker is missing: {marker_path}; run wiki-setup repair"
        )
    marker = _read_json(marker_path)
    if marker.get("version") != 1 or not isinstance(marker.get("name"), str):
        raise LayoutContractError(f"active layout marker is invalid: {marker_path}")
    layout = load_layout(marker["name"])
    expected = {
        "manifest_sha256": _digest(layout.root / "layout.json"),
        "inventory_sha256": _inventory_hash(layout),
        "routing_rules_sha256": _digest(layout.root / "routing.json"),
        "routing_prompt_sha256": _digest(layout.root / "routing.md"),
    }
    stale = [key for key, value in expected.items() if marker.get(key) != value]
    if stale:
        raise LayoutContractError(
            f"active layout contract is stale ({', '.join(stale)}); "
            "run wiki-setup repair or an explicit layout migration"
        )
    return layout


def iter_content_pages(vault: Path) -> Iterator[Path]:
    """Yield Markdown pages within the active layout's declared content roots."""
    vault = Path(vault)
    layout = active_layout(vault)
    # Legacy/uninitialized vaults do not yet have a trustworthy declaration of
    # their content roots.  Keep read-only commands useful during migration by
    # scanning conservatively while excluding the default workflow's system
    # areas.  Once a marker exists, its declared roots are authoritative.
    if not (vault / LAYOUT_MARKER).is_file():
        for path in vault.rglob("*.md"):
            relative = path.relative_to(vault)
            if any(
                part in layout.skip_dirs or part in _UNINITIALIZED_SKIP_DIRS
                for part in relative.parts
            ):
                continue
            yield path
        return
    for root_name in layout.content_roots:
        root = vault / root_name
        if not root.is_dir():
            continue
        for path in root.rglob("*.md"):
            relative = path.relative_to(vault)
            if any(part in layout.skip_dirs for part in relative.parts):
                continue
            yield path


def trust_ledger_path(vault: Path) -> Path:
    """Return the trust-ledger path under the active layout marker directory."""
    marker_parent = LAYOUT_MARKER.parent
    active_layout(vault)
    return marker_parent / "trust-ledger.json"
