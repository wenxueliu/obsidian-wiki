"""Vault directory layout — single source of truth for vault structure.

Replaces every hardcoded directory list (VAULT_SUBDIRS, SKIP_DIRS,
TRUST_SKIP_DIRS, etc.) with a single lazily-loaded VaultLayout resolved
from a YAML file.

Resolution order:
  1. ~/.obsidian-wiki/vault-layout.yaml  (user override)
  2. Bundled vault-layout.yaml           (package default)
  3. DEFAULT_LAYOUT constant             (emergency fallback)

The project has no runtime dependencies, so this module ships a minimal
YAML parser that handles only the subset used by vault-layout.yaml:
comments, top-level scalars, simple lists, and one level of nested
key-value blocks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class VaultLayout:
    """Immutable vault directory layout resolved from a config file."""

    categories: tuple[str, ...]
    projects_dir: str
    project_subdirs: tuple[str, ...]    # subset of categories created under each project
    raw_dir: str
    staging_dir: str
    archives_dir: str
    meta_dir: str
    readouts_dir: str

    # ── Derived: all content + system dirs scaffold_vault() creates ──────

    @property
    def all_dirs(self) -> tuple[str, ...]:
        """Every directory scaffold_vault() should create (categories + projects + system).

        Project subdirs (concepts/, skills/, references/ under each project) are
        NOT included — they're created on-demand per project by wiki-update / wiki-ingest.
        """
        return self.categories + (
            self.projects_dir,
            self.raw_dir,
            self.staging_dir,
            self.archives_dir,
            self.meta_dir,
            self.readouts_dir,
        )

    # ── Derived: system dirs excluded from page iteration ─────────────────

    @property
    def skip_dirs(self) -> frozenset[str]:
        """Directories excluded from page iteration, linting, and graph analysis.

        Includes all configurable system dirs plus implicitly-excluded
        directories that are NOT part of the configurable layout.
        """
        return frozenset({
            self.raw_dir,
            self.staging_dir,
            self.archives_dir,
            self.meta_dir,
            self.readouts_dir,
            "_archived",       # created ad-hoc within raw_dir
            "_bootstrap",      # setup-time templates
            ".obsidian",       # Obsidian's own config
            ".git",            # version control
        })

    @property
    def reserved_stems(self) -> frozenset[str]:
        """Page stems at vault root that are never treated as content pages."""
        return frozenset({"index", "log", "hot", "_insights"})

    def trust_ledger_path(self) -> Path:
        """Relative path to the trust ledger within the vault."""
        return Path(self.meta_dir) / "trust-ledger.json"


# ── Default layout — byte-for-byte match with pre-configurable structure ─

DEFAULT_LAYOUT = VaultLayout(
    categories=("concepts", "entities", "skills", "references", "synthesis", "journal"),
    projects_dir="projects",
    project_subdirs=("concepts", "skills", "references"),
    raw_dir="_raw",
    staging_dir="_staging",
    archives_dir="_archives",
    meta_dir="_meta",
    readouts_dir="_readouts",
)


# ── YAML subset parser — no PyYAML dependency ──────────────────────────

_YAML_COMMENT_RE = re.compile(r"^\s*#")
_YAML_SCALAR_RE = re.compile(r'^(\w[\w_-]*):\s*"?(?:([^"#]*?))?"?\s*(?:#.*)?$')
_YAML_LIST_ITEM_RE = re.compile(r"^\s*-\s+(\w[\w_-]*)\s*(?:#.*)?$")
_YAML_NESTED_KEY_RE = re.compile(r'^\s\s(\w[\w_-]*):\s*"?(?:([^"#]*?))?"?\s*(?:#.*)?$')


def _parse_simple_yaml(text: str) -> dict:
    """Parse the minimal YAML subset used by vault-layout.yaml.

    Handles: ``#`` comments, top-level ``key: value`` scalars,
    ``- item`` list entries under a preceding top-level key, and one
    level of indented ``key: value`` pairs under a preceding top-level
    key (for the ``system:`` block).

    Returns a dict whose values are str, list[str], or dict[str, str].
    """
    result: dict = {}
    lines = text.splitlines()

    list_keys = {"categories"}  # keys that hold lists
    nested_keys = {"system"}     # keys that hold nested dicts

    current_list_key: Optional[str] = None
    current_nested_key: Optional[str] = None

    for line in lines:
        stripped = line.strip()
        if not stripped or _YAML_COMMENT_RE.match(line):
            continue

        # List item under the last-seen list key
        m = _YAML_LIST_ITEM_RE.match(line)
        if m and current_list_key is not None:
            if not isinstance(result.get(current_list_key), list):
                result[current_list_key] = []
            result[current_list_key].append(m.group(1))
            continue

        # Indented key under a nested block (system:)
        m = _YAML_NESTED_KEY_RE.match(line)
        if m and current_nested_key is not None:
            if not isinstance(result.get(current_nested_key), dict):
                result[current_nested_key] = {}
            result[current_nested_key][m.group(1)] = m.group(2).strip()
            continue

        # Top-level scalar
        m = _YAML_SCALAR_RE.match(line)
        if m:
            key = m.group(1)
            val = m.group(2).strip()
            if not val:
                # Bare key with no value — placeholder, will be populated
                # by subsequent list items or nested keys
                current_list_key = key if key in list_keys else current_list_key
                current_nested_key = key if key in nested_keys else current_nested_key
            else:
                try:
                    result[key] = int(val)
                except ValueError:
                    result[key] = val
            continue

    return result


# ── Layout loading ─────────────────────────────────────────────────────

def _resolve_layout_path() -> Optional[Path]:
    """Return the path to the user's custom layout, or the bundled default."""
    user_path = Path.home() / ".obsidian-wiki" / "vault-layout.yaml"
    if user_path.is_file():
        return user_path
    pkg_dir = Path(__file__).resolve().parent
    for cand in (
        pkg_dir / "_data" / "vault-layout.yaml",
        pkg_dir.parent / "vault-layout.yaml",
    ):
        if cand.is_file():
            return cand
    return None


