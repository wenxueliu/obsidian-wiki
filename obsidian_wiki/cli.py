"""obsidian-wiki installer CLI.

Python CLI for the pip-installed package. The standalone ``setup.py`` covers source checkouts. Skill content
lives inside the installed package (``obsidian_wiki/_data/skills``) instead of a
cloned repo, so this wires the bundled skills into every supported AI agent's
skills directory and writes ``~/.obsidian-wiki/config`` so the skills resolve
the vault from any project.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from obsidian_wiki import __version__
from obsidian_wiki.workflow_layout import (
    LayoutContractError,
    WorkflowLayout,
    layouts_dir,
    list_layouts,
    load_layout,
)
from obsidian_wiki.validate import validate_vault_pages, print_report
from obsidian_wiki.verify import (
    verify_completeness,
    verify_sections,
    print_report as print_verify_report,
    print_sections_report,
)

HOME = Path.home()
_IS_WINDOWS = os.name == "nt"
GLOBAL_CONFIG_DIR = (Path(os.environ.get("LOCALAPPDATA", "")) if _IS_WINDOWS else HOME) / ".obsidian-wiki"
GLOBAL_CONFIG = GLOBAL_CONFIG_DIR / "config"

# Skills usable from any project (no vault context needed beyond the global
# config). These are also installed globally for agents that only scope skills
# per-project, so cross-project sync/query/context work everywhere.
PORTABLE_SKILLS = ("wiki-update", "wiki-query", "wiki-context-pack")
OBSOLETE_MANAGED_SKILLS = ("wiki-ingest",)


class SchemaOptions(TypedDict):
    allowed_lifecycles: frozenset[str]
    allowed_relationship_types: frozenset[str]
    required_trust_fields: tuple[str, ...]
    schema_source: str


# ── Data resolution ──────────────────────────────────────────────────────────
# Works for both a built wheel (data under <pkg>/_data) and an editable/source
# checkout (data at the repo root next to the package).
def _pkg_dir() -> Path:
    return Path(__file__).resolve().parent


def skills_dir() -> Path:
    """Return the directory holding the bundled skill folders."""
    for cand in (_pkg_dir() / "_data" / "skills", _pkg_dir().parent / ".skills"):
        if cand.is_dir():
            return cand
    raise FileNotFoundError(
        "Could not locate bundled skills. Reinstall obsidian-wiki "
        "(`pip install --force-reinstall obsidian-wiki`)."
    )


def workflows_dir() -> Path:
    """Return workflow support files without depending on the caller's CWD."""
    for cand in (_pkg_dir() / "_data" / "workflows", _pkg_dir().parent / "workflows"):
        if cand.is_dir():
            return cand
    raise FileNotFoundError(
        "Could not locate bundled workflows. Reinstall obsidian-wiki "
        "(`pip install --force-reinstall obsidian-wiki`)."
    )


def bootstrap_dir() -> Path | None:
    """Return the directory containing agent bootstrap context files.

    For a wheel this is ``_data/bootstrap``; for a source checkout the files are
    spread across the repo root, so we return the repo root and resolve each
    file via the repo-relative layout in ``_bootstrap_files``.
    """
    built = _pkg_dir() / "_data" / "bootstrap"
    if built.is_dir():
        return built
    repo = _pkg_dir().parent
    if (repo / "AGENTS.md").is_file():
        return repo
    return None


def list_skills() -> list[str]:
    return sorted(p.name for p in skills_dir().iterdir() if p.is_dir())


# ── Skill installation ───────────────────────────────────────────────────────
def _remove_obsolete_managed_skills(target_dir: Path) -> None:
    """Remove only legacy skill installs recognizable as ours."""
    for name in OBSOLETE_MANAGED_SKILLS:
        candidate = target_dir / name
        if candidate.is_symlink():
            raw_target = os.readlink(candidate).replace("\\", "/")
            if raw_target.endswith((f"/.skills/{name}", f"/_data/skills/{name}")):
                candidate.unlink()
            continue
        marker = candidate / "SKILL.md"
        if not marker.is_file():
            continue
        try:
            content = marker.read_text(encoding="utf-8")
        except OSError:
            continue
        if "name: wiki-ingest" in content and "# Wiki Ingest — Packet Integration" in content:
            shutil.rmtree(candidate)


def install_skills(
    target_dir: Path,
    label: str,
    *,
    subset: tuple[str, ...] | None = None,
    mode: str = "symlink",
    quiet: bool = False,
) -> int:
    """Install bundled skills into *target_dir*. Returns the count installed."""
    src_root = skills_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    if subset is None:
        _remove_obsolete_managed_skills(target_dir)
    installed = 0
    for skill in sorted(p for p in src_root.iterdir() if p.is_dir()):
        name = skill.name
        if subset is not None and name not in subset:
            continue
        link_path = target_dir / name

        if link_path.is_symlink() or link_path.is_file():
            link_path.unlink()
        elif link_path.is_dir():
            # A real directory we previously copied here is safe to replace;
            # anything else is the user's and we leave it alone.
            if (link_path / "SKILL.md").exists():
                shutil.rmtree(link_path)
            else:
                print(f"   ⚠️  {link_path} is not a managed skill, skipping")
                continue

        if mode == "symlink":
            link_path.symlink_to(skill, target_is_directory=True)
        else:  # copy
            shutil.copytree(skill, link_path)

        if not (link_path / "SKILL.md").exists():
            raise RuntimeError(f"broken skill install: {link_path} -> {skill}")
        installed += 1

    if not quiet:
        print(f"✅  Installed {installed} skills → {label}")
    return installed


# Agents whose skills directory lives under $HOME. (path-under-home, label,
# subset). All get every skill — pip users have no cloned repo to host
# project-scoped skills, so everything must be globally discoverable.
GLOBAL_AGENT_DIRS: list[tuple[str, str, tuple[str, ...] | None]] = [
    (".claude/skills", "~/.claude/skills/ (Claude Code)", None),
    (".gemini/skills", "~/.gemini/skills/ (Gemini CLI)", None),
    (".gemini/antigravity/skills", "~/.gemini/antigravity/skills/ (Antigravity, legacy)", None),
    (".codex/skills", "~/.codex/skills/ (Codex)", None),
    (".hermes/skills", "~/.hermes/skills/ (Hermes default)", None),
    (".openclaw/skills", "~/.openclaw/skills/ (OpenClaw)", None),
    (".copilot/skills", "~/.copilot/skills/ (GitHub Copilot CLI)", None),
    (".trae/skills", "~/.trae/skills/ (Trae)", None),
    (".trae-cn/skills", "~/.trae-cn/skills/ (Trae CN)", None),
    (".kiro/skills", "~/.kiro/skills/ (Kiro CLI)", None),
    (".pi/agent/skills", "~/.pi/agent/skills/ (Pi)", None),
    (".agents/skills", "~/.agents/skills/ (OpenCode, Aider, Droid, generic)", None),
]


def install_global_skills(mode: str) -> None:
    for rel, label, subset in GLOBAL_AGENT_DIRS:
        install_skills(HOME / rel, label, subset=subset, mode=mode)
    _install_hermes_profiles(mode)


def _install_hermes_profiles(mode: str) -> None:
    """Install into the active and all named Hermes profiles."""
    hermes_home = os.environ.get("HERMES_HOME")
    handled: set[Path] = set()
    if hermes_home:
        hp = Path(hermes_home).expanduser()
        if hp != HOME / ".hermes":
            install_skills(hp / "skills", f"{hp}/skills/ (Hermes active profile)", mode=mode)
            handled.add(hp)
    profiles = HOME / ".hermes" / "profiles"
    if profiles.is_dir():
        for prof in sorted(p for p in profiles.iterdir() if p.is_dir()):
            if prof in handled:
                continue
            install_skills(
                prof / "skills",
                f"~/.hermes/profiles/{prof.name}/skills/ (Hermes profile: {prof.name})",
                mode=mode,
            )


# ── Project-local install (opt-in) ───────────────────────────────────────────
PROJECT_AGENT_DIRS = [
    (".claude/skills", "Claude Code"),
    (".cursor/skills", "Cursor"),
    (".windsurf/skills", "Windsurf"),
    (".agents/skills", "OpenCode / generic"),
    (".pi/skills", "Pi"),
    (".kiro/skills", "Kiro"),
]

# (bootstrap-relative source path, destination relative to project dir).
# The source path is resolved against bootstrap_dir() for a wheel, or mapped to
# the repo layout for a source checkout (see _resolve_bootstrap_src).
BOOTSTRAP_FILES = [
    ("AGENTS.md", "AGENTS.md"),
    ("cursor/rules/obsidian-wiki.mdc", ".cursor/rules/obsidian-wiki.mdc"),
    ("windsurf/rules/obsidian-wiki.md", ".windsurf/rules/obsidian-wiki.md"),
    ("kiro/steering/obsidian-wiki.md", ".kiro/steering/obsidian-wiki.md"),
    ("agent/rules/obsidian-wiki.md", ".agent/rules/obsidian-wiki.md"),
    ("agent/workflows/obsidian-wiki.md", ".agent/workflows/obsidian-wiki.md"),
    ("github/copilot-instructions.md", ".github/copilot-instructions.md"),
]

# AGENTS.md aliases created as symlinks within the project (single source).
AGENTS_ALIASES = ("CLAUDE.md", "GEMINI.md", ".hermes.md")


def _resolve_bootstrap_src(boot_root: Path, rel: str) -> Path | None:
    """Resolve a bootstrap source path under a wheel layout or repo layout."""
    built = boot_root / rel
    if built.exists():
        return built
    # Source checkout: boot_root is the repo root; files use the repo layout.
    repo_rel = {
        "AGENTS.md": "AGENTS.md",
        "cursor/rules/obsidian-wiki.mdc": ".cursor/rules/obsidian-wiki.mdc",
        "windsurf/rules/obsidian-wiki.md": ".windsurf/rules/obsidian-wiki.md",
        "kiro/steering/obsidian-wiki.md": ".kiro/steering/obsidian-wiki.md",
        "agent/rules/obsidian-wiki.md": ".agent/rules/obsidian-wiki.md",
        "agent/workflows/obsidian-wiki.md": ".agent/workflows/obsidian-wiki.md",
        "github/copilot-instructions.md": ".github/copilot-instructions.md",
    }.get(rel)
    if repo_rel and (boot_root / repo_rel).exists():
        return boot_root / repo_rel
    return None


def install_project(project_dir: Path, mode: str) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n📁  Installing project-local files → {project_dir}")
    for rel, _label in PROJECT_AGENT_DIRS:
        install_skills(project_dir / rel, f"{rel}/", mode=mode)

    boot_root = bootstrap_dir()
    if boot_root is None:
        print("   ⚠️  Bootstrap files not found in package; skipping context files")
        return

    for rel, dest in BOOTSTRAP_FILES:
        src = _resolve_bootstrap_src(boot_root, rel)
        if src is None:
            continue
        dst = project_dir / dest
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.is_symlink() or dst.exists():
            if dst.is_dir() and not dst.is_symlink():
                continue
            dst.unlink()
        shutil.copyfile(src, dst)
    print("✅  Installed bootstrap context files (AGENTS.md, rules, workflows)")

    # AGENTS.md aliases as relative symlinks (copy fallback for symlink-hostile FS).
    for alias in AGENTS_ALIASES:
        link = project_dir / alias
        if link.is_symlink() or link.exists():
            link.unlink()
        try:
            link.symlink_to("AGENTS.md")
        except OSError:
            shutil.copyfile(project_dir / "AGENTS.md", link)
    print(f"✅  Linked AGENTS.md aliases ({', '.join(AGENTS_ALIASES)})")


# ── Config ───────────────────────────────────────────────────────────────────
def _read_config_value(key: str) -> str:
    if not GLOBAL_CONFIG.is_file():
        return ""
    for line in GLOBAL_CONFIG.read_text().splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip('"')
    return ""


def _read_config() -> dict[str, str]:
    if not GLOBAL_CONFIG.is_file():
        return {}
    values: dict[str, str] = {}
    for raw in GLOBAL_CONFIG.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"')
    return values


def resolve_vault_path(cli_vault: str | None) -> str:
    if cli_vault:
        return os.path.expanduser(cli_vault)
    existing = _read_config_value("OBSIDIAN_VAULT_PATH")
    if existing and existing != "/path/to/your/vault":
        return existing
    if sys.stdin.isatty():
        try:
            entered = input("  Where is your Obsidian vault? (absolute path): ").strip()
        except EOFError:
            entered = ""
        if entered:
            return os.path.expanduser(entered)
    return existing


