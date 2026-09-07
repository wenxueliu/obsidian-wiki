# Installation

Four ways in. Pick one — they all end at the same place: your vault path in `~/.obsidian-wiki/config` and the skills discoverable by your agent.

| Path | Best for | Writes global config | Agent skill targets |
|---|---|---|---|
| [pip](#install-via-pip-recommended) | Most people | ✅ | User-selected, command-directory only |
| [Let your agent do it](#let-your-agent-set-it-up) | No terminal required | ✅ | Current agent |
| [git clone + `python3 setup.py`](#install-via-git-clone) | Contributors, hackers | ✅ | Legacy all-agent installer |
| [Skills CLI](#install-via-skills-cli-deprecated) | Deprecated — partial install | ❌ | Current agent only |

## Install via pip (recommended)

```bash
pip install obsidian-wiki
obsidian-wiki setup --vault /path/to/your/digital/brain
```

`obsidian-wiki setup` writes the config to `~/.obsidian-wiki/config` and asks which agent skill
targets to install. It has no implicit all-agent selection and never installs skills globally.
Skills and bootstrap files are written only under the directory where the command runs (or the
explicit `--project DIR` override). Skills are symlinked to the installed package, so
`pip install -U obsidian-wiki` upgrades the selected targets when setup is run again.

For scripts and other non-interactive environments, select targets explicitly:

```bash
obsidian-wiki setup --vault /path/to/brain --knowledge-pack default --agent claude --agent codex
obsidian-wiki setup --vault /path/to/brain --knowledge-pack software-knowledge --agent claude,codex,pi
obsidian-wiki setup --vault /path/to/brain --knowledge-pack default --agent all
```

Run `obsidian-wiki setup --list-agents` to see the stable project-local target names. Non-interactive setup requires an explicit selection; use `--agent none`
only when intentionally configuring the vault without installing agent skills.

If `--knowledge-pack` is omitted in a terminal, setup displays the available Knowledge Packs and requires
one selection. Agent selection accepts multiple values; Knowledge Pack selection is always single-choice.
Non-interactive setup must pass `--knowledge-pack NAME` explicitly.

Then open that directory in your agent and say **"set up my wiki"**.

Useful flags:

```bash
obsidian-wiki setup --project /work/app  # override the command-directory target
obsidian-wiki setup --copy        # copy skill files instead of symlinking
```

For a self-contained project installation using the `software-knowledge` Pack, run:

```bash
obsidian-wiki setup --knowledge-pack software-knowledge --copy --agent cursor
```

This selects the `software-knowledge` Knowledge Pack, initializes the configured vault, and
installs the selected agent's project-local skills and bootstrap files, plus a missing `.env` from the packaged template
under the command directory. The deprecated `--project-only` flag is retained as a no-op for compatibility because
CLI setup no longer has any global skill-install phase. `--copy` stores
independent skill files instead of symlinks, which is useful when the project must remain
self-contained.

The project `.env` is created only when it does not already exist; setup never overwrites an
existing project configuration. When `--vault` is supplied, its resolved absolute path is
written to `OBSIDIAN_VAULT_PATH` in the new `.env`. Setup also fills the stable context bindings
declared by `.env.example`: the Knowledge Pack, owner/Writing Profile paths, vault metadata and
taxonomy paths, and the persistent compiled-context snapshot path. Existing `.env` files remain
preserved except that setup fills missing or blank stable-binding keys; non-empty custom values,
unknown fields, and comments are retained. Run setup/repair after changing these bindings.

`OBSIDIAN_VAULT_PATH` is just any directory where you want your digital brain to live — a new empty folder or an existing Obsidian vault. In an interactive terminal, omit `--vault` to enter the folder; the displayed default is the current directory, accepted by pressing Enter. In a non-interactive run, pass `--vault` explicitly or use the existing value in `~/.obsidian-wiki/config`.

The agent selection also filters generated project rules and entry files. Selecting only Claude,
for example, creates shared `AGENTS.md`, `CLAUDE.md`, and `.claude/skills/`, without generating
the files for other agents. Selecting several agents generates the union of their files.

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
3. **Global symlinks** for every agent's discovery path (legacy `python3 setup.py` behavior):
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

The two entry points use the same packaged skills and vault contracts, but their target selection
differs: `obsidian-wiki setup` installs only explicitly selected agents, while the legacy
`python3 setup.py` source installer still wires every supported agent path.

## Install via Skills CLI (deprecated)

```bash
npx skills add Ar9av/obsidian-wiki
```

This only installs the markdown skills into the current agent. It does **not** write `~/.obsidian-wiki/config`, configure GitHub sync, or wire the project bootstrap that `obsidian-wiki setup` performs. The legacy `python3 setup.py` source installer additionally wires global agent directories.

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