def load_layout(path: Optional[Path] = None) -> VaultLayout:
    """Load a VaultLayout, with fallback chain.

    1. Explicit *path* argument (for testing)
    2. ``~/.obsidian-wiki/vault-layout.yaml`` (user override)
    3. Bundled ``vault-layout.yaml`` (package default)
    4. ``DEFAULT_LAYOUT`` constant (emergency fallback)
    """
    if path is not None:
        raw = _parse_simple_yaml(path.read_text())
    else:
        resolved = _resolve_layout_path()
        if resolved is not None:
            raw = _parse_simple_yaml(resolved.read_text())
        else:
            return DEFAULT_LAYOUT

    categories = tuple(raw.get("categories", DEFAULT_LAYOUT.categories))
    projects_dir = str(raw.get("projects", DEFAULT_LAYOUT.projects_dir))
    project_subdirs = tuple(raw.get("project_subdirs", DEFAULT_LAYOUT.project_subdirs))
    system = raw.get("system", {})
    if not isinstance(system, dict):
        system = {}

    return VaultLayout(
        categories=categories,
        projects_dir=projects_dir,
        project_subdirs=project_subdirs,
        raw_dir=str(system.get("raw", DEFAULT_LAYOUT.raw_dir)),
        staging_dir=str(system.get("staging", DEFAULT_LAYOUT.staging_dir)),
        archives_dir=str(system.get("archives", DEFAULT_LAYOUT.archives_dir)),
        meta_dir=str(system.get("meta", DEFAULT_LAYOUT.meta_dir)),
        readouts_dir=str(system.get("readouts", DEFAULT_LAYOUT.readouts_dir)),
    )