def write_config(vault_path: str) -> None:
    GLOBAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    # OBSIDIAN_WIKI_REPO points at the bundled data root so skills that reference
    # framework assets (templates, references) can find them post-install.
    repo_root = skills_dir().parent
    GLOBAL_CONFIG.write_text(
        f'OBSIDIAN_VAULT_PATH="{vault_path}"\n'
        f'OBSIDIAN_WIKI_REPO="{repo_root}"\n'
        f'OBSIDIAN_WIKI_VERSION="{__version__}"\n'
    )
    print(f"✅  Global config written to {GLOBAL_CONFIG}")


def ensure_global_writing_profile() -> Path:
    """Create the editable global writing profile without replacing user preferences."""
    GLOBAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    target = GLOBAL_CONFIG_DIR / "WRITING.md"
    if target.exists():
        return target
    template = skills_dir() / "llm-wiki" / "references" / "WRITING.md"
    target.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    return target


def scaffold_vault(vault_path: Path, layout: WorkflowLayout | None = None) -> bool:
    """Create the vault directory structure and special files if they don't exist yet.

    Idempotent: existing files/dirs are left untouched. Returns True if the vault
    directory itself had to be created (i.e. this is a brand new vault).
    """
    if layout is None:
        layout = load_layout("default")

    created = not vault_path.is_dir()
    copier = workflows_dir() / "scripts" / "apply_wiki_layout.py"
    with tempfile.TemporaryDirectory(prefix="obsidian-wiki-layout-") as output_dir:
        result = subprocess.run(
            [
                sys.executable,
                str(copier),
                "apply",
                "--layouts-dir",
                str(layouts_dir()),
                "--layout",
                layout.name,
                "--vault",
                str(vault_path.expanduser().resolve()),
                "--output-dir",
                output_dir,
            ],
            capture_output=True,
            text=True,
        )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise LayoutContractError(f"could not apply workflow layout: {detail}")

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    index_md = vault_path / "index.md"
    if not index_md.exists():
        sections = "\n\n".join(
            f"## {cat.title().replace('-', ' ')}" for cat in layout.categories
        )
        index_md.write_text(
            "---\n"
            "title: Wiki Index\n"
            "---\n\n"
            "# Wiki Index\n\n"
            f"*This index is automatically maintained. Last updated: {timestamp}*\n\n"
            f"{sections}\n"
        )

    log_md = vault_path / "log.md"
    if not log_md.exists():
        log_md.write_text(
            "---\n"
            "title: Wiki Log\n"
            "---\n\n"
            "# Wiki Log\n\n"
            f'- [{timestamp}] INIT vault_path="{vault_path}" '
            f"categories={','.join(layout.categories)}\n"
        )

    hot_md = vault_path / "hot.md"
    if not hot_md.exists():
        hot_md.write_text(
            "---\n"
            "title: Hot Cache\n"
            f"updated: {timestamp}\n"
            "---\n\n"
            "# Hot Cache\n\n"
            "*A ~500-word semantic snapshot of recent activity. Updated after every major write operation.*\n\n"
            "## Recent Activity\n\n"
            f"- [{timestamp}] INIT — vault created at {vault_path}\n\n"
            "## Active Threads\n\n"
            "*None yet — start ingesting sources to populate.*\n\n"
            "## Key Takeaways\n\n"
            "*None yet.*\n\n"
            "## Flagged Contradictions\n\n"
            "*None yet.*\n"
        )

    manifest_json = vault_path / ".manifest.json"
    if not manifest_json.exists():
        manifest_json.write_text("{}\n")

    app_json = vault_path / ".obsidian" / "app.json"
    if not app_json.exists():
        app_json.write_text(
            json.dumps(
                {
                    "strictLineBreaks": False,
                    "showFrontmatter": False,
                    "defaultViewMode": "preview",
                    "livePreview": True,
                },
                indent=2,
            )
            + "\n"
        )

    appearance_json = vault_path / ".obsidian" / "appearance.json"
    if not appearance_json.exists():
        appearance_json.write_text(json.dumps({"baseFontSize": 16}, indent=2) + "\n")

    return created


def _check_stale() -> None:
    """Warn if the installed version doesn't match when setup last ran, or if skills are missing."""
    if not GLOBAL_CONFIG.is_file():
        print(
            f"⚠️  obsidian-wiki {__version__} is installed but setup has never been run.\n"
            f"   Run: obsidian-wiki setup --vault /path/to/your/vault",
            file=sys.stderr,
        )
        return

    setup_version = _read_config_value("OBSIDIAN_WIKI_VERSION")
    if setup_version and setup_version != __version__:
        print(
            f"⚠️  obsidian-wiki upgraded {setup_version} → {__version__} but setup hasn't been re-run.\n"
            f"   New skills won't be available until you run: obsidian-wiki setup",
            file=sys.stderr,
        )
        return

    # Even if the version matches, check that ~/.claude/skills has the full set.
    claude_skills_dir = HOME / ".claude" / "skills"
    if claude_skills_dir.is_dir():
        bundled = set(list_skills())
        installed = {p.name for p in claude_skills_dir.iterdir() if p.is_dir()}
        missing = bundled - installed
        if missing:
            print(
                f"⚠️  {len(missing)} skill(s) missing from ~/.claude/skills/ "
                f"(e.g. {', '.join(sorted(missing)[:3])}{', ...' if len(missing) > 3 else ''}).\n"
                f"   Run: obsidian-wiki setup",
                file=sys.stderr,
            )


def _doctor_add(
    checks: list[dict[str, str]],
    *,
    name: str,
    status: str,
    detail: str,
    hint: str = "",
) -> None:
    checks.append({
        "name": name,
        "status": status,
        "detail": detail,
        "hint": hint,
    })


def _doctor_status(checks: list[dict[str, str]]) -> str:
    statuses = {check["status"] for check in checks}
    if "fail" in statuses:
        return "fail"
    if "warn" in statuses:
        return "warn"
    return "pass"


def _required_vault_paths(vault: Path) -> list[Path]:
    return [
        vault / "index.md",
        vault / "log.md",
        vault / "hot.md",
        vault / ".manifest.json",
    ]


def _doctor_project_check(project_dir: Path) -> dict[str, str]:
    required = [project_dir / "AGENTS.md", *[project_dir / dest for _src, dest in BOOTSTRAP_FILES[1:]]]
    missing = [str(path.relative_to(project_dir)) for path in required if not path.exists()]
    if missing:
        return {
            "status": "warn",
            "detail": f"missing {len(missing)} bootstrap file(s)",
            "hint": f"run: obsidian-wiki setup --project {project_dir}",
        }
    aliases_missing = [alias for alias in AGENTS_ALIASES if not (project_dir / alias).exists()]
    if aliases_missing:
        return {
            "status": "warn",
            "detail": f"missing AGENTS aliases: {', '.join(aliases_missing)}",
            "hint": f"run: obsidian-wiki setup --project {project_dir}",
        }
    return {"status": "pass", "detail": "bootstrap files and aliases present", "hint": ""}


def run_doctor(*, vault_override: str | None = None, project_dir: str | None = None) -> dict[str, object]:
    checks: list[dict[str, str]] = []

    try:
        bundled = list_skills()
        _doctor_add(
            checks,
            name="bundled-skills",
            status="pass" if bundled else "fail",
            detail=f"{len(bundled)} bundled skill(s) available",
            hint="" if bundled else "reinstall obsidian-wiki",
        )
    except FileNotFoundError as exc:
        _doctor_add(checks, name="bundled-skills", status="fail", detail=str(exc), hint="reinstall obsidian-wiki")
        bundled = []

    boot = bootstrap_dir()
    _doctor_add(
        checks,
        name="bootstrap-assets",
        status="pass" if boot else "fail",
        detail=str(boot) if boot else "bootstrap files not found",
        hint="" if boot else "reinstall obsidian-wiki",
    )

    config = _read_config()
    config_present = GLOBAL_CONFIG.is_file()
    _doctor_add(
        checks,
        name="global-config",
        status="pass" if config_present else "fail",
        detail=str(GLOBAL_CONFIG) if config_present else "global config not written",
        hint="" if config_present else "run: obsidian-wiki setup --vault /path/to/your/vault",
    )

    vault_path = ""
    if vault_override:
        vault_path = os.path.expanduser(vault_override)
    elif config_present:
        vault_path = config.get("OBSIDIAN_VAULT_PATH", "")

    if not vault_path:
        _doctor_add(
            checks,
            name="vault-config",
            status="fail",
            detail="OBSIDIAN_VAULT_PATH is not set",
            hint="run: obsidian-wiki setup --vault /path/to/your/vault",
        )
        vault = None
    else:
        vault = Path(vault_path).expanduser().resolve()
        _doctor_add(
            checks,
            name="vault-config",
            status="pass",
            detail=str(vault),
            hint="",
        )

    setup_version = config.get("OBSIDIAN_WIKI_VERSION", "") if config_present else ""
    if setup_version and setup_version != __version__:
        _doctor_add(
            checks,
            name="setup-version",
            status="warn",
            detail=f"setup ran with {setup_version}; installed package is {__version__}",
            hint="run: obsidian-wiki setup",
        )
    elif config_present:
        _doctor_add(
            checks,
            name="setup-version",
            status="pass",
            detail=f"setup version matches installed package ({__version__})" if setup_version else "setup version not recorded",
            hint="" if setup_version else "re-run setup to record install metadata",
        )

    if vault is not None:
        if vault.is_dir():
            _doctor_add(checks, name="vault-path", status="pass", detail="vault directory exists", hint="")
            missing_core = [str(path.relative_to(vault)) for path in _required_vault_paths(vault) if not path.exists()]
            if missing_core:
                _doctor_add(
                    checks,
                    name="vault-core-files",
                    status="warn",
                    detail=f"missing {len(missing_core)} core file(s): {', '.join(missing_core)}",
                    hint="run the wiki setup skill or create the missing files",
                )
            else:
                _doctor_add(checks, name="vault-core-files", status="pass", detail="core vault files present", hint="")

            manifest_path = vault / ".manifest.json"
            if manifest_path.exists():
                try:
                    data = json.loads(manifest_path.read_text(encoding="utf-8"))
                    sources = data.get("sources", {})
                    _doctor_add(
                        checks,
                        name="manifest-json",
                        status="pass",
                        detail=f"valid JSON with {len(sources)} tracked source(s)",
                        hint="",
                    )
                except (json.JSONDecodeError, OSError) as exc:
                    _doctor_add(
                        checks,
                        name="manifest-json",
                        status="fail",
                        detail=f"invalid manifest: {exc}",
                        hint="repair or regenerate .manifest.json",
                    )
        else:
            _doctor_add(
                checks,
                name="vault-path",
                status="fail",
                detail=f"vault directory not found: {vault}",
                hint="fix OBSIDIAN_VAULT_PATH or re-run setup",
            )

    agent_summaries: list[str] = []
    partial_agents: list[str] = []
    full_agents = 0
    bundled_set = set(bundled)
    for rel, label, _subset in GLOBAL_AGENT_DIRS:
        agent_dir = HOME / rel
        if not agent_dir.is_dir():
            continue
        installed = {p.name for p in agent_dir.iterdir() if (p.is_dir() or p.is_symlink())}
        missing = bundled_set - installed
        count = len(installed & bundled_set)
        agent_summaries.append(f"{label}: {count}/{len(bundled_set)}")
        if missing:
            partial_agents.append(label)
        else:
            full_agents += 1

    if not agent_summaries:
        _doctor_add(
            checks,
            name="agent-installs",
            status="warn",
            detail="no global agent skill installs found",
            hint="run: obsidian-wiki setup",
        )
    elif partial_agents:
        _doctor_add(
            checks,
            name="agent-installs",
            status="warn",
            detail="; ".join(agent_summaries),
            hint="re-run obsidian-wiki setup to fill missing skills",
        )
    else:
        _doctor_add(
            checks,
            name="agent-installs",
            status="pass",
            detail=f"{full_agents} agent install(s) fully provisioned",
            hint="",
        )

    if project_dir:
        project = Path(project_dir).expanduser().resolve()
        if project.is_dir():
            project_check = _doctor_project_check(project)
            _doctor_add(
                checks,
                name="project-bootstrap",
                status=project_check["status"],
                detail=project_check["detail"],
                hint=project_check["hint"],
            )
        else:
            _doctor_add(
                checks,
                name="project-bootstrap",
                status="fail",
                detail=f"project directory not found: {project}",
                hint="pass an existing directory",
            )

    return {
        "status": _doctor_status(checks),
        "checks": checks,
    }


