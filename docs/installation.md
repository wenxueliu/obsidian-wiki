# Installation

Four ways in. Pick one — they all end at the same place: your vault path in `~/.obsidian-wiki/config` and the skills discoverable by your agent.

| Path | Best for | Writes global config | Installs into all agents |
|---|---|---|---|
| [pip](#install-via-pip-recommended) | Most people | ✅ | ✅ |
| [Let your agent do it](#let-your-agent-set-it-up) | No terminal required | ✅ | ✅ |
| [git clone + `python3 setup.py`](#install-via-git-clone) | Contributors, hackers | ✅ | ✅ |
| [Skills CLI](#install-via-skills-cli-deprecated) | Deprecated — partial install | ❌ | ❌ (current agent only) |

## Install via pip (recommended)

```bash
pip install obsidian-wiki
obsidian-wiki setup --vault /path/to/your/digital/brain
```

`obsidian-wiki setup` writes the config to `~/.obsidian-wiki/config` and installs every wiki skill into all your AI agents (Claude Code, Cursor, Codex, Gemini, Hermes, Pi, and more). Skills are symlinked to the installed package, so `pip install -U obsidian-wiki` upgrades them everywhere — just re-run `obsidian-wiki setup` to pick up new skills.

Then open a project in your agent and say **"set up my wiki"**.

Useful flags:

```bash
obsidian-wiki setup --project .   # also drop project-local skills + AGENTS.md into the current repo
obsidian-wiki setup --copy        # copy skill files instead of symlinking
```

For a self-contained project installation using the software-knowledge layout, run:

```bash
obsidian-wiki setup --layout software-knowledge --project . --project-only --copy
```

This selects the `software-knowledge` Knowledge Pack, initializes the configured vault, and
installs project-local skills, bootstrap files, and a missing `.env` from the packaged template
under the current repository. `--project-only`
skips global agent installation; it does not skip vault/configuration setup. `--copy` stores
independent skill files instead of symlinks, which is useful when the project must remain
self-contained.

The project `.env` is created only when it does not already exist; setup never overwrites an
existing project configuration. When `--vault` is supplied, its resolved absolute path is
written to `OBSIDIAN_VAULT_PATH` in the new `.env`.

`OBSIDIAN_VAULT_PATH` is just any directory where you want your digital brain to live — a new empty folder or an existing Obsidian vault. Omit `--vault` to be prompted, or set it later in `~/.obsidian-wiki/config`.

Run `obsidian-wiki info` to see the resolved paths and `obsidian-wiki doctor` to health-check the result. See the [CLI reference](cli.md) for everything else the package ships.

## Let your agent set it up

The fastest path — no commands required. Give your agent this repo and say:

```text
https://github.com/Ar9av/obsidian-wiki — set up my wiki
```

The agent reads [`.skills/wiki-setup/SKILL.md`](../.skills/wiki-setup/SKILL.md) from the repo, asks where you want your vault to live, and initializes the full structure: directories, index, log, Obsidian config, and an optional auto-capture hook. The skill *is* the setup guide.

This works in any agent that can read files (Claude Code, Cursor, Windsurf, Codex, Gemini CLI, Kiro, and more). After setup, every wiki skill is available immediately.

## Install via git clone

```bash
git clone https://github.com/Ar9av/obsidian-wiki.git
cd obsidian-wiki
python3 setup.py
```

`python3 setup.py` asks for your vault path, writes the config to `~/.obsidian-wiki/config`, installs skills into all your agents (copy mode on Windows, symlinks on Unix), and installs `wiki-update`, `wiki-query`, and `wiki-context-pack` globally so you can use them from any project.

Open the project in your agent and say **"set up my wiki"**.

For local-only config, copy `.env.example` to `.env` and set `OBSIDIAN_VAULT_PATH` — a `.env` in the working directory (or any parent up to `$HOME`) takes precedence over the global config. See [Configuration](configuration.md).

### What `python3 setup.py` wires up

1. **Global config** at `~/.obsidian-wiki/config` with your vault path and the repo location. This is how skills know where to read and write.
2. **Portable skills** — `wiki-update`, `wiki-query`, and `wiki-context-pack` symlinked into `~/.claude/skills/` so they're available from any project in Claude Code.
3. **Global symlinks** for every agent's discovery path:
   - `~/.gemini/skills/` — Gemini CLI (canonical)
   - `~/.gemini/antigravity/skills/` — Google Antigravity (legacy)
   - `~/.codex/skills/` — Codex
   - `~/.hermes/skills/` — Hermes
   - `~/.openclaw/skills/` — OpenClaw (managed)
   - `~/.copilot/skills/` — GitHub Copilot CLI
   - `~/.trae/skills/` + `~/.trae-cn/skills/` — Trae / Trae CN
   - `~/.kiro/skills/` — Kiro CLI
   - `~/.pi/agent/skills/` — Pi
   - `~/.agents/skills/` — OpenCode, Aider, Factory Droid, and other `AGENTS.md`-aware agents
4. **Project-local symlinks** — `.claude/skills/`, `.cursor/skills/`, `.windsurf/skills/`, `.agents/skills/`, `.pi/skills/`, `.kiro/skills/`
5. **Always-on rule files** — `CLAUDE.md`, `GEMINI.md`, `AGENTS.md`, `.hermes.md`, `.cursor/rules/…`, `.windsurf/rules/…`, `.kiro/steering/…`, `.agent/rules/…`, `.agent/workflows/…`, `.github/copilot-instructions.md`
6. **GitHub sync** (optional) — see [Configuration → Syncing your vault to GitHub](configuration.md#syncing-your-vault-to-github)

`obsidian-wiki setup` and `python3 setup.py` share one implementation, so pip and source installs produce the identical result.

## Install via Skills CLI (deprecated)

```bash
npx skills add Ar9av/obsidian-wiki
```

This only installs the markdown skills into the current agent. It does **not** write `~/.obsidian-wiki/config`, configure GitHub sync, or wire the global multi-agent bootstrap that `obsidian-wiki setup` / `python3 setup.py` performs.

Use this path only if you intentionally want a partial, agent-local install and are prepared to manage config yourself. For a complete setup, use pip or git clone instead.

Browse the full skill list at [skills.sh/ar9av/obsidian-wiki](https://skills.sh/ar9av/obsidian-wiki).

## Open in Obsidian

Open your vault directory in Obsidian (File → Open Vault). The wiki pages, wikilinks, and graph view all work natively. Nothing about the vault is proprietary — it's markdown files with YAML frontmatter.

## Multiple vaults

Keep a default vault active in `~/.obsidian-wiki/config`, or create named configs like `~/.obsidian-wiki/config.work` with `/wiki-switch new work`.

From any directory, route one request to a named vault with `@name`:

```text
@work update wiki
@research save this
wiki-query @personal what do I know about MCP security
```

The `@name` override applies **only to that request** and never changes your default vault. To change the default, use `/wiki-switch <name>` — it re-points the active symlink.

All supported agents can use this syntax after `obsidian-wiki setup` or `python3 setup.py`, because the shared skills and always-on bootstrap files all point back to the same Config Resolution Protocol. Claude Code, Cursor, Windsurf, Codex, Gemini, Kiro, Hermes, OpenClaw, Copilot CLI, Pi, and the generic `AGENTS.md` agents all pick it up from the same instructions.

The routing token works with write skills (`@work update wiki`, `@research save this`) and read skills (`wiki-query @personal what do I know about X`).

## Verifying the install

```bash
obsidian-wiki doctor
```

`doctor` catches broken setup, stale installs, and malformed vault state. Add `--json` for machine-readable output.

## Next steps

- [Skills Reference](skills.md) — what you can actually ask for
- [Configuration](configuration.md) — every config variable, QMD, GitHub sync
- [Agent Compatibility](agents.md) — per-agent details and manual setup
