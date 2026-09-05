"""Read the public Knowledge Pack contracts bundled with obsidian-wiki.

Knowledge Packs live exclusively under ``knowledge-packs``. Each pack binds
a semantic Knowledge Profile to one physical Vault Layout. A vault persists
the selected contract hashes in ``_meta/knowledge-pack.json``.

This module is a runtime adapter for Python commands that need to enumerate
live knowledge pages. It deliberately exposes Knowledge Packs independently
of workflow implementation resources.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


KNOWLEDGE_PACK_MARKER = Path("_meta/knowledge-pack.json")
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_-]+$")
_UNINITIALIZED_SKIP_DIRS = frozenset({"_archived", "_bootstrap", ".git"})


class KnowledgePackContractError(RuntimeError):
    """The selected Knowledge Pack is missing, invalid, or stale."""


def knowledge_packs_dir() -> Path:
    """Locate Knowledge Pack definitions in a wheel or source checkout."""
    package = Path(__file__).resolve().parent
    for candidate in (
        package / "_data" / "knowledge-packs",
        package.parent / "knowledge-packs",
    ):
        if candidate.is_dir():
            return candidate
    raise KnowledgePackContractError(
        "Knowledge Packs are unavailable; reinstall obsidian-wiki"
    )


@dataclass(frozen=True)
class KnowledgePack:
    """One bundled semantic and physical Knowledge Pack."""

    name: str
    description: str
    categories: tuple[str, ...]
    profile: dict[str, Any]
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
        raise KnowledgePackContractError(f"invalid layout file: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise KnowledgePackContractError(f"layout file must contain a JSON object: {path}")
    return value


def _string_list(value: Any, label: str, *, allow_empty: bool = False) -> list[str]:
    if (
        not isinstance(value, list)
        or (not allow_empty and not value)
        or not all(isinstance(item, str) and item.strip() for item in value)
    ):
        suffix = "" if allow_empty else " non-empty"
        raise KnowledgePackContractError(f"profile {label} must be a{suffix} string array")
    if len(value) != len(set(value)):
        raise KnowledgePackContractError(f"profile {label} must not contain duplicates")
    return value


def _validate_profile(data: dict[str, Any], name: str, routing: dict[str, Any]) -> dict[str, Any]:
    if data.get("version") != 1 or data.get("name") != name:
        raise KnowledgePackContractError(f"profile version/name mismatch: {name}")
    if not isinstance(data.get("description"), str) or not data["description"].strip():
        raise KnowledgePackContractError("profile description must be a non-empty string")
    _string_list(data.get("purpose"), "purpose")
    scope = data.get("scope")
    if not isinstance(scope, dict) or scope.get("on_mismatch") not in {"ask", "stage", "reject"}:
        raise KnowledgePackContractError("profile scope must declare on_mismatch=ask|stage|reject")
    _string_list(scope.get("include"), "scope.include")
    _string_list(scope.get("exclude"), "scope.exclude", allow_empty=True)
    knowledge_types = _string_list(data.get("knowledge_types"), "knowledge_types")
    unknown_types = sorted(set(knowledge_types) - set(routing.get("routes", {})))
    if unknown_types:
        raise KnowledgePackContractError(
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
            raise KnowledgePackContractError(f"profile {section} must be an object")
        for key in keys:
            _string_list(value.get(key), f"{section}.{key}")
    return data


def _knowledge_pack_root(name: str) -> Path:
    if not _SAFE_NAME.fullmatch(name):
        raise KnowledgePackContractError("Knowledge Pack name must match [A-Za-z0-9_-]+")
    root = knowledge_packs_dir() / name
    if root.is_symlink() or not root.is_dir():
        raise KnowledgePackContractError(f"unknown Knowledge Pack: {name}")
    return root


def load_knowledge_pack(name: str) -> KnowledgePack:
    """Load one named Knowledge Pack and all of its contracts."""
    root = _knowledge_pack_root(name)
    for contract_name in ("layout.json", "routing.json", "routing.md", "profile.json"):
        contract_path = root / contract_name
        if contract_path.is_symlink() or not contract_path.is_file():
            raise KnowledgePackContractError(
                f"layout contract must be a regular non-symlink file: {contract_path}"
            )
    manifest = _read_json(root / "layout.json")
    routing = _read_json(root / "routing.json")
    profile = _read_json(root / "profile.json")
    vault_template = root / "vault"
    if manifest.get("version") != 1 or manifest.get("name") != name:
        raise KnowledgePackContractError(f"layout manifest identity mismatch: {name}")
    if manifest.get("copy_policy") != "missing-only":
        raise KnowledgePackContractError(f"unsupported copy policy for layout: {name}")
    if manifest.get("profile") != "profile.json":
        raise KnowledgePackContractError(f"layout profile must reference profile.json: {name}")
    if not vault_template.is_dir() or vault_template.is_symlink():
        raise KnowledgePackContractError(f"layout vault template is unavailable: {name}")
    for key in ("routes", "content_roots", "system_dirs", "skip_dirs", "system_paths"):
        if key not in routing:
            raise KnowledgePackContractError(f"layout routing is missing {key!r}: {name}")
    categories = manifest.get("categories")
    if not isinstance(categories, list) or not all(isinstance(item, str) for item in categories):
        raise KnowledgePackContractError(f"layout categories are invalid: {name}")
    return KnowledgePack(
        name=name,
        description=str(manifest.get("description", "")),
        categories=tuple(categories),
        profile=_validate_profile(profile, name, routing),
        root=root,
        vault_template=vault_template,
        routing=routing,
    )


def list_knowledge_packs() -> dict[str, KnowledgePack]:
    """Return every valid bundled Knowledge Pack keyed by name."""
    result: dict[str, KnowledgePack] = {}
    for candidate in sorted(knowledge_packs_dir().iterdir()):
        if candidate.is_dir() and not candidate.is_symlink():
            result[candidate.name] = load_knowledge_pack(candidate.name)
    return result


def _digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _inventory_hash(pack: KnowledgePack) -> str:
    """Reproduce the portable inventory hash written by the Pack copier."""
    manifest = _read_json(pack.root / "layout.json")
    ignored = set(manifest.get("ignore", []))
    files: list[dict[str, Any]] = []
    directories: list[str] = []
    for candidate in sorted(pack.vault_template.rglob("*")):
        relative = candidate.relative_to(pack.vault_template).as_posix()
        if candidate.is_dir():
            directories.append(relative + "/")
        elif candidate.is_file() and candidate.name not in ignored:
            files.append({
                "path": relative,
                "size": candidate.stat().st_size,
                "sha256": _digest(candidate),
            })
    routing_path = pack.root / "routing.json"
    prompt_path = pack.root / "routing.md"
    portable = {
        "version": 1,
        "name": pack.name,
        "description": pack.description,
        "copy_policy": "missing-only",
        "categories": list(pack.categories),
        "manifest_sha256": _digest(pack.root / "layout.json"),
        "directories": directories,
        "files": files,
        "ignored": sorted(ignored),
        "routing": {
            "rules_sha256": _digest(routing_path),
            "rules": pack.routing,
            "prompt_sha256": _digest(prompt_path),
            "prompt": prompt_path.read_text(encoding="utf-8"),
        },
        "profile": {
            "sha256": _digest(pack.root / "profile.json"),
            "contract": pack.profile,
        },
    }
    encoded = json.dumps(portable, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def active_knowledge_pack(vault: Path, *, allow_uninitialized: bool = True) -> KnowledgePack:
    """Resolve and validate the Knowledge Pack selected by a vault marker.

    Read-only Python commands may inspect an uninitialized vault using the
    bundled ``default`` contract.  Initialized vaults always use their marker,
    and a stale marker fails closed.
    """
    vault = Path(vault)
    marker_path = vault / KNOWLEDGE_PACK_MARKER
    if not marker_path.is_file():
        if allow_uninitialized:
            return load_knowledge_pack("default")
        raise KnowledgePackContractError(
            f"active Knowledge Pack marker is missing: {marker_path}; run wiki-setup repair"
        )
    marker = _read_json(marker_path)
    if marker.get("version") != 1 or not isinstance(marker.get("name"), str):
        raise KnowledgePackContractError(f"active Knowledge Pack marker is invalid: {marker_path}")
    pack = load_knowledge_pack(marker["name"])
    expected = {
        "manifest_sha256": _digest(pack.root / "layout.json"),
        "inventory_sha256": _inventory_hash(pack),
        "routing_rules_sha256": _digest(pack.root / "routing.json"),
        "routing_prompt_sha256": _digest(pack.root / "routing.md"),
        "profile_sha256": _digest(pack.root / "profile.json"),
    }
    stale = [key for key, value in expected.items() if marker.get(key) != value]
    if stale:
        raise KnowledgePackContractError(
            f"active Knowledge Pack contract is stale ({', '.join(stale)}); "
            "run wiki-setup repair or an explicit Knowledge Pack migration"
        )
    return pack


def iter_content_pages(vault: Path) -> Iterator[Path]:
    """Yield Markdown pages within the active Pack's declared content roots."""
    vault = Path(vault)
    pack = active_knowledge_pack(vault)
    # Uninitialized vaults do not yet have a trustworthy declaration of
    # their content roots.  Keep read-only commands useful during migration by
    # scanning conservatively while excluding the default workflow's system
    # areas.  Once a marker exists, its declared roots are authoritative.
    if not (vault / KNOWLEDGE_PACK_MARKER).is_file():
        for path in vault.rglob("*.md"):
            relative = path.relative_to(vault)
            if any(
                part in pack.skip_dirs or part in _UNINITIALIZED_SKIP_DIRS
                for part in relative.parts
            ):
                continue
            yield path
        return
    for root_name in pack.content_roots:
        root = vault / root_name
        if not root.is_dir():
            continue
        for path in root.rglob("*.md"):
            relative = path.relative_to(vault)
            if any(part in pack.skip_dirs for part in relative.parts):
                continue
            yield path


def trust_ledger_path(vault: Path) -> Path:
    """Return the trust-ledger path under the active Pack marker directory."""
    marker_parent = KNOWLEDGE_PACK_MARKER.parent
    active_knowledge_pack(vault)
    return marker_parent / "trust-ledger.json"