def _print_doctor(report: dict[str, object]) -> None:
    icon = {"pass": "✅", "warn": "⚠️ ", "fail": "❌"}
    print(f"obsidian-wiki doctor: {report['status']}")
    for check in report["checks"]:
        name = check["name"]
        status = check["status"]
        detail = check["detail"]
        hint = check["hint"]
        print(f"{icon.get(status, '•')} {name}: {detail}")
        if hint:
            print(f"   hint: {hint}")


# ── Commands ─────────────────────────────────────────────────────────────────
def _maybe_configure_sync(vault_path: Path, remote_arg: str | None) -> bool:
    """Offer (or apply) GitHub sync setup for the vault.

    Non-interactive (`--remote` passed, or no TTY and no remote given): only
    acts when a remote was explicitly supplied. Interactive: prompts, mirroring
    setup, so pip/uv installs get the same offer shell/curl installs
    always had (see #153).
    """
    from obsidian_wiki.sync import configure_sync, get_remote

    if get_remote(vault_path):
        return True  # already configured — nothing to do

    remote = remote_arg
    if not remote:
        if not sys.stdin.isatty():
            return False
        print()
        try:
            answer = input("  Set up GitHub sync for your vault? [y/N]: ").strip()
        except EOFError:
            answer = ""
        if answer.lower() != "y":
            return False
        try:
            remote = input("  GitHub repo URL (e.g. https://github.com/you/my-wiki.git): ").strip()
        except EOFError:
            remote = ""
        if not remote:
            return False

    try:
        messages = configure_sync(vault_path, remote)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"⚠️  GitHub sync setup skipped: {exc}", file=sys.stderr)
        return False
    for m in messages:
        print(f"✅  {m}")
    print("✅  Run `obsidian-wiki sync` any time to commit and push vault changes.")
    return True


def cmd_setup(args: argparse.Namespace) -> int:
    if args.list_layouts:
        layouts = list_layouts()
        if not layouts:
            print("No workflow layouts found.")
        else:
            print("\nAvailable Knowledge Packs (Profile + Layout):\n")
            for name, layout in sorted(layouts.items()):
                print(f"  {name:20s}  {layout.profile['description']} ← workflow")
            print(f"\nUse: obsidian-wiki setup --layout <name>")
        return 0

    if args.layout:
        try:
            layout = load_layout(args.layout)
        except LayoutContractError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
    else:
        layout = load_layout("default")

    mode = "symlink" if (not _IS_WINDOWS and not args.copy) else "copy"
    print("\n╔══════════════════════════════════════════════════╗")
    print("║         obsidian-wiki — Agent Setup              ║")
    print("╚══════════════════════════════════════════════════╝\n")

    vault_path = resolve_vault_path(args.vault)
    write_config(vault_path)
    writing_profile = ensure_global_writing_profile()
    if not vault_path:
        print("    → Vault path not set yet. Re-run with `--vault /path/to/vault`")
        print("      or edit OBSIDIAN_VAULT_PATH in ~/.obsidian-wiki/config.")
    else:
        vault_dir = Path(vault_path).expanduser()
        vault_created = scaffold_vault(vault_dir, layout=layout)
        print(f"   Layout: {layout.name}")
        if vault_created:
            print(f"✅  Vault created at {vault_dir}")
        else:
            print(f"✅  Vault verified at {vault_dir}")

    if not args.project_only:
        print()
        install_global_skills(mode)

    if args.project is not None:
        project_dir = Path(args.project or os.getcwd()).expanduser().resolve()
        install_project(project_dir, mode)

    sync_configured = False
    if vault_path and Path(vault_path).expanduser().is_dir():
        sync_configured = _maybe_configure_sync(Path(vault_path).expanduser(), args.remote)

    n = len(list_skills())
    print("\n───────────────────────────────────────────────────")
    print(" Setup complete!\n")
    print(f" Skills installed: {n}  (mode: {mode})")
    if vault_path:
        print(f" Vault:            {vault_path}")
    print(f" Writing profile:  {writing_profile.resolve()}")
    if sync_configured:
        print(" GitHub sync:      obsidian-wiki sync")
    print("\n Next steps:")
    print("   1. Open a project in your agent")
    print('   2. Say: "set up my wiki"\n')
    print(" From any project:")
    print("   /wiki-update    → sync knowledge into your vault")
    print("   /wiki-query     → ask questions against your wiki")
    print("   /wiki-context-pack → compile bounded context for another agent")
    print("───────────────────────────────────────────────────\n")
    return 0


def cmd_sync_setup(args: argparse.Namespace) -> int:
    from obsidian_wiki.sync import configure_sync

    vault_str = resolve_vault_path(args.vault)
    if not vault_str:
        print("error: no vault configured — pass --vault or run `obsidian-wiki setup` first", file=sys.stderr)
        return 1
    vault_path = Path(vault_str).expanduser()
    try:
        messages = configure_sync(vault_path, args.remote)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for m in messages:
        print(f"✅  {m}")
    print("✅  Run `obsidian-wiki sync` any time to commit and push vault changes.")
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    from obsidian_wiki.sync import run_sync

    vault_str = resolve_vault_path(args.vault)
    if not vault_str:
        print("error: no vault configured — pass --vault or run `obsidian-wiki setup` first", file=sys.stderr)
        return 1
    code, message = run_sync(Path(vault_str).expanduser())
    print(message)
    return code


def cmd_graph_query(args: argparse.Namespace) -> int:
    from obsidian_wiki.graphrag import query
    vault = Path(args.vault).expanduser().resolve()
    if not vault.is_dir():
        print(f"error: vault not found: {vault}", file=sys.stderr)
        return 1
    result = query(vault, args.question, top_n=args.top, max_should_read=args.max_read)
    if args.pretty:
        print(json.dumps(result, indent=2))
    else:
        print(json.dumps(result))
    return 0


def cmd_batch_plan(args: argparse.Namespace) -> int:
    from obsidian_wiki.batch import plan_batches
    source_dir = Path(args.source_dir).expanduser().resolve()
    vault = Path(args.vault).expanduser().resolve()
    if not source_dir.is_dir():
        print(f"error: source directory not found: {source_dir}", file=sys.stderr)
        return 1
    result = plan_batches(
        source_dir,
        vault,
        max_batch_mb=args.max_mb,
        max_batch_files=args.max_files,
        skip_unchanged=not args.no_cache,
        include_code=args.include_code,
    )
    if args.pretty:
        print(json.dumps(result, indent=2))
    else:
        print(json.dumps(result))
    return 0


def cmd_graph(args: argparse.Namespace) -> int:
    """Delegate to graph.py CLI (networkx-based graph queries)."""
    from obsidian_wiki.graph import build_graph, load_graph
    from obsidian_wiki.graph import find_paths, neighbors, centrality, tag_subgraph, communities, stats
    import networkx as nx  # noqa: F811 — validated by graph.py's import guard

    vault = str(Path(args.vault).expanduser().resolve())
    if not Path(vault).is_dir():
        print(f"error: vault not found: {vault}", file=sys.stderr)
        return 1

    try:
        if args.no_cache:
            G = build_graph(vault)
        else:
            G = load_graph(vault)
    except ImportError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    result: Any = None
    if args.graph_cmd == "paths":
        result = find_paths(G, args.source, args.target, args.max_len, args.relation)
    elif args.graph_cmd == "neighbors":
        result = neighbors(G, args.slug, args.radius)
    elif args.graph_cmd == "centrality":
        result = centrality(G, args.method, args.top, args.tag)
    elif args.graph_cmd == "tag-subgraph":
        sg = tag_subgraph(G, args.tag, args.min_degree)
        result = nx.node_link_data(sg)
        if args.output:
            Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2))
            print(f"Saved subgraph to {args.output}")
            return 0
    elif args.graph_cmd == "communities":
        result = communities(G)
    elif args.graph_cmd == "stats":
        result = stats(G)
    else:
        result = stats(G)

    indent = 2 if args.pretty else None
    print(json.dumps(result, ensure_ascii=False, indent=indent))
    return 0


def cmd_graph_analyse(args: argparse.Namespace) -> int:
    from obsidian_wiki.graph_analysis import analyse_vault
    vault = Path(args.vault).expanduser().resolve()
    if not vault.is_dir():
        print(f"error: vault not found: {vault}", file=sys.stderr)
        return 1
    result = analyse_vault(vault, top_n=args.top)
    if args.pretty:
        print(json.dumps(result, indent=2))
    else:
        print(json.dumps(result))
    return 0


DEFAULT_CLAUDE_DIR = "~/.claude"
DEFAULT_BRAIN_DIR = "~/.claude/session-brain"


def _brain_dir(args: argparse.Namespace) -> Path:
    return Path(
        args.out or os.environ.get("WIKI_SESSION_BRAIN_DIR") or DEFAULT_BRAIN_DIR
    ).expanduser()


def _skip_list(args: argparse.Namespace) -> list[str]:
    raw = args.skip or os.environ.get("WIKI_SKIP_PROJECTS", "")
    return [s.strip() for s in raw.split(",") if s.strip()]


def cmd_sessions_build(args: argparse.Namespace) -> int:
    from obsidian_wiki.session_graph import build
    claude_dir = Path(args.claude_dir).expanduser()
    bookmarks = Path(args.bookmarks).expanduser() if args.bookmarks else \
        Path("~/.bookmark-agent/bookmarks.json").expanduser()

    def progress(message: str) -> None:
        if args.verbose:
            print(f"… {message}", file=sys.stderr)

    result = build(
        claude_dir,
        _brain_dir(args),
        k=args.k,
        min_sim=args.min_sim,
        mutual=args.mutual,
        half_life_days=args.half_life,
        full=args.full,
        since=args.since,
        skip=_skip_list(args),
        bookmarks_path=bookmarks,
        write_html=not args.no_html,
        progress=progress,
    )
    if args.json:
        print(json.dumps(result, indent=2) if args.pretty else json.dumps(result))
        return 0

    stats = result["stats"]
    print(f"{stats['sessions']} sessions ({stats['full']} with transcripts, "
          f"{stats['thin']} history-only) · {stats['edges']} links · "
          f"{stats['clusters']} topics · {stats['unclustered']} unclustered")
    print(f"read {stats['read_this_run']} this run, reused {stats['reused']} cached")
    for cluster in result["clusters"][:15]:
        flag = " [dormant]" if cluster["dormant"] else (" [hot]" if cluster["momentum"] >= 2 else "")
        print(f"  {cluster['size']:4}  {cluster['name'] or cluster['label']}{flag}")
    if result["unnamed"]:
        print(f"{result['unnamed']} unnamed topic(s) — run the session-brain skill to name them")
    print(f"-> {result['out_dir']}")
    return 0


def cmd_sessions_query(args: argparse.Namespace) -> int:
    from obsidian_wiki.session_query import query
    try:
        result = query(
            _brain_dir(args), args.question,
            top_n=args.top, max_load=args.max_load, half_life_days=args.half_life,
            project=args.project, cluster=args.cluster, since=args.since,
            min_score=args.min_score,
        )
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2) if args.pretty else json.dumps(result))
        return 0
    if not result["candidates"]:
        print("no matching sessions")
        return 0
    for c in result["candidates"]:
        loadable = "" if c["loadable"] else "  (no transcript)"
        print(f"{c['score']:.2f}  {c['end_ts'][:10]}  {c['project'][:18]:18}  "
              f"{(c['title'] or '(untitled)')[:52]:52}{loadable}")
        print(f"      {c['why']}")
    if result["should_load"]:
        print(f"\nload: {result['load_command']}")
    return 0


def cmd_sessions_show(args: argparse.Namespace) -> int:
    from obsidian_wiki.session_query import show
    try:
        result = show(_brain_dir(args), args.session_id, neighbors=args.neighbors)
    except (FileNotFoundError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2) if args.pretty else json.dumps(result))
    return 0


def cmd_sessions_clusters(args: argparse.Namespace) -> int:
    from obsidian_wiki.session_graph import load_graph
    try:
        _, clusters_doc = load_graph(_brain_dir(args))
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    clusters = clusters_doc.get("clusters", [])
    if args.unnamed:
        clusters = [c for c in clusters if not c.get("name")]
    clusters = clusters[:args.top]
    if args.json:
        payload = {"clusters": clusters}
        print(json.dumps(payload, indent=2) if args.pretty else json.dumps(payload))
        return 0
    for c in clusters:
        flag = " [dormant]" if c.get("dormant") else (" [hot]" if c.get("momentum", 0) >= 2 else "")
        print(f"{c['id']:3}  {c['size']:4}  {c.get('name') or c['label']}{flag}")
        print(f"      terms: {', '.join(t for t, _ in c['top_terms'][:8])}")
    return 0


