#!/usr/bin/env python3
"""
obsidian-wiki setup — configures skill discovery for all supported AI agents.

Usage: python3 setup.py

What it does:
  1. Creates .env from .env.example (if not present)
  2. Writes ~/.obsidian-wiki/config so skills work from any project
  3. Symlinks .skills/* into each agent's expected skills directory
  4. Bootstraps AGENTS.md aliases (CLAUDE.md, GEMINI.md, .hermes.md)
  5. Prints a summary of what's ready
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILLS_DIR = SCRIPT_DIR / ".skills"
_IS_WINDOWS = os.name == "nt"
GLOBAL_CONFIG_DIR = (Path(os.environ.get("LOCALAPPDATA", "")) if _IS_WINDOWS else Path.home()) / ".obsidian-wiki"
GLOBAL_CONFIG = GLOBAL_CONFIG_DIR / "config"


def install_skills(target_dir, label, mode="absolute", subset=None):
    """Symlink skills into target_dir.

    Args:
        target_dir: Destination directory for skill symlinks.
        label: Human-readable label for progress output.
        mode: "relative" or "absolute" — relative emits ../-prefixed targets.
        subset: Optional iterable of skill names to install (default: all).
    """
    if subset is None:
        subset = []
    subset = list(subset)

    if mode not in ("relative", "absolute"):
        print(f"install_skills: bad mode '{mode}' (want relative|absolute)", file=sys.stderr)
        sys.exit(1)

    target = Path(target_dir)
    rel_prefix = ""

    if mode == "relative":
        try:
            rel = target.relative_to(SCRIPT_DIR)
        except ValueError:
            print(
                f"install_skills: relative mode requires target under SCRIPT_DIR ({target_dir})",
                file=sys.stderr,
            )
            sys.exit(1)
        depth = len(rel.parts)
        rel_prefix = "../" * depth

    target.mkdir(parents=True, exist_ok=True)

    for skill_path in sorted(SKILLS_DIR.iterdir()):
        if not skill_path.is_dir():
            continue
        skill_name = skill_path.name

        if subset and skill_name not in subset:
            continue

        link_path = target / skill_name

        if mode == "relative":
            link_target = f"{rel_prefix}.skills/{skill_name}"
        else:
            link_target = str(skill_path)

        # Remove existing link, regular file, or directory
        if link_path.is_symlink():
            link_path.unlink()
        elif link_path.is_dir():
            if (link_path / "SKILL.md").exists():
                shutil.rmtree(link_path)
            else:
                print(f"⚠️   {link_path} is not a managed skill, skipping")
                continue
        elif link_path.is_file():
            link_path.unlink()

        if _IS_WINDOWS:
            # Windows: copy instead of symlink (requires admin/Developer Mode)
            shutil.copytree(skill_path, link_path)
        else:
            link_path.symlink_to(link_target)

        # Sanity check: every skill ships a SKILL.md
        if not (link_path / "SKILL.md").exists():
            print(f"install_skills: broken install {link_path} -> {link_target}", file=sys.stderr)
            sys.exit(1)

    print(f"✅  Installed skills → {label}")


def run_owiki(*args):
    """Run obsidian-wiki CLI from this checkout via PYTHONPATH."""
    if shutil.which("python3"):
        result = subprocess.run(
            [sys.executable, "-m", "obsidian_wiki.cli", *args],
            cwd=str(SCRIPT_DIR),
            env={**os.environ, "PYTHONPATH": str(SCRIPT_DIR)},
        )
        return result.returncode == 0
    elif shutil.which("obsidian-wiki"):
        result = subprocess.run(["obsidian-wiki", *args])
        return result.returncode == 0
    else:
        print(
            "⚠️  Skipping GitHub sync setup — neither 'python3' nor 'obsidian-wiki' found on PATH.",
            file=sys.stderr,
        )
        return False


def main():
    print()
    print("╔══════════════════════════════════════════════════╗")
    print("║         obsidian-wiki — Agent Setup              ║")
    print("╚══════════════════════════════════════════════════╝")
    print()

    # ── Step 1: .env ──────────────────────────────────────────────
    env_file = SCRIPT_DIR / ".env"
    env_example = SCRIPT_DIR / ".env.example"
    if not env_file.exists():
        shutil.copy(env_example, env_file)
        print("✅  Created .env from .env.example")
        print("    → Edit .env and set OBSIDIAN_VAULT_PATH before using skills.")
    else:
        print("✅  .env already exists")

    # ── Step 1b: ~/.obsidian-wiki/config ─────────────────────────
    GLOBAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    vault_path = ""
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("OBSIDIAN_VAULT_PATH="):
                vault_path = line.split("=", 1)[1].strip().strip('"')
                break

    if not vault_path or vault_path == "/path/to/your/vault":
        print()
        try:
            vault_path = input("  Where is your Obsidian vault? (absolute path): ").strip()
        except (EOFError, KeyboardInterrupt):
            vault_path = ""
        if vault_path:
            escaped = vault_path.replace("\\", "\\\\")
            content = env_file.read_text()
            import re
            content = re.sub(
                r"^OBSIDIAN_VAULT_PATH=.*",
                f'OBSIDIAN_VAULT_PATH="{escaped}"',
                content,
                flags=re.MULTILINE,
            )
            env_file.write_text(content)

    GLOBAL_CONFIG.write_text(
        f'OBSIDIAN_VAULT_PATH="{vault_path}"\n'
        f'OBSIDIAN_WIKI_REPO="{SCRIPT_DIR}"\n'
    )
    print("✅  Global config written to ~/.obsidian-wiki/config")

    # ── Step 1c: Bootstrap AGENTS.md aliases ──────────────────────
    hermes_bootstrap = SCRIPT_DIR / ".hermes.md"
    if hermes_bootstrap.is_symlink():
        hermes_bootstrap.unlink()
    elif hermes_bootstrap.is_file():
        hermes_bootstrap.unlink()
    if _IS_WINDOWS:
        shutil.copyfile(SCRIPT_DIR / "AGENTS.md", hermes_bootstrap)
    else:
        hermes_bootstrap.symlink_to("AGENTS.md")
    print("✅  .hermes.md → AGENTS.md")

    # ── Step 2: Symlink skills into agent directories ─────────────
    agent_dirs = [
        ".claude/skills",
        ".cursor/skills",
        ".windsurf/skills",
        ".agents/skills",
        ".pi/skills",
        ".kiro/skills",
    ]

    for agent_dir in agent_dirs:
        install_skills(SCRIPT_DIR / agent_dir, f"{agent_dir}/", mode="relative")

    # ── Step 3: Install global skills ────────────────────────────
    install_skills(
        Path.home() / ".claude/skills",
        "~/.claude/skills/ (portable wiki skills)",
        mode="absolute",
        subset=["wiki-update", "wiki-query", "wiki-context-pack"],
    )

    install_skills(Path.home() / ".gemini/skills", "~/.gemini/skills/ (Gemini CLI)")
    install_skills(
        Path.home() / ".gemini/antigravity/skills",
        "~/.gemini/antigravity/skills/ (Antigravity, legacy)",
    )
    install_skills(Path.home() / ".codex/skills", "~/.codex/skills/")
    install_skills(Path.home() / ".hermes/skills", "~/.hermes/skills/ (Hermes default)")

    # Hermes: active named profile
    hermes_home = os.environ.get("HERMES_HOME", "")
    if hermes_home and hermes_home != str(Path.home() / ".hermes"):
        profile_name = Path(hermes_home).name
        install_skills(
            Path(hermes_home) / "skills",
            f"{hermes_home}/skills/ (Hermes active profile: {profile_name})",
        )

    # Hermes: all named profiles under ~/.hermes/profiles/
    profiles_dir = Path.home() / ".hermes/profiles"
    if profiles_dir.is_dir():
        for profile_dir in sorted(profiles_dir.iterdir()):
            if not profile_dir.is_dir():
                continue
            profile_name = profile_dir.name
            if hermes_home and hermes_home == str(profile_dir):
                continue
            install_skills(
                profile_dir / "skills",
                f"~/.hermes/profiles/{profile_name}/skills/ (Hermes profile: {profile_name})",
            )

    install_skills(Path.home() / ".openclaw/skills", "~/.openclaw/skills/ (OpenClaw managed)")
    install_skills(Path.home() / ".copilot/skills", "~/.copilot/skills/ (GitHub Copilot CLI)")
    install_skills(Path.home() / ".trae/skills", "~/.trae/skills/ (Trae)")
    install_skills(Path.home() / ".trae-cn/skills", "~/.trae-cn/skills/ (Trae CN)")
    install_skills(Path.home() / ".kiro/skills", "~/.kiro/skills/ (Kiro CLI)")
    install_skills(Path.home() / ".pi/agent/skills", "~/.pi/agent/skills/ (Pi)")
    install_skills(
        Path.home() / ".agents/skills",
        "~/.agents/skills/ (OpenCode, Aider, Droid, generic)",
    )

    # ── Step 4: GitHub sync (optional) ───────────────────────────
    sync_configured = False

    print()
    try:
        setup_sync = input("  Set up GitHub sync for your vault? [y/N]: ").strip()
    except (EOFError, KeyboardInterrupt):
        setup_sync = ""

    if setup_sync.lower() == "y":
        try:
            vault_remote = input(
                "  GitHub repo URL (e.g. https://github.com/you/my-wiki.git): "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            vault_remote = ""

        if vault_remote and vault_path and Path(vault_path).is_dir():
            if run_owiki("sync-setup", vault_remote, "--vault", vault_path):
                sync_configured = True

                # Offer shell alias
                print()
                try:
                    add_alias = input("  Add 'wiki-sync' alias to your shell? [Y/n]: ").strip()
                except (EOFError, KeyboardInterrupt):
                    add_alias = "n"
                if add_alias.lower() != "n":
                    if _IS_WINDOWS:
                        # PowerShell profile
                        pwsh_profile = Path(os.environ.get("PROFILE", Path.home() / "Documents" / "PowerShell" / "Microsoft.PowerShell_profile.ps1"))
                        pwsh_profile.parent.mkdir(parents=True, exist_ok=True)
                        alias_line = "function wiki-sync { obsidian-wiki sync --vault " + vault_path + " }\n"
                        content = pwsh_profile.read_text() if pwsh_profile.is_file() else ""
                        if "wiki-sync" not in content:
                            pwsh_profile.write_text(content + alias_line)
                            shell_rc = str(pwsh_profile)
                            print(f"✅  Added wiki-sync to PowerShell profile: {shell_rc}")
                            print("    → Restart PowerShell or run: . $PROFILE")
                        else:
                            print(f"    ℹ️  wiki-sync already in PowerShell profile")
                    else:
                        shell_rc = ""
                        for rc in [".zshrc", ".bashrc"]:
                            rc_path = Path.home() / rc
                            if rc_path.is_file():
                                shell_rc = str(rc_path)
                                break
                        if shell_rc:
                            rc_content = Path(shell_rc).read_text()
                            if "wiki-sync" not in rc_content:
                                with open(shell_rc, "a") as f:
                                    f.write(
                                        "\n# wiki-sync — push Obsidian vault to GitHub\n"
                                        "alias wiki-sync='obsidian-wiki sync'\n"
                                    )
                                print(f"✅  Added wiki-sync alias to {shell_rc}")
                                print(f"    → Run: source {shell_rc}  (or open a new terminal)")
                            else:
                                print(f"    ℹ️  wiki-sync alias already in {shell_rc}")

                # Offer hourly auto-sync
                print()
                try:
                    add_cron = input("  Enable hourly auto-sync? [y/N]: ").strip()
                except (EOFError, KeyboardInterrupt):
                    add_cron = ""

                if add_cron.lower() == "y":
                    if shutil.which("python3"):
                        sync_cmd = f"{sys.executable} -m obsidian_wiki.cli sync --vault {vault_path}"
                    else:
                        sync_cmd = f"obsidian-wiki sync --vault {vault_path}"

                    if _IS_WINDOWS:
                        # Windows Task Scheduler
                        log_path = GLOBAL_CONFIG_DIR / "sync.log"
                        task_name = "ObsidianWikiHourlySync"
                        result = subprocess.run(
                            [
                                "schtasks", "/create", "/sc", "hourly",
                                "/tn", task_name,
                                "/tr", f'cmd /c "{sync_cmd} >> {log_path} 2>&1"',
                                "/f",
                            ],
                            capture_output=True, text=True,
                        )
                        if result.returncode == 0:
                            print(f"✅  Hourly sync scheduled via Task Scheduler")
                            print(f"    Logs: {log_path}")
                        else:
                            print(f"⚠️  Failed to create scheduled task. Run manually or use Task Scheduler GUI.")
                            print(f"    Command: {sync_cmd}")
                    else:
                        cron_line = f"0 * * * * {sync_cmd} >> {GLOBAL_CONFIG_DIR}/sync.log 2>&1"
                        try:
                            existing = subprocess.run(
                                ["crontab", "-l"], capture_output=True, text=True
                            )
                            lines = existing.stdout.strip().split("\n") if existing.stdout.strip() else []
                        except Exception:
                            lines = []
                        if cron_line not in lines:
                            lines.append(cron_line)
                            lines = [l for l in lines if l.strip()]
                            subprocess.run(
                                ["crontab", "-"],
                                input="\n".join(lines) + "\n",
                                text=True,
                            )
                        print(f"✅  Hourly cron installed  (logs: ~/.obsidian-wiki/sync.log)")

    # ── Step 5: Summary ──────────────────────────────────────────
    skill_count = sum(1 for p in SKILLS_DIR.iterdir() if p.is_dir())

    print()
    print("───────────────────────────────────────────────────")
    print(" Setup complete!")
    print()
    print(f" Skills found:    {skill_count}")
    print(" Agents ready:    Claude Code, Cursor, Windsurf, Gemini CLI, Antigravity,")
    print("                  Codex, Hermes, OpenClaw, OpenCode, Aider, Factory Droid,")
    print("                  Trae, Trae CN, Kiro, Pi, GitHub Copilot (CLI + VS Code Chat)")
    if sync_configured:
        print(" GitHub sync:     wiki-sync  (obsidian-wiki sync)")
    print()
    print(" Bootstrap files:")
    print("   CLAUDE.md                            → Claude Code")
    print("   GEMINI.md                            → Gemini / Antigravity")
    print("   AGENTS.md                            → Codex, OpenClaw, OpenCode, Aider, Droid, Trae, Hermes, Pi")
    print("   .hermes.md                           → Hermes (symlink → AGENTS.md)")
    print("   .cursor/rules/obsidian-wiki.mdc      → Cursor (alwaysApply)")
    print("   .windsurf/rules/obsidian-wiki.md     → Windsurf (always-on)")
    print("   .kiro/steering/obsidian-wiki.md      → Kiro (inclusion: always)")
    print("   .agent/rules/obsidian-wiki.md        → Google Antigravity (alwaysApply)")
    print("   .agent/workflows/obsidian-wiki.md    → Google Antigravity (slash commands)")
    print("   .github/copilot-instructions.md      → GitHub Copilot (VS Code Chat)")
    print()
    print(" Next steps:")
    print("   1. Open this project in your agent")
    print("   2. Say: \"Set up my wiki\"")
    print()
    print(" From any other project:")
    print("   /wiki-update    → sync knowledge into your vault")
    print("   /wiki-query     → ask questions against your wiki")
    print("   /wiki-context-pack → compile bounded context for another agent")
    if sync_configured:
        print("   wiki-sync       → push all vault changes to GitHub")
    print("───────────────────────────────────────────────────")
    print()


if __name__ == "__main__":
    main()
