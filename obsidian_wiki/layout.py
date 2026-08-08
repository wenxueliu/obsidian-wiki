"""Vault directory layout — single source of truth for vault structure.

Replaces every hardcoded directory list (VAULT_SUBDIRS, SKIP_DIRS,
TRUST_SKIP_DIRS, etc.) with a single lazily-loaded VaultLayout resolved
from a YAML file.

Resolution order:
  1. ~/.obsidian-wiki/vault-layout.yaml      (user override)
  2. ~/.obsidian-wiki/vault-layout/*.yaml    (selected by name)
  3. <pkg>/_data/vault-layout/*.yaml         (bundled built-ins)
  4. <repo>/vault-layout/*.yaml              (source checkout)
  5. DEFAULT_LAYOUT constant                 (emergency fallback)

v2 format: categories may use dot-separated paths for nested dirs.
  categories:
    - concepts
    - concepts.patterns    → creates concepts/patterns/
    - concepts.models      → creates concepts/models/
    - skills.how-to        → creates skills/how-to/

The project has no runtime dependencies, so this module ships a minimal
YAML parser that handles only the subset used by vault-layout.yaml.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class VaultLayout:
    """Immutable vault directory layout resolved from a config file.

    Categories may contain dot-separated paths for nested directories.
    Use ``flat_categories`` for backward-compatible top-level names only.
    """

    categories: tuple[str, ...]
    projects_dir: str
    project_subdirs: tuple[str, ...]
    raw_dir: str
    staging_dir: str
    archives_dir: str
    meta_dir: str
    readouts_dir: str
    extra_skip_dirs: tuple[str, ...]

    @property
    def flat_categories(self) -> tuple[str, ...]:
        """Top-level category names only (no subdirectory parts)."""
        return tuple(sorted({c.split(".")[0] for c in self.categories}))

    @property
    def all_dirs(self) -> tuple[str, ...]:
        """Every directory scaffold_vault() should create."""
        dirs: list[str] = []
        # Flatten dot-separated paths: "concepts.patterns" → "concepts/patterns"
        for cat in self.categories:
            parts = cat.split(".")
            path = "/".join(parts)
            dirs.append(path)
            # Ensure parent dirs are included (concepts.patterns requires concepts/)
            for i in range(1, len(parts)):
                dirs.append("/".join(parts[:i]))
        # Deduplicate while preserving insertion order
        seen = set()
        result = []
        for d in dirs:
            if d not in seen:
                seen.add(d)
                result.append(d)
        result.append(self.projects_dir)
        result.extend([
            self.raw_dir, self.staging_dir, self.archives_dir,
            self.meta_dir, self.readouts_dir,
        ])
        return tuple(result)

    @property
    def skip_dirs(self) -> frozenset[str]:
        """Directories excluded from page iteration, linting, and graph analysis."""
        return frozenset({
            self.raw_dir, self.staging_dir, self.archives_dir,
            self.meta_dir, self.readouts_dir,
            "_archived", "_bootstrap", ".obsidian", ".git",
            *self.extra_skip_dirs,
        })

    @property
    def reserved_stems(self) -> frozenset[str]:
        """Page stems at vault root that are never treated as content pages."""
        return frozenset({"index", "log", "hot", "_insights"})

    def trust_ledger_path(self) -> Path:
        """Relative path to the trust ledger within the vault."""
        return Path(self.meta_dir) / "trust-ledger.json"


# ── Default layout ──────────────────────────────────────────────────

DEFAULT_LAYOUT = VaultLayout(
    categories=(
        "concepts", "concepts.patterns", "concepts.models",
        "entities",
        "skills", "skills.how-to", "skills.debugging",
        "references",
        "synthesis",
        "journal",
    ),
    projects_dir="projects",
    project_subdirs=("concepts", "skills", "references"),
    raw_dir="_raw",
    staging_dir="_staging",
    archives_dir="_archives",
    meta_dir="_meta",
    readouts_dir="_readouts",
    extra_skip_dirs=(),
)


# ── YAML subset parser ───────────────────────────────────────────────

_YAML_COMMENT_RE = re.compile(r"^\s*#")
_YAML_SCALAR_RE = re.compile(r'^(\w[\w_-]*):\s*"?(?:([^"#]*?))?"?\s*(?:#.*)?$')
_YAML_LIST_ITEM_RE = re.compile(r"^\s*-\s+(\.?\w[\w_.-]*)\s*(?:#.*)?$")
_YAML_NESTED_KEY_RE = re.compile(r'^\s\s(\w[\w_-]*):\s*"?(?:([^"#]*?))?"?\s*(?:#.*)?$')

_LIST_KEYS = {"categories", "project_subdirs", "extra_skip_dirs"}
_NESTED_KEYS = {"system"}


def _parse_simple_yaml(text: str) -> dict:
    """Parse the minimal YAML subset used by vault-layout.yaml.

    Returns a dict whose values are str, list[str], or dict[str, str].
    """
    result: dict = {}
    lines = text.splitlines()
    current_list_key: Optional[str] = None
    current_nested_key: Optional[str] = None

    for line in lines:
        stripped = line.strip()
        if not stripped or _YAML_COMMENT_RE.match(line):
            continue

        m = _YAML_LIST_ITEM_RE.match(line)
        if m and current_list_key is not None:
            if not isinstance(result.get(current_list_key), list):
                result[current_list_key] = []
            result[current_list_key].append(m.group(1))
            continue

        m = _YAML_NESTED_KEY_RE.match(line)
        if m and current_nested_key is not None:
            if not isinstance(result.get(current_nested_key), dict):
                result[current_nested_key] = {}
            result[current_nested_key][m.group(1)] = m.group(2).strip()
            continue

        m = _YAML_SCALAR_RE.match(line)
        if m:
            key = m.group(1)
            val = m.group(2).strip()
            if not val:
                current_list_key = key if key in _LIST_KEYS else current_list_key
                current_nested_key = key if key in _NESTED_KEYS else current_nested_key
            else:
                try:
                    result[key] = int(val)
                except ValueError:
                    result[key] = val
            continue

    return result


# ── Layout discovery ─────────────────────────────────────────────────

def _layout_search_paths() -> list[Path]:
    """Return all directories to scan for .yaml layout files."""
    paths: list[Path] = []
    pkg_dir = Path(__file__).resolve().parent
    # User override dir
    user_dir = Path.home() / ".obsidian-wiki" / "vault-layout"
    if user_dir.is_dir():
        paths.append(user_dir)
    # Bundled layouts in the package
    for cand in (pkg_dir / "_data" / "vault-layout", pkg_dir.parent / "vault-layout"):
        if cand.is_dir():
            paths.append(cand)
    return paths


def list_layouts() -> dict[str, tuple[str, Path]]:
    """List available layouts as {key: (description, path)}.

    Scans ~/.obsidian-wiki/vault-layout/ first, then bundled layouts.
    User layouts shadow bundled ones with the same stem.
    """
    layouts: dict[str, tuple[str, Path]] = {}
    for search_dir in _layout_search_paths():
        for yaml_file in sorted(search_dir.glob("*.yaml")):
            stem = yaml_file.stem
            if stem in layouts:
                continue  # user layout shadows bundled
            raw = _parse_simple_yaml(yaml_file.read_text())
            desc = raw.get("description", stem)
            layouts[stem] = (str(desc), yaml_file)
    return layouts


def select_layout(name: str) -> VaultLayout:
    """Load a layout by name from the available layouts.

    Raises FileNotFoundError if *name* doesn't match any layout.
    """
    available = list_layouts()
    if name not in available:
        raise FileNotFoundError(
            f"Unknown layout '{name}'. Available: {', '.join(available)}"
        )
    return load_layout(path=available[name][1])


# ── Layout loading ───────────────────────────────────────────────────

def _resolve_layout_path(name: str | None = None) -> Optional[Path]:
    """Return the path to a layout file, or None."""
    # 1. Named layout in user dir or bundled
    if name:
        available = list_layouts()
        if name in available:
            return available[name][1]

    # 2. ~/.obsidian-wiki/vault-layout.yaml (legacy single-file)
    legacy = Path.home() / ".obsidian-wiki" / "vault-layout.yaml"
    if legacy.is_file():
        return legacy

    # 3. Bundled single file (also legacy)
    pkg_dir = Path(__file__).resolve().parent
    for cand in (
        pkg_dir / "_data" / "vault-layout.yaml",
        pkg_dir.parent / "vault-layout.yaml",
    ):
        if cand.is_file():
            return cand

    # 4. First available layout in vault-layout/ dirs
    for search_dir in _layout_search_paths():
        yamls = sorted(search_dir.glob("*.yaml"))
        if yamls:
            return yamls[0]

    return None


def load_layout(
    path: Optional[Path] = None, name: Optional[str] = None
) -> VaultLayout:
    """Load a VaultLayout.

    Resolution order:
    1. Explicit *path* → use that file directly
    2. Explicit *name* → select from available layouts
    3. ~/.obsidian-wiki/vault-layout.yaml (legacy single-file)
    4. Bundled vault-layout.yaml (legacy)
    5. First layout in vault-layout/ dirs
    6. DEFAULT_LAYOUT constant (hardcoded fallback)
    """
    if path is not None:
        raw = _parse_simple_yaml(path.read_text())
    else:
        resolved = _resolve_layout_path(name)
        if resolved is not None:
            raw = _parse_simple_yaml(resolved.read_text())
        else:
            return DEFAULT_LAYOUT

    def _as_tuple(value, default: tuple[str, ...]) -> tuple[str, ...]:
        if isinstance(value, list):
            return tuple(value)
        return default

    categories = _as_tuple(raw.get("categories"), DEFAULT_LAYOUT.categories)
    projects_dir = str(raw.get("projects", DEFAULT_LAYOUT.projects_dir))
    project_subdirs = _as_tuple(
        raw.get("project_subdirs"), DEFAULT_LAYOUT.project_subdirs
    )
    extra_skip_dirs = _as_tuple(
        raw.get("extra_skip_dirs"), DEFAULT_LAYOUT.extra_skip_dirs
    )
    system = raw.get("system", {})
    if not isinstance(system, dict):
        system = {}

    return VaultLayout(
        categories=categories,
        projects_dir=projects_dir,
        project_subdirs=project_subdirs,
        extra_skip_dirs=extra_skip_dirs,
        raw_dir=str(system.get("raw", DEFAULT_LAYOUT.raw_dir)),
        staging_dir=str(system.get("staging", DEFAULT_LAYOUT.staging_dir)),
        archives_dir=str(system.get("archives", DEFAULT_LAYOUT.archives_dir)),
        meta_dir=str(system.get("meta", DEFAULT_LAYOUT.meta_dir)),
        readouts_dir=str(system.get("readouts", DEFAULT_LAYOUT.readouts_dir)),
    )