def cmd_sessions_name(args: argparse.Namespace) -> int:
    from obsidian_wiki.session_graph import set_cluster_names
    raw = sys.stdin.read() if args.from_file == "-" else \
        Path(args.from_file).expanduser().read_text(encoding="utf-8")
    try:
        updates = json.loads(raw)
    except ValueError as exc:
        print(f"error: invalid JSON: {exc}", file=sys.stderr)
        return 1
    if not isinstance(updates, list):
        print('error: expected a JSON array of {"id": N, "name": "...", "summary": "..."}',
              file=sys.stderr)
        return 1
    try:
        result = set_cluster_names(_brain_dir(args), updates)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


def cmd_cache_check(args: argparse.Namespace) -> int:
    from obsidian_wiki.cache import check_sources
    vault = Path(args.vault).expanduser().resolve()
    sources = [Path(p).expanduser().resolve() for p in args.sources]
    result = check_sources(vault, sources)
    if args.pretty:
        print(json.dumps(result, indent=2))
    else:
        print(json.dumps(result))
    return 0


def cmd_cache_update(args: argparse.Namespace) -> int:
    from obsidian_wiki.cache import update_source
    vault = Path(args.vault).expanduser().resolve()
    source = Path(args.source).expanduser().resolve()
    pages = args.pages or []
    h = update_source(vault, source, pages_produced=pages)
    print(json.dumps({"path": str(source), "content_hash": h}))
    return 0


def cmd_cache_hash(args: argparse.Namespace) -> int:
    from obsidian_wiki.cache import hash_file
    path = Path(args.path).expanduser().resolve()
    if not path.exists():
        print(f"error: {path} does not exist", file=sys.stderr)
        return 1
    print(json.dumps({"path": str(path), "sha256": hash_file(path)}))
    return 0


def cmd_text_chunk_plan(args: argparse.Namespace) -> int:
    from obsidian_wiki.text_chunker import TextChunkError, plan_text_chunks

    try:
        strategy_options = _load_strategy_options(args)
        plan = plan_text_chunks(
            Path(args.source),
            target_budget=args.target_budget,
            hard_budget=args.hard_budget,
            min_budget=args.min_budget,
            chunk_strategy=args.chunk_strategy,
            strategy_options=strategy_options,
            allow_unsafe_hard_budget=args.allow_unsafe_hard_budget,
        )
    except (OSError, ValueError, TextChunkError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2 if args.pretty else None))
    return 0


def cmd_text_chunk_strategies(args: argparse.Namespace) -> int:
    from obsidian_wiki.text_chunker import available_chunk_strategies

    result = {"strategies": list(available_chunk_strategies())}
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0


def cmd_text_chunk_read(args: argparse.Namespace) -> int:
    from obsidian_wiki.text_chunker import TextChunkError, read_text_chunk, unit_for_range

    try:
        unit = unit_for_range(
            start_byte=args.start_byte,
            end_byte=args.end_byte,
            expected_hash=args.expect_hash,
            allow_unsafe_hard_budget=args.allow_unsafe_hard_budget,
        )
        content = read_text_chunk(Path(args.source), unit)
    except (OSError, TextChunkError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    # Binary stdout avoids both an appended newline and platform newline
    # translation, preserving the exact UTF-8 bytes of the requested range.
    sys.stdout.buffer.write(content.encode("utf-8"))
    return 0


def _emit_workflow_json(value: dict, *, pretty: bool, output: str | None) -> None:
    rendered = json.dumps(value, ensure_ascii=False, indent=2 if pretty else None) + "\n"
    if output is None:
        sys.stdout.write(rendered)
        return
    target = Path(output).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp-{os.getpid()}")
    try:
        temporary.write_text(rendered, encoding="utf-8")
        os.replace(temporary, target)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    print(json.dumps({"output": str(target)}))


def cmd_text_ingest_plan(args: argparse.Namespace) -> int:
    from obsidian_wiki.ingest_pipeline import (
        PipelineContractError,
        create_or_resume_job,
        summarize_job,
    )

    try:
        strategy_options = _load_strategy_options(args)
        job_dir, job, resumed = create_or_resume_job(
            Path(args.source), Path(args.vault),
            target_budget=args.target_budget,
            hard_budget=args.hard_budget,
            min_budget=args.min_budget,
            chunk_strategy=args.chunk_strategy,
            strategy_options=strategy_options,
            direct_extract_max_bytes=args.direct_extract_max_bytes,
            write_mode=args.write_mode,
        )
        result = summarize_job(job_dir, job)
        result["resumed"] = resumed
        _emit_workflow_json(result, pretty=args.pretty, output=args.output)
    except (OSError, ValueError, PipelineContractError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_text_ingest_status(args: argparse.Namespace) -> int:
    from obsidian_wiki.ingest_pipeline import PipelineContractError, summarize_job

    try:
        result = summarize_job(Path(args.job))
        _emit_workflow_json(result, pretty=args.pretty, output=args.output)
    except (OSError, ValueError, PipelineContractError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_text_ingest_report(args: argparse.Namespace) -> int:
    from obsidian_wiki.ingest_pipeline import (
        PipelineContractError,
        build_completion_report,
        render_completion_report_markdown,
    )

    try:
        result = build_completion_report(Path(args.job))
        markdown_target = Path(args.markdown_output).expanduser().resolve()
        markdown_target.parent.mkdir(parents=True, exist_ok=True)
        markdown_temporary = markdown_target.with_name(
            f".{markdown_target.name}.tmp-{os.getpid()}"
        )
        try:
            markdown_temporary.write_text(
                render_completion_report_markdown(result), encoding="utf-8"
            )
            os.replace(markdown_temporary, markdown_target)
        finally:
            try:
                markdown_temporary.unlink()
            except FileNotFoundError:
                pass
        _emit_workflow_json(result, pretty=args.pretty, output=args.output)
    except (OSError, ValueError, PipelineContractError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def _load_bound_packet(job_dir: Path, packet_arg: str) -> tuple[dict, dict, dict, dict, str]:
    """Load one Packet and prove that it is the next writable unit for its Job source."""
    from obsidian_wiki.ingest_pipeline import (
        PipelineContractError,
        load_job,
        resolve_packet_path,
        validate_packet,
    )

    directory = job_dir.expanduser().resolve()
    job = load_job(directory)
    packet_path = resolve_packet_path(directory, packet_arg)
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    if not isinstance(packet, dict):
        raise PipelineContractError("Packet must be a JSON object")
    packet_source = packet.get("source", {})
    packet_unit = packet.get("unit", {})
    source = next(
        (
            item for item in job.get("sources", [])
            if item.get("source_id") == packet_source.get("source_id")
        ),
        None,
    )
    if source is None:
        raise PipelineContractError("Packet source is not present in the Job")
    validate_packet(packet, job_source=source)
    unit_id = packet_unit.get("unit_id")
    units = source.get("units", [])
    target_index = next(
        (index for index, unit in enumerate(units) if unit.get("unit_id") == unit_id),
        None,
    )
    if target_index is None:
        raise PipelineContractError("Packet unit is not present in the Job")
    unit = units[target_index]
    if unit.get("transport", "packet") != "packet":
        raise PipelineContractError("Job unit is not planned for Packet transport")
    expected_path = resolve_packet_path(directory, unit.get("packet_path", ""))
    if packet_path != expected_path:
        raise PipelineContractError("Packet path does not match the planned Job unit")
    write_mode = job.get("write_mode", "direct")
    allowed_previous = {"integrated"} if write_mode == "direct" else {
        "staged", "approved_waiting_order", "integrated",
    }
    if any(previous.get("status") not in allowed_previous for previous in units[:target_index]):
        raise PipelineContractError("Packet is not the next writable unit for its source")
    if unit.get("status") in {"integrated", "staged", "approved_waiting_order"}:
        raise PipelineContractError("Packet unit has already advanced")
    relative_packet = packet_path.relative_to(directory).as_posix()
    return job, packet, source, unit, relative_packet


def cmd_text_ingest_packet_check(args: argparse.Namespace) -> int:
    from obsidian_wiki.ingest_pipeline import PipelineContractError

    try:
        job, packet, source, unit, relative_packet = _load_bound_packet(
            Path(args.job), args.packet
        )
        result = {
            "status": "valid",
            "job_id": job.get("job_id"),
            "write_mode": job.get("write_mode", "direct"),
            "packet_path": relative_packet,
            "packet_id": packet.get("packet_id"),
            "source_id": source.get("source_id"),
            "unit_id": unit.get("unit_id"),
            "range": {
                key: unit.get(key)
                for key in ("start_line", "end_line", "start_byte", "end_byte")
            },
        }
        _emit_workflow_json(result, pretty=args.pretty, output=args.output)
    except (OSError, ValueError, json.JSONDecodeError, PipelineContractError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_text_ingest_unit_advance(args: argparse.Namespace) -> int:
    from obsidian_wiki.ingest_pipeline import (
        PipelineContractError,
        mark_unit_integrated,
        mark_unit_staged,
        summarize_job,
        write_job,
    )

    try:
        job_dir = Path(args.job).expanduser().resolve()
        job, _packet, source, unit, relative_packet = _load_bound_packet(
            job_dir, args.packet
        )
        write_mode = job.get("write_mode", "direct")
        if args.mode != write_mode:
            raise PipelineContractError(
                f"advance mode {args.mode!r} does not match Job write_mode {write_mode!r}"
            )
        if args.mode == "direct":
            if args.artifact:
                raise PipelineContractError("direct unit advance does not accept staged artifacts")
            mark_unit_integrated(
                job, str(source.get("source_id")), str(unit.get("unit_id")), relative_packet
            )
        else:
            mark_unit_staged(
                job, str(source.get("source_id")), str(unit.get("unit_id")), args.artifact
            )
        write_job(job_dir, job)
        result = summarize_job(job_dir, job)
        result["advanced"] = {
            "source_id": source.get("source_id"),
            "unit_id": unit.get("unit_id"),
            "status": unit.get("status"),
            "packet_path": relative_packet,
            "artifacts": list(args.artifact),
        }
        _emit_workflow_json(result, pretty=args.pretty, output=args.output)
    except (OSError, ValueError, json.JSONDecodeError, PipelineContractError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def _load_bound_inline_unit(
    job_dir: Path, source_id: str, unit_id: str
) -> tuple[dict, dict, dict]:
    from obsidian_wiki.ingest_pipeline import bind_inline_unit, load_job

    job = load_job(job_dir)
    source, unit = bind_inline_unit(job, source_id, unit_id)
    return job, source, unit


def cmd_text_ingest_inline_check(args: argparse.Namespace) -> int:
    from obsidian_wiki.ingest_pipeline import PipelineContractError

    try:
        job_dir = Path(args.job).expanduser().resolve()
        job, source, unit = _load_bound_inline_unit(
            job_dir, args.source_id, args.unit_id
        )
        result = {
            "status": "valid",
            "job_id": job.get("job_id"),
            "write_mode": job.get("write_mode", "direct"),
            "transport": "inline",
            "source_id": source.get("source_id"),
            "source_path": source.get("path"),
            "content_hash": source.get("content_hash"),
            "unit_id": unit.get("unit_id"),
            "range": {
                key: unit.get(key)
                for key in ("start_line", "end_line", "start_byte", "end_byte")
            },
        }
        _emit_workflow_json(result, pretty=args.pretty, output=args.output)
    except (OSError, ValueError, PipelineContractError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_text_ingest_inline_advance(args: argparse.Namespace) -> int:
    from obsidian_wiki.ingest_pipeline import (
        PipelineContractError,
        mark_unit_integrated,
        mark_unit_staged,
        summarize_job,
        write_job,
    )

    try:
        job_dir = Path(args.job).expanduser().resolve()
        job, source, unit = _load_bound_inline_unit(
            job_dir, args.source_id, args.unit_id
        )
        write_mode = job.get("write_mode", "direct")
        if args.mode != write_mode:
            raise PipelineContractError(
                f"advance mode {args.mode!r} does not match Job write_mode {write_mode!r}"
            )
        if args.mode == "direct":
            if args.artifact:
                raise PipelineContractError(
                    "direct inline advance does not accept staged artifacts"
                )
            mark_unit_integrated(
                job, str(source.get("source_id")), str(unit.get("unit_id"))
            )
        else:
            mark_unit_staged(
                job, str(source.get("source_id")), str(unit.get("unit_id")), args.artifact
            )
        write_job(job_dir, job)
        result = summarize_job(job_dir, job)
        result["advanced"] = {
            "source_id": source.get("source_id"),
            "unit_id": unit.get("unit_id"),
            "status": unit.get("status"),
            "transport": "inline",
            "artifacts": list(args.artifact),
        }
        _emit_workflow_json(result, pretty=args.pretty, output=args.output)
    except (OSError, ValueError, PipelineContractError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_wiki_context_resolve(args: argparse.Namespace) -> int:
    """Run the bundled context resolver from any working directory."""
    try:
        script = workflows_dir() / "scripts" / "resolve_wiki_context.py"
        if not script.is_file():
            raise FileNotFoundError(f"bundled context resolver is missing: {script}")
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    command = [
        sys.executable, str(script),
        "--input", args.input,
        "--source-cwd", args.source_cwd,
        "--requested-keys", args.requested_keys,
        "--optional-reads", args.optional_reads,
        "--setup-mode", args.setup_mode,
        "--output-dir", args.output_dir,
    ]
    if args.layouts_dir is not None:
        command.extend(["--layouts-dir", args.layouts_dir])
    return subprocess.run(command, check=False).returncode


def cmd_wiki_setup_contract_build(args: argparse.Namespace) -> int:
    """Build the setup contract from bundled workflow resources."""
    try:
        root = workflows_dir()
        script = root / "scripts" / "build_setup_contract.py"
        templates = root / "templates" / "wiki-setup"
        layouts = root / "layouts"
        if not script.is_file():
            raise FileNotFoundError(f"bundled setup contract builder is missing: {script}")
        if not templates.is_dir():
            raise FileNotFoundError(f"bundled setup templates are missing: {templates}")
        if not layouts.is_dir():
            raise FileNotFoundError(f"bundled workflow layouts are missing: {layouts}")
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    command = [
        sys.executable,
        str(script),
        args.phase,
        "--templates-dir",
        str(templates),
        "--layouts-dir",
        str(layouts),
        "--output-dir",
        args.output_dir,
    ]
    return subprocess.run(command, check=False).returncode


def cmd_wiki_layout_apply(args: argparse.Namespace) -> int:
    """Apply one bundled Knowledge Pack without depending on the caller's CWD."""
    try:
        root = workflows_dir()
        script = root / "scripts" / "apply_wiki_layout.py"
        layouts = root / "layouts"
        if not script.is_file():
            raise FileNotFoundError(f"bundled layout copier is missing: {script}")
        if not layouts.is_dir():
            raise FileNotFoundError(f"bundled workflow layouts are missing: {layouts}")
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    command = [
        sys.executable,
        str(script),
        "apply",
        "--layouts-dir",
        str(layouts),
        "--layout",
        args.layout,
        "--vault",
        args.vault,
        "--output-dir",
        args.output_dir,
    ]
    if args.refresh_layout_marker:
        command.append("--refresh-layout-marker")
    return subprocess.run(command, check=False).returncode


def cmd_wiki_route_resolve(args: argparse.Namespace) -> int:
    """Run the bundled page-route resolver from any working directory."""
    try:
        script = workflows_dir() / "scripts" / "resolve_wiki_route.py"
        if not script.is_file():
            raise FileNotFoundError(f"bundled page-route resolver is missing: {script}")
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    command = [
        sys.executable, str(script),
        "--routing", args.routing,
        "--page-type", args.page_type,
    ]
    for flag, value in (
        ("--slug", args.slug),
        ("--project", args.project),
        ("--date", args.date),
        ("--output", args.output),
    ):
        if value is not None:
            command.extend([flag, value])
    return subprocess.run(command, check=False).returncode


def cmd_ast_extract(args: argparse.Namespace) -> int:
    from pathlib import Path
    from obsidian_wiki.ast_extractor import extract
    path = Path(args.path).expanduser().resolve()
    try:
        result = extract(path)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.pretty:
        print(json.dumps(result, indent=2))
    else:
        print(json.dumps(result))
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    report = run_doctor(vault_override=args.vault, project_dir=args.project)
    if args.json:
        if args.pretty:
            print(json.dumps(report, indent=2))
        else:
            print(json.dumps(report))
    else:
        _print_doctor(report)
    statuses = {check["status"] for check in report["checks"]}
    if "fail" in statuses or (args.strict and "warn" in statuses):
        return 1
    return 0


def _print_lint(report: dict[str, object]) -> None:
    print(f"obsidian-wiki lint: {report['status']}")
    stats = report["stats"]
    print(f"pages: {stats['pages']}  links: {stats['link_count']}")
    for name, count in stats["findings"].items():
        print(f"{name}: {count}")


def _schema_csv(config: dict[str, str], key: str) -> list[str]:
    if key not in config:
        return []
    values = [item.strip() for item in config[key].split(",")]
    if any(not item for item in values):
        raise ValueError(f"invalid {key} value: entries must not be empty")
    return values


def _schema_cli_values(values: list[str] | None, flag: str) -> list[str]:
    normalised = [item.strip() for item in values or []]
    if any(not item for item in normalised):
        raise ValueError(f"invalid {flag} value: must not be empty")
    return normalised


def _schema_source_value(
    args: argparse.Namespace,
    config: dict[str, str],
) -> str | None:
    configured_value: str | None = None
    if "OBSIDIAN_SCHEMA_SOURCE" in config:
        configured_value = config["OBSIDIAN_SCHEMA_SOURCE"].strip()
        if not configured_value:
            raise ValueError("invalid OBSIDIAN_SCHEMA_SOURCE value: must not be empty")

    cli_value = getattr(args, "schema_source", None)
    if cli_value is not None:
        value = cli_value.strip()
        if not value:
            raise ValueError("invalid --schema-source value: must not be empty")
        return value
    return configured_value


def _read_config_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def _resolve_schema_command_context(
    vault_arg: str | None,
) -> tuple[Path, dict[str, str], str] | None:
    config: dict[str, str]
    config_source: str
    if vault_arg and vault_arg.startswith("@"):
        name = vault_arg[1:]
        if not name or re.fullmatch(r"[A-Za-z0-9_-]+", name) is None:
            print("error: named vault must use @ followed by letters, digits, _ or -", file=sys.stderr)
            return None
        path = GLOBAL_CONFIG_DIR / f"config.{name}"
        config = _read_config_file(path)
        config_source = str(path)
        resolved = config.get("OBSIDIAN_VAULT_PATH", "")
    elif vault_arg is not None:
        config = {}
        config_source = "explicit-vault"
        resolved = vault_arg
    else:
        current = Path.cwd().resolve()
        config = {}
        config_source = str(GLOBAL_CONFIG)
        while True:
            candidate = current / ".env"
            local = _read_config_file(candidate)
            if "OBSIDIAN_VAULT_PATH" in local:
                config = local
                config_source = str(candidate)
                break
            if current == HOME or current.parent == current:
                break
            current = current.parent
        if not config:
            config = _read_config_file(GLOBAL_CONFIG)
        resolved = config.get("OBSIDIAN_VAULT_PATH", "")
    if not resolved:
        print("error: vault not configured; pass a path, @name, or run obsidian-wiki setup", file=sys.stderr)
        return None
    vault = Path(resolved).expanduser().resolve()
    if not vault.is_dir():
        print(f"error: vault not found: {vault}", file=sys.stderr)
        return None
    return vault, config, config_source


def _schema_options(
    args: argparse.Namespace,
    config: dict[str, str],
    config_source: str,
    *,
    default_required_trust_fields: tuple[str, ...] | None = None,
) -> SchemaOptions:
    from obsidian_wiki.lint import (
        ALLOWED_RELATIONSHIP_TYPES,
        TRUST_REQUIRED_FRONTMATTER,
    )
    from obsidian_wiki.trust import (
        ALLOWED_LIFECYCLES,
        TRUST_REQUIRED_FIELD_ALLOWLIST,
    )

    cli_lifecycles = _schema_cli_values(
        getattr(args, "allow_lifecycle", None), "--allow-lifecycle"
    )
    cli_relationships = _schema_cli_values(
        getattr(args, "allow_relationship_type", None), "--allow-relationship-type"
    )
    raw_cli_required = getattr(args, "required_trust_field", None)
    cli_required = (
        _schema_cli_values(raw_cli_required, "--required-trust-field")
        if raw_cli_required is not None
        else None
    )
    configured_lifecycles = _schema_csv(config, "OBSIDIAN_ALLOWED_LIFECYCLES")
    configured_relationships = _schema_csv(config, "OBSIDIAN_ALLOWED_RELATIONSHIP_TYPES")
    configured_required = _schema_csv(config, "OBSIDIAN_REQUIRED_TRUST_FIELDS")
    unknown_required = sorted(
        set(configured_required).union(cli_required or ()) - TRUST_REQUIRED_FIELD_ALLOWLIST
    )
    if unknown_required:
        allowed = ", ".join(sorted(TRUST_REQUIRED_FIELD_ALLOWLIST))
        unknown = ", ".join(unknown_required)
        raise ValueError(
            "invalid OBSIDIAN_REQUIRED_TRUST_FIELDS value(s): "
            f"{unknown}; allowed values: {allowed}"
        )
    required = tuple(
        cli_required
        if cli_required is not None
        else configured_required
        or list(default_required_trust_fields or TRUST_REQUIRED_FRONTMATTER)
    )
    cli_overrides = bool(
        cli_lifecycles
        or cli_relationships
        or cli_required is not None
    )
    configured_overrides = bool(
        configured_lifecycles
        or configured_relationships
        or configured_required
    )
    source = _schema_source_value(args, config)
    if not source:
        if cli_overrides and configured_overrides:
            source = f"cli+config:{config_source}"
        elif cli_overrides:
            source = f"cli:{config_source}"
        elif configured_overrides:
            source = f"config:{config_source}"
        else:
            source = "framework-defaults"
    return {
        "allowed_lifecycles": ALLOWED_LIFECYCLES.union(configured_lifecycles, cli_lifecycles),
        "allowed_relationship_types": ALLOWED_RELATIONSHIP_TYPES.union(
            configured_relationships, cli_relationships
        ),
        "required_trust_fields": required,
        "schema_source": source,
    }


def cmd_lint(args: argparse.Namespace) -> int:
    from obsidian_wiki.lint import lint_vault

    context = _resolve_schema_command_context(args.vault)
    if context is None:
        return 1
    vault, config, config_source = context

    strict_trust = args.strict_trust or config.get("OBSIDIAN_TRUST_STRICT", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    try:
        schema = _schema_options(args, config, config_source)
        report = lint_vault(
            vault,
            require_trust_ledger=True,
            strict_trust=strict_trust,
            **schema,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        if args.pretty:
            print(json.dumps(report, indent=2))
        else:
            print(json.dumps(report))
    else:
        _print_lint(report)
    if report["status"] == "fail" or (args.strict and report["status"] == "warn"):
        return 1
    return 0


def _resolve_command_vault(vault_arg: str | None) -> Path | None:
    resolved = (
        vault_arg
        if vault_arg is not None
        else _read_config_value("OBSIDIAN_VAULT_PATH")
    )
    if not resolved:
        print("error: vault not configured; pass a path or run obsidian-wiki setup", file=sys.stderr)
        return None
    vault = Path(resolved).expanduser().resolve()
    if not vault.is_dir():
        print(f"error: vault not found: {vault}", file=sys.stderr)
        return None
    return vault


def _read_env_value(path: Path, key: str) -> tuple[bool, str]:
    if not path.is_file():
        return False, ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith(f"{key}="):
            return True, line.split("=", 1)[1].strip().strip('"')
    return False, ""


def _resolve_context_pack_vault(vault_arg: str | None) -> Path | None:
    if vault_arg is not None:
        return _resolve_command_vault(vault_arg)

    current = Path.cwd().resolve()
    home = HOME.resolve()
    while True:
        found, local_vault = _read_env_value(
            current / ".env",
            "OBSIDIAN_VAULT_PATH",
        )
        if found:
            if not local_vault:
                print(
                    "error: vault not configured; pass a path or run obsidian-wiki setup",
                    file=sys.stderr,
                )
                return None
            return _resolve_command_vault(local_vault)
        if current == home or current.parent == current:
            break
        current = current.parent
    return _resolve_command_vault(None)


def cmd_trust_record(args: argparse.Namespace) -> int:
    from obsidian_wiki.trust import (
        TRUST_LEDGER_RELATIVE_PATH,
        build_trust_ledger,
        check_trust_ledger,
        update_trust_ledger,
        write_trust_ledger,
    )

    context = _resolve_schema_command_context(args.vault)
    if context is None:
        return 1
    vault, config, config_source = context
    try:
        schema = _schema_options(
            args,
            config,
            config_source,
            default_required_trust_fields=("base_confidence", "lifecycle", "updated"),
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    path = vault / TRUST_LEDGER_RELATIVE_PATH
    try:
        if args.all:
            removed_not_applicable: list[str] = []
            if path.is_file():
                previous = check_trust_ledger(
                    vault,
                    path,
                    allowed_lifecycles=schema["allowed_lifecycles"],
                    required_trust_keys=schema["required_trust_fields"],
                    schema_source=schema["schema_source"],
                )
                removed_not_applicable = sorted(
                    item["page"]
                    for item in previous["stale"]
                    if item.get("reason")
                    == "confidence_not_applicable_but_ledger_entry_exists"
                )
            ledger = build_trust_ledger(
                vault,
                reviewed_at=args.reviewed_at,
                allowed_lifecycles=schema["allowed_lifecycles"],
                required_trust_keys=schema["required_trust_fields"],
            )
            ledger["removed_not_applicable"] = removed_not_applicable
            recorded_pages = len(ledger["pages"])
        else:
            ledger = update_trust_ledger(
                vault,
                path,
                reviewed_at=args.reviewed_at,
                page_paths=args.page,
                allowed_lifecycles=schema["allowed_lifecycles"],
                required_trust_keys=schema["required_trust_fields"],
            )
            requested = {
                Path(raw).as_posix().removeprefix("./") for raw in args.page
            }
            recorded_pages = len(requested.intersection(ledger["pages"]))
        write_trust_ledger(path, ledger, vault=vault)
    except (RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    result = {
        "status": "recorded",
        "ledger_path": str(path),
        "recorded_pages": recorded_pages,
        "not_applicable_pages": list(ledger.get("not_applicable", [])),
        "removed_not_applicable": list(ledger.get("removed_not_applicable", [])),
        "reviewed_at": args.reviewed_at,
        "method": ledger["method"],
        "schema": {
            "source": schema["schema_source"],
            "allowed_lifecycles": sorted(schema["allowed_lifecycles"]),
            "required_trust_fields": list(schema["required_trust_fields"]),
        },
    }
    if args.json:
        print(json.dumps(result, indent=2 if args.pretty else None))
    else:
        print(f"recorded {result['recorded_pages']} reviewed page(s) in {path}")
        print(
            "not applicable (excluded from trust review): "
            f"{len(result['not_applicable_pages'])} page(s)"
        )
        for page in result["not_applicable_pages"]:
            print(f"  - {page}")
        print(
            "obsolete ledger entries removed: "
            f"{len(result['removed_not_applicable'])} page(s)"
        )
        for page in result["removed_not_applicable"]:
            print(f"  - {page}")
        if result["removed_not_applicable"]:
            removed = ", ".join(result["removed_not_applicable"])
            print(
                "warning: removed obsolete trust ledger entries because "
                f"base_confidence is not applicable: {removed}",
                file=sys.stderr,
            )
    return 0


def cmd_trust_check(args: argparse.Namespace) -> int:
    from obsidian_wiki.trust import check_trust_ledger

    context = _resolve_schema_command_context(args.vault)
    if context is None:
        return 1
    vault, config, config_source = context
    try:
        schema = _schema_options(
            args,
            config,
            config_source,
            default_required_trust_fields=("base_confidence", "lifecycle", "updated"),
        )
        report = check_trust_ledger(
            vault,
            allowed_lifecycles=schema["allowed_lifecycles"],
            required_trust_keys=schema["required_trust_fields"],
            schema_source=schema["schema_source"],
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, indent=2 if args.pretty else None))
    else:
        print(f"obsidian-wiki trust-check: {report['status']}")
        for name, count in report["counts"].items():
            print(f"{name}: {count}")
    if report["status"] == "fail" or (args.strict and report["status"] == "warn"):
        return 1
    return 0


def _print_query(result: dict[str, object]) -> None:
    print(f"answer_type: {result['answer_type']}")
    candidates = result.get("candidates", [])
    if candidates:
        print("candidates:")
        for item in candidates:
            print(f"- {item['title']} ({item['page']}) score={item['score']}")
    path = result.get("path") or []
    if path:
        print("path:")
        print(" -> ".join(path))
    path_edges = result.get("path_edges") or []
    if path_edges:
        print("path_edges:")
        for edge in path_edges:
            reverse = " (reverse)" if edge.get("direction") == "reverse" else ""
            print(
                f"- {edge['source']} -[{edge['relation']}{reverse}]-> {edge['target']}"
            )
    should_read = result.get("should_read") or []
    if should_read:
        print("should_read:")
        for page in should_read:
            print(f"- {page}")


def cmd_query(args: argparse.Namespace) -> int:
    from obsidian_wiki.graphrag import query

    vault_arg = args.vault or _read_config_value("OBSIDIAN_VAULT_PATH")
    if not vault_arg:
        print("error: vault not configured; pass --vault or run obsidian-wiki setup", file=sys.stderr)
        return 1

    vault = Path(vault_arg).expanduser().resolve()
    if not vault.is_dir():
        print(f"error: vault not found: {vault}", file=sys.stderr)
        return 1

    result = query(vault, args.question, top_n=args.top, max_should_read=args.max_read)
    if args.json:
        if args.pretty:
            print(json.dumps(result, indent=2))
        else:
            print(json.dumps(result))
    else:
        _print_query(result)
    return 0


def cmd_context_pack(args: argparse.Namespace) -> int:
    from obsidian_wiki.context_pack import ContextError, build_context_pack, render_markdown

    vault = _resolve_context_pack_vault(args.vault)
    if vault is None:
        return 1
    try:
        pack = build_context_pack(
            vault,
            args.topic or "",
            budget=args.budget,
            recent=args.recent,
            public_only=args.public_only,
            metadata_only=args.metadata_only,
        )
    except ContextError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(pack, indent=2 if args.pretty else None))
    else:
        print(render_markdown(pack), end="")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    for name in list_skills():
        print(name)
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    bundled = list_skills()
    print(f"obsidian-wiki {__version__}")
    print(f"skills:    {skills_dir()}")
    boot = bootstrap_dir()
    print(f"bootstrap: {boot if boot else '(not found)'}")
    print(f"config:    {GLOBAL_CONFIG}{'' if GLOBAL_CONFIG.exists() else ' (not written yet)'}")
    if GLOBAL_CONFIG.exists():
        vp = _read_config_value("OBSIDIAN_VAULT_PATH")
        setup_ver = _read_config_value("OBSIDIAN_WIKI_VERSION")
        print(f"vault:     {vp or '(unset)'}")
        print(f"setup ran: {setup_ver or '(never)'}")
        if vp:
            from obsidian_wiki.sync import get_remote
            remote = get_remote(Path(vp).expanduser())
            print(f"sync:      {remote if remote else '(not configured — run: obsidian-wiki sync-setup <url>)'}")
    print(f"bundled skills: {len(bundled)}")
    print()
    print("Agent skill install status:")
    bundled_set = set(bundled)
    for rel, label, _subset in GLOBAL_AGENT_DIRS:
        agent_dir = HOME / rel
        if not agent_dir.is_dir():
            print(f"  {label}: not installed")
            continue
        installed = {p.name for p in agent_dir.iterdir() if p.is_dir()}
        wiki_installed = installed & bundled_set
        missing = bundled_set - installed
        status = "✅" if not missing else "⚠️ "
        print(f"  {status} {label}: {len(wiki_installed)}/{len(bundled_set)}", end="")
        if missing:
            print(f"  (run: obsidian-wiki setup)", end="")
        print()
    _check_stale()
    return 0


# ── Argument parsing ─────────────────────────────────────────────────────────
def _json_object(value: str) -> dict:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(f"invalid JSON object: {exc}") from exc
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("value must be a JSON object")
    return parsed


def _load_strategy_options(args: argparse.Namespace) -> dict:
    path = getattr(args, "strategy_options_file", None)
    if path is None:
        return getattr(args, "strategy_options", None) or {}
    value = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("chunk strategy options file must contain a JSON object")
    return value


def _add_chunk_strategy_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--min-budget", type=int,
        help="preferred minimum unit size before a heading split (default: half target)",
    )
    parser.add_argument(
        "--chunk-strategy", default="adaptive_sections",
        help="built-in or installed custom chunk strategy (default: adaptive_sections)",
    )
    options = parser.add_mutually_exclusive_group()
    options.add_argument(
        "--strategy-options", type=_json_object, metavar="JSON",
        help="JSON object passed to the selected chunk strategy",
    )
    options.add_argument(
        "--strategy-options-file", metavar="PATH",
        help="path to a JSON object passed to the selected chunk strategy",
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="obsidian-wiki",
        description="Install the LLM-Wiki agent skills into your AI coding agents.",
    )
    p.add_argument("-V", "--version", action="version", version=f"obsidian-wiki {__version__}")
    sub = p.add_subparsers(dest="command")

    sp = sub.add_parser("setup", help="install skills into your agents and write config (default)")
    _add_setup_args(sp)
    sp.set_defaults(func=cmd_setup)

    ssp = sub.add_parser(
        "sync-setup",
        help="configure GitHub sync for your vault (git init, .gitignore, remote)",
    )
    ssp.add_argument("remote", help="GitHub (or any git host) repo URL, e.g. https://github.com/you/my-wiki.git")
    ssp.add_argument("--vault", metavar="PATH", help="absolute path to your Obsidian vault")
    ssp.set_defaults(func=cmd_sync_setup)

    syp = sub.add_parser("sync", help="commit and push pending vault changes (git add -A, commit, push)")
    syp.add_argument("--vault", metavar="PATH", help="absolute path to your Obsidian vault")
    syp.set_defaults(func=cmd_sync)

    lp = sub.add_parser("list", help="list bundled skills")
    lp.set_defaults(func=cmd_list)

    ip = sub.add_parser("info", help="show install paths, version, and config")
    ip.set_defaults(func=cmd_info)

    gq = sub.add_parser(
        "graph-query",
        help="answer a question from the vault's wikilink index without reading page bodies",
    )
    gq.add_argument("vault", help="path to the Obsidian vault")
    gq.add_argument("question", help="question to answer")
    gq.add_argument("--top", type=int, default=8, help="number of candidate pages to rank (default: 8)")
    gq.add_argument("--max-read", type=int, default=3, help="max pages to return in should_read (default: 3)")
    gq.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    gq.set_defaults(func=cmd_graph_query)

    bp = sub.add_parser(
        "batch-plan",
        help="split a source directory into parallel-ingest batches, skipping unchanged files",
    )
    bp.add_argument("vault", help="path to the Obsidian vault")
    bp.add_argument("source_dir", help="directory of source documents to ingest")
    bp.add_argument("--max-mb", type=float, default=2.0, help="max MB per batch (default: 2)")
    bp.add_argument("--max-files", type=int, default=20, help="max files per batch (default: 20)")
    bp.add_argument("--no-cache", action="store_true", help="disable manifest-based skip of unchanged files")
    bp.add_argument("--include-code", action="store_true", help="include code files (default: excluded; use ast-extract instead)")
    bp.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    bp.set_defaults(func=cmd_batch_plan)

    ga = sub.add_parser(
        "graph-analyse",
        help="analyse the vault's wikilink graph: god nodes, communities, surprising connections",
    )
    ga.add_argument("vault", help="path to the Obsidian vault")
    ga.add_argument("--top", type=int, default=20, help="number of top results to return (default: 20)")
    ga.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    ga.set_defaults(func=cmd_graph_analyse)

    gx = sub.add_parser(
        "graph",
        help="networkx graph queries: paths, neighbors, centrality, communities, stats",
    )
    gx.add_argument("vault", help="path to the Obsidian vault")
    gx.add_argument("--no-cache", action="store_true", help="force rebuild graph (skip .obsidian/graph.json cache)")
    gx.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    gx_sub = gx.add_subparsers(dest="graph_cmd")
    gx_p = gx_sub.add_parser("paths", help="find shortest paths between two pages")
    gx_p.add_argument("--from", dest="source", required=True, metavar="SLUG", help="source page slug")
    gx_p.add_argument("--to", dest="target", required=True, metavar="SLUG", help="target page slug")
    gx_p.add_argument("--max-len", type=int, default=4, help="max path length (default: 4)")
    gx_p.add_argument("--relation", help="filter edges by relation type")
    gx_n = gx_sub.add_parser("neighbors", help="ego-network around a page")
    gx_n.add_argument("slug", help="page slug")
    gx_n.add_argument("--radius", type=int, default=1, help="neighborhood radius (default: 1)")
    gx_c = gx_sub.add_parser("centrality", help="rank pages by centrality metric")
    gx_c.add_argument("--method", default="pagerank", choices=["pagerank", "betweenness", "degree", "in_degree", "out_degree"])
    gx_c.add_argument("--top", type=int, default=10, help="number of top results (default: 10)")
    gx_c.add_argument("--tag", help="filter to pages with this tag")
    gx_t = gx_sub.add_parser("tag-subgraph", help="extract subgraph of pages with a given tag")
    gx_t.add_argument("--tag", required=True, help="tag to filter by")
    gx_t.add_argument("--min-degree", type=int, default=1, help="minimum node degree (default: 1)")
    gx_t.add_argument("--output", help="save subgraph as node-link JSON file")
    gx_sub.add_parser("communities", help="detect communities (Louvain or greedy modularity)")
    gx_sub.add_parser("stats", help="graph statistics (nodes, edges, density, components)")
    gx.set_defaults(func=cmd_graph)

    sb = sub.add_parser(
        "sessions-build",
        help="build a topic graph over your agent session history (writes a sidecar, not the vault)",
    )
    sb.add_argument("--claude-dir", default=DEFAULT_CLAUDE_DIR,
                    help=f"agent session cache to read (default: {DEFAULT_CLAUDE_DIR})")
    sb.add_argument("--out", default=None,
                    help=f"output directory (default: $WIKI_SESSION_BRAIN_DIR or {DEFAULT_BRAIN_DIR})")
    sb.add_argument("--k", type=int, default=8, help="neighbours per session (default: 8)")
    sb.add_argument("--min-sim", type=float, default=0.08,
                    help="minimum cosine similarity for an edge (default: 0.08)")
    sb.add_argument("--mutual", action="store_true",
                    help="keep only mutual kNN edges — tighter, smaller clusters")
    sb.add_argument("--half-life", type=float, default=90.0,
                    help="recency half-life in days (default: 90)")
    sb.add_argument("--since", help="only read sessions modified on or after this ISO date")
    sb.add_argument("--skip",
                    help="comma-separated substrings of project dirs to skip (or $WIKI_SKIP_PROJECTS). "
                         "Cache dir names begin with '-', which argparse reads as a flag — pass the "
                         "bare name ('game') or use --skip=-w-game")
    sb.add_argument("--full", action="store_true", help="ignore caches and re-read every session")
    sb.add_argument("--no-html", action="store_true", help="skip writing graph.html")
    sb.add_argument("--bookmarks", help="path to bookmarks.json (default: ~/.bookmark-agent/bookmarks.json)")
    sb.add_argument("--json", action="store_true", help="emit JSON instead of a human summary")
    sb.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    sb.add_argument("-v", "--verbose", action="store_true", help="report progress to stderr")
    sb.set_defaults(func=cmd_sessions_build)

    sq = sub.add_parser(
        "sessions-query",
        help="find the sessions most relevant to a topic, ranked by similarity and recency",
    )
    sq.add_argument("question", help="topic or question to search for")
    sq.add_argument("--out", default=None, help="session-brain directory")
    sq.add_argument("--top", type=int, default=10, help="candidates to return (default: 10)")
    sq.add_argument("--max-load", type=int, default=3,
                    help="max sessions to recommend loading (default: 3)")
    sq.add_argument("--half-life", type=float, default=None,
                    help="override the recency half-life used at build time")
    sq.add_argument("--project", help="restrict to one project")
    sq.add_argument("--cluster", type=int, help="restrict to one topic cluster id")
    sq.add_argument("--since", help="only consider sessions ending on or after this ISO date")
    sq.add_argument("--min-score", type=float, default=0.05, help="drop candidates below this score")
    sq.add_argument("--json", action="store_true", help="emit JSON instead of a human summary")
    sq.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    sq.set_defaults(func=cmd_sessions_query)

    ssh = sub.add_parser(
        "sessions-show",
        help="show one session's graph node and its nearest neighbours",
    )
    ssh.add_argument("session_id", help="session id (full or unique prefix)")
    ssh.add_argument("--out", default=None, help="session-brain directory")
    ssh.add_argument("--neighbors", type=int, default=8, help="neighbours to include (default: 8)")
    ssh.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    ssh.set_defaults(func=cmd_sessions_show)

    scl = sub.add_parser("sessions-clusters", help="list the discovered topic clusters")
    scl.add_argument("--out", default=None, help="session-brain directory")
    scl.add_argument("--unnamed", action="store_true", help="only clusters that still need a name")
    scl.add_argument("--top", type=int, default=20, help="max clusters to list (default: 20)")
    scl.add_argument("--json", action="store_true", help="emit JSON instead of a human summary")
    scl.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    scl.set_defaults(func=cmd_sessions_clusters)

    snm = sub.add_parser("sessions-name", help="assign names to topic clusters (durable across rebuilds)")
    snm.add_argument("--out", default=None, help="session-brain directory")
    snm.add_argument("--from", dest="from_file", required=True, metavar="FILE",
                     help='JSON array of {"id": N, "name": "...", "summary": "..."}; use - for stdin')
    snm.set_defaults(func=cmd_sessions_name)

    cc = sub.add_parser(
        "cache-check",
        help="check which sources are new/modified/unchanged vs. .manifest.json",
    )
    cc.add_argument("vault", help="path to the Obsidian vault")
    cc.add_argument("sources", nargs="+", help="source file or directory paths to check")
    cc.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    cc.set_defaults(func=cmd_cache_check)

    cu = sub.add_parser(
        "cache-update",
        help="record a source's current SHA-256 hash in .manifest.json after ingestion",
    )
    cu.add_argument("vault", help="path to the Obsidian vault")
    cu.add_argument("source", help="source file or directory that was just ingested")
    cu.add_argument("--pages", nargs="*", metavar="PAGE", help="vault-relative paths of pages produced")
    cu.set_defaults(func=cmd_cache_update)

    ch = sub.add_parser(
        "cache-hash",
        help="compute the SHA-256 hash of a file or directory (no manifest I/O)",
    )
    ch.add_argument("path", help="file or directory to hash")
    ch.set_defaults(func=cmd_cache_hash)

    tcp = sub.add_parser(
        "text-chunk-plan",
        help="plan deterministic UTF-8 byte ranges for a supported text source",
    )
    tcp.add_argument("source", help=".md, .markdown, .mdx, .txt, or .rst source")
    tcp.add_argument("--target-budget", type=int, default=48_000,
                     help="preferred UTF-8 byte size per unit (default: 48000)")
    tcp.add_argument("--hard-budget", type=int, default=64_000,
                     help="absolute UTF-8 byte cap per unit (default: 64000)")
    _add_chunk_strategy_args(tcp)
    tcp.add_argument("--allow-unsafe-hard-budget", action="store_true",
                     help="explicitly allow a hard cap above the documented 64000-byte maximum")
    tcp.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    tcp.set_defaults(func=cmd_text_chunk_plan)

    tcs = sub.add_parser(
        "text-chunk-strategies",
        help="list built-in, registered, and installed text chunk strategies",
    )
    tcs.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    tcs.set_defaults(func=cmd_text_chunk_strategies)

    tcr = sub.add_parser(
        "text-chunk-read",
        help="verify a source hash and write exactly one planned UTF-8 byte range",
    )
    tcr.add_argument("source", help="planned text source")
    tcr.add_argument("--start-byte", type=int, required=True, help="zero-based inclusive byte offset")
    tcr.add_argument("--end-byte", type=int, required=True, help="exclusive byte offset")
    tcr.add_argument("--expect-hash", required=True, metavar="sha256:HEX",
                     help="source hash recorded by text-chunk-plan")
    tcr.add_argument("--allow-unsafe-hard-budget", action="store_true",
                     help="explicitly allow reading a planned range above 64000 bytes")
    tcr.set_defaults(func=cmd_text_chunk_read)

    tip = sub.add_parser(
        "text-ingest-plan",
        help="discover text sources and atomically create or resume a deterministic ingest Job",
    )
    tip.add_argument("source", help="supported text file or directory to ingest")
    tip.add_argument("--vault", required=True, help="resolved Obsidian vault path")
    tip.add_argument("--write-mode", choices=("direct", "staged"), default="direct")
    tip.add_argument("--target-budget", type=int, default=48_000)
    tip.add_argument("--hard-budget", type=int, default=64_000)
    tip.add_argument(
        "--direct-extract-max-bytes", type=int,
        help=(
            "inline-extract complete sources at or below this size; 0 disables "
            "(default: min(16000, hard budget))"
        ),
    )
    _add_chunk_strategy_args(tip)
    tip.add_argument("--output", help="atomically write the JSON summary to this artifact path")
    tip.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    tip.set_defaults(func=cmd_text_ingest_plan)

    tis = sub.add_parser(
        "text-ingest-status",
        help="summarize one ingest Job and calculate its next unit and live completion state",
    )
    tis.add_argument("job", help="ingest Job directory")
    tis.add_argument("--output", help="atomically write the JSON summary to this artifact path")
    tis.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    tis.set_defaults(func=cmd_text_ingest_status)

    tir = sub.add_parser(
        "text-ingest-report",
        help="generate deterministic JSON and Markdown completion reports for one ingest Job",
    )
    tir.add_argument("job", help="ingest Job directory")
    tir.add_argument("--output", required=True, help="atomically write the JSON completion report")
    tir.add_argument(
        "--markdown-output", required=True,
        help="atomically write the Markdown completion report",
    )
    tir.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    tir.set_defaults(func=cmd_text_ingest_report)

    tipc = sub.add_parser(
        "text-ingest-packet-check",
        help="validate one Packet against its Job and planned source/unit/path binding",
    )
    tipc.add_argument("job", help="ingest Job directory")
    tipc.add_argument("packet", help="planned Packet path, relative to the Job or absolute")
    tipc.add_argument("--output", help="atomically write the JSON result to this artifact path")
    tipc.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    tipc.set_defaults(func=cmd_text_ingest_packet_check)

    tiua = sub.add_parser(
        "text-ingest-unit-advance",
        help="atomically advance one validated Packet unit after page validation succeeds",
    )
    tiua.add_argument("job", help="ingest Job directory")
    tiua.add_argument("packet", help="planned Packet path, relative to the Job or absolute")
    tiua.add_argument("--mode", choices=("direct", "staged"), required=True)
    tiua.add_argument(
        "--artifact", action="append", default=[],
        help="staged review artifact path; repeat for multiple artifacts",
    )
    tiua.add_argument("--output", help="atomically write the JSON result to this artifact path")
    tiua.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    tiua.set_defaults(func=cmd_text_ingest_unit_advance)

    tiic = sub.add_parser(
        "text-ingest-inline-check",
        help="validate one full-source inline unit without creating a Packet",
    )
    tiic.add_argument("job", help="ingest Job directory")
    tiic.add_argument("--source-id", required=True, help="planned inline source identifier")
    tiic.add_argument("--unit-id", required=True, help="planned logical unit identifier")
    tiic.add_argument("--output", help="atomically write the JSON result to this artifact path")
    tiic.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    tiic.set_defaults(func=cmd_text_ingest_inline_check)

    tiia = sub.add_parser(
        "text-ingest-inline-advance",
        help="atomically advance one validated inline unit after page validation succeeds",
    )
    tiia.add_argument("job", help="ingest Job directory")
    tiia.add_argument("--source-id", required=True, help="planned inline source identifier")
    tiia.add_argument("--unit-id", required=True, help="planned logical unit identifier")
    tiia.add_argument("--mode", choices=("direct", "staged"), required=True)
    tiia.add_argument(
        "--artifact", action="append", default=[],
        help="staged review artifact path; repeat for multiple artifacts",
    )
    tiia.add_argument("--output", help="atomically write the JSON result to this artifact path")
    tiia.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    tiia.set_defaults(func=cmd_text_ingest_inline_advance)

    wcr = sub.add_parser(
        "wiki-context-resolve",
        help="run the bundled workflow context resolver independently of the current directory",
    )
    wcr.add_argument("--input", required=True, help="approved vault-input.json path")
    wcr.add_argument("--source-cwd", required=True, help="source project directory used for config lookup")
    wcr.add_argument("--requested-keys", default="", help="comma-separated configuration keys")
    wcr.add_argument("--optional-reads", default="", help="comma-separated optional metadata reads")
    wcr.add_argument("--setup-mode", choices=("true", "false"), default="false")
    wcr.add_argument("--layouts-dir", default=None, help="override the bundled layouts directory")
    wcr.add_argument("--output-dir", required=True, help="artifact output directory")
    wcr.set_defaults(func=cmd_wiki_context_resolve)

    wsc = sub.add_parser(
        "wiki-setup-contract-build",
        help="build setup contracts from bundled workflow templates and Knowledge Packs",
    )
    wsc.add_argument("phase", choices=("core", "finalize"))
    wsc.add_argument("--output-dir", required=True, help="artifact output directory")
    wsc.set_defaults(func=cmd_wiki_setup_contract_build)

    wla = sub.add_parser(
        "wiki-layout-apply",
        help="apply a bundled Knowledge Pack independently of the current directory",
    )
    wla.add_argument("--layout", required=True, help="bundled Knowledge Pack name")
    wla.add_argument("--vault", required=True, help="absolute target vault path")
    wla.add_argument("--output-dir", required=True, help="artifact output directory")
    wla.add_argument(
        "--refresh-layout-marker",
        action="store_true",
        help="refresh hashes for the same layout name; cannot switch layouts",
    )
    wla.set_defaults(func=cmd_wiki_layout_apply)

    wrr = sub.add_parser(
        "wiki-route-resolve",
        help="resolve one declared page type with the bundled deterministic router",
    )
    wrr.add_argument("--routing", required=True, help="routing.json or frozen page contract")
    wrr.add_argument("--page-type", required=True)
    wrr.add_argument("--slug")
    wrr.add_argument("--project")
    wrr.add_argument("--date")
    wrr.add_argument("--output")
    wrr.set_defaults(func=cmd_wiki_route_resolve)

    ap = sub.add_parser(
        "ast-extract",
        help="extract code structure (classes, functions, imports) from a file or directory — no LLM, no API calls",
    )
    ap.add_argument("path", help="file or directory to extract from")
    ap.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    ap.set_defaults(func=cmd_ast_extract)

    dr = sub.add_parser(
        "doctor",
        help="check config, vault shape, bootstrap assets, and installed skills",
    )
    dr.add_argument("--vault", help="override OBSIDIAN_VAULT_PATH for this health check")
    dr.add_argument("--project", help="also check project-local bootstrap files in this directory")
    dr.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    dr.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    dr.add_argument("--strict", action="store_true", help="exit non-zero on warnings as well as failures")
    dr.set_defaults(func=cmd_doctor)

    lt = sub.add_parser(
        "lint",
        help="lint a vault for missing frontmatter, broken links, duplicates, and orphans",
    )
    lt.add_argument("vault", nargs="?", help="vault path or @name (defaults via CWD .env, then global config)")
    lt.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    lt.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    lt.add_argument("--strict", action="store_true", help="exit non-zero on warnings as well as failures")
    lt.add_argument(
        "--strict-trust",
        action="store_true",
        help=(
            "fail lint on missing trust fields, ledger errors, stale reviews, and "
            "score mismatches (default: legacy mode, these are warnings only). "
            "Also settable per-vault via OBSIDIAN_TRUST_STRICT=1 in the config."
        ),
    )
    lt.add_argument(
        "--allow-lifecycle",
        action="append",
        metavar="VALUE",
        help="extend the framework lifecycle allowlist (repeatable)",
    )
    lt.add_argument(
        "--allow-relationship-type",
        action="append",
        metavar="VALUE",
        help="extend the framework relationship-type allowlist (repeatable)",
    )
    lt.add_argument(
        "--required-trust-field",
        action="append",
        choices=("base_confidence", "lifecycle", "lifecycle_changed", "updated"),
        help="replace default trust-field requiredness (repeatable)",
    )
    lt.add_argument(
        "--schema-source",
        help="authority locator recorded in the lint report (for example, vault/AGENTS.md)",
    )
    lt.set_defaults(func=cmd_lint)

    vl = sub.add_parser(
        "validate",
        help="validate frontmatter completeness for pages after an ingest",
    )
    vl.add_argument("vault", nargs="?", help="vault path or @name (defaults via CWD .env, then global config)")
    pages_src = vl.add_mutually_exclusive_group(required=True)
    pages_src.add_argument(
        "--pages", nargs="+", metavar="PAGE",
        help="vault-relative page paths to validate (e.g. concepts/foo.md)",
    )
    pages_src.add_argument(
        "--from-stdin", action="store_true",
        help="read page paths from stdin (JSON array or newline-separated)",
    )
    vl.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    vl.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    vl.set_defaults(func=cmd_validate)

    vf = sub.add_parser(
        "verify",
        help="audit source-to-page completeness against the manifest (detect ingest omissions)",
    )
    vf.add_argument("vault", nargs="?", help="vault path or @name (defaults via CWD .env, then global config)")
    vf_src = vf.add_mutually_exclusive_group()
    vf_src.add_argument(
        "--sources", nargs="+", metavar="SOURCE",
        help="source paths from this ingest batch to verify",
    )
    vf_src.add_argument(
        "--from-stdin", action="store_true",
        help="read source paths from stdin (JSON array or newline-separated)",
    )
    vf.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    vf.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    vf.set_defaults(func=cmd_verify)

    vs = sub.add_parser(
        "verify-sections",
        help="emit a section-coverage checklist from a PageIndex _structure.json",
    )
    vs.add_argument("structure", help="path to a PageIndex _structure.json file")
    vs.add_argument("--pages", nargs="*", metavar="PAGE", help="produced page paths (vault-relative) for a coverage hint")
    vs.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    vs.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    vs.set_defaults(func=cmd_verify_sections)

    tr = sub.add_parser(
        "trust-record",
        help="record explicitly approved manual confidence reviews in the vault trust ledger",
    )
    tr.add_argument("vault", nargs="?", help="vault path or @name (defaults via CWD .env, then global config)")
    selection = tr.add_mutually_exclusive_group(required=True)
    selection.add_argument("--all", action="store_true", help="record every current trust-schema page")
    selection.add_argument(
        "--page",
        action="append",
        metavar="VAULT_RELATIVE_PATH",
        help="record only this explicitly reviewed page (repeatable)",
    )
    tr.add_argument("--reviewed-at", required=True, help="ISO timestamp for the approved review")
    tr.add_argument(
        "--approved",
        action="store_true",
        required=True,
        help="confirm a human approved every confidence value being recorded",
    )
    tr.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    tr.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    tr.add_argument(
        "--allow-lifecycle",
        action="append",
        metavar="VALUE",
        help="extend the resolved vault lifecycle allowlist (repeatable)",
    )
    tr.add_argument(
        "--required-trust-field",
        action="append",
        choices=("base_confidence", "lifecycle", "lifecycle_changed", "updated"),
        help="replace resolved vault trust-field requiredness (repeatable)",
    )
    tr.add_argument("--schema-source", help="authority locator recorded in the result")
    tr.set_defaults(func=cmd_trust_record)

    tc = sub.add_parser(
        "trust-check",
        help="validate confidence values and material fingerprints against the manual trust ledger",
    )
    tc.add_argument("vault", nargs="?", help="vault path or @name (defaults via CWD .env, then global config)")
    tc.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    tc.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    tc.add_argument("--strict", action="store_true", help="exit non-zero on warnings as well as failures")
    tc.add_argument(
        "--allow-lifecycle",
        action="append",
        metavar="VALUE",
        help="extend the framework lifecycle allowlist (repeatable)",
    )
    tc.add_argument(
        "--required-trust-field",
        action="append",
        choices=("base_confidence", "lifecycle", "lifecycle_changed", "updated"),
        help="replace default trust-field requiredness (repeatable)",
    )
    tc.add_argument(
        "--schema-source",
        help="authority locator recorded in the trust report",
    )
    tc.set_defaults(func=cmd_trust_check)

    qq = sub.add_parser(
        "query",
        help="query the configured vault without passing the raw path each time",
    )
    qq.add_argument("question", help="question to ask against the vault index")
    qq.add_argument("--vault", help="override OBSIDIAN_VAULT_PATH for this query")
    qq.add_argument("--top", type=int, default=8, help="number of candidate pages to rank (default: 8)")
    qq.add_argument("--max-read", type=int, default=3, help="max pages to return in should_read (default: 3)")
    qq.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    qq.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    qq.set_defaults(func=cmd_query)

    cp = sub.add_parser(
        "context-pack",
        aliases=["context"],
        help="compile a token-bounded vault slice for a downstream agent",
    )
    cp.add_argument("topic", nargs="?", help="topic to retrieve; omit only with --recent")
    cp.add_argument("--vault", help="override OBSIDIAN_VAULT_PATH")
    cp.add_argument(
        "--budget",
        type=int,
        default=8_000,
        help="maximum estimated output tokens, 256..100000 (default: 8000)",
    )
    cp.add_argument("--recent", action="store_true", help="select recently updated notes")
    cp.add_argument(
        "--public-only",
        action="store_true",
        help="exclude visibility/internal and visibility/pii notes",
    )
    cp.add_argument(
        "--metadata-only",
        action="store_true",
        help="emit titles, provenance, and summaries without body excerpts",
    )
    cp.add_argument("--json", action="store_true", help="emit structured JSON")
    cp.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    cp.set_defaults(func=cmd_context_pack)

    return p


def cmd_validate(args: argparse.Namespace) -> int:
    """Validate frontmatter completeness for recently written wiki pages."""
    context = _resolve_schema_command_context(args.vault)
    if context is None:
        return 1
    vault, _config, _config_source = context

    if args.pages:
        page_paths = args.pages
    elif args.from_stdin:
        raw = sys.stdin.read()
        try:
            page_paths = json.loads(raw)
        except json.JSONDecodeError:
            page_paths = [line.strip() for line in raw.splitlines() if line.strip()]
    else:
        print("error: pass --pages or --from-stdin", file=sys.stderr)
        return 1

    report = validate_vault_pages(vault, page_paths)
    if args.json:
        if args.pretty:
            print(json.dumps(report, indent=2))
        else:
            print(json.dumps(report))
    else:
        print_report(report)

    if report["status"] == "fail":
        return 1
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """Audit source→page completeness against the manifest."""
    context = _resolve_schema_command_context(args.vault)
    if context is None:
        return 1
    vault, _config, _config_source = context

    source_paths = args.sources if args.sources else None
    if source_paths is None and args.from_stdin:
        raw = sys.stdin.read()
        try:
            source_paths = json.loads(raw)
        except json.JSONDecodeError:
            source_paths = [line.strip() for line in raw.splitlines() if line.strip()]

    report = verify_completeness(vault, source_paths=source_paths)
    if args.json:
        if args.pretty:
            print(json.dumps(report, indent=2))
        else:
            print(json.dumps(report))
    else:
        print_verify_report(report)

    if report["status"] == "fail":
        return 1
    return 0


def cmd_verify_sections(args: argparse.Namespace) -> int:
    """Emit a section-coverage checklist from a PageIndex structure JSON."""
    report = verify_sections(args.structure, produced_pages=args.pages)
    if args.json:
        if args.pretty:
            print(json.dumps(report, indent=2))
        else:
            print(json.dumps(report))
    else:
        print_sections_report(report)

    if report.get("status") == "fail":
        return 1
    return 0


def _add_setup_args(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("--vault", metavar="PATH", help="absolute path to your Obsidian vault")
    sp.add_argument(
        "--project",
        nargs="?",
        const="",
        default=None,
        metavar="DIR",
        help="also install project-local skills + bootstrap files into DIR "
        "(defaults to the current directory if no DIR given)",
    )
    sp.add_argument(
        "--project-only",
        action="store_true",
        help="skip the global agent install (use with --project)",
    )
    sp.add_argument(
        "--copy",
        action="store_true",
        help="copy skill files instead of symlinking (the default on Windows)",
    )
    sp.add_argument(
        "--layout",
        metavar="NAME",
        help="use a Knowledge Pack (Profile + Layout; run with --list-layouts to see options)",
    )
    sp.add_argument(
        "--list-layouts",
        action="store_true",
        help="list available Knowledge Packs and exit",
    )
    sp.add_argument(
        "--remote",
        metavar="URL",
        help="GitHub (or any git host) repo URL for vault sync — skips the interactive "
        "prompt and configures it non-interactively (see also: obsidian-wiki sync-setup)",
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    argv = list(sys.argv[1:] if argv is None else argv)
    # No subcommand → default to `setup` (the common case).
    if not argv or (argv[0].startswith("-") and argv[0] not in ("-h", "--help", "-V", "--version")):
        argv = ["setup", *argv]
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    # Warn about stale installs on every command except `setup` (which fixes it)
    # and `info` (which calls _check_stale itself with richer output).
    if getattr(args, "command", None) not in ("setup", "info", "doctor", None):
        _check_stale()
    try:
        return args.func(args)
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
