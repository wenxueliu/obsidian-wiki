#!/usr/bin/env python3
"""
Daily wiki index update — called by cron/launchd or directly.

Checks if any history sources are stale and writes vault-scoped state files
that the shell prompt reads on terminal open.

Config resolution order (mirrors llm-wiki/SKILL.md protocol):
  1. Walk up from CWD looking for .env with OBSIDIAN_VAULT_PATH
  2. Fall back to ~/.obsidian-wiki/config
  3. Exit with error if neither found
"""

import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def find_config():
    """Walk up from CWD looking for .env, then fall back to global config."""
    cwd = Path.cwd()
    for directory in [cwd, *cwd.parents]:
        env_file = directory / ".env"
        if env_file.is_file():
            content = env_file.read_text()
            if "OBSIDIAN_VAULT_PATH" in content:
                return str(env_file)
        if directory == Path.home():
            break

    global_config = Path.home() / ".obsidian-wiki" / "config"
    if global_config.is_file():
        return str(global_config)

    return ""


def read_config(config_file):
    """Parse OBSIDIAN_VAULT_PATH from config file."""
    content = Path(config_file).read_text()
    for line in content.splitlines():
        if line.startswith("OBSIDIAN_VAULT_PATH="):
            val = line.split("=", 1)[1].strip().strip('"')
            return val
    return ""


def count_stale_sources(vault_path):
    """Count sources modified after last ingest in manifest.json."""
    manifest_path = Path(vault_path) / ".manifest.json"
    if not manifest_path.is_file():
        return 0

    try:
        manifest = json.loads(manifest_path.read_text())
    except (json.JSONDecodeError, OSError):
        return 0

    last_updated_str = manifest.get("last_updated", "")
    if not last_updated_str:
        return 0

    try:
        last_updated = datetime.fromisoformat(last_updated_str.replace("Z", "+00:00"))
    except ValueError:
        return 0

    if last_updated.tzinfo is None:
        last_updated = last_updated.replace(tzinfo=timezone.utc)

    stale = 0
    for path_str, meta in manifest.get("sources", {}).items():
        expanded = os.path.expanduser(path_str)
        if not os.path.isabs(expanded) and vault_path:
            expanded = os.path.join(vault_path, expanded)
        expanded_path = Path(expanded)
        if expanded_path.exists():
            mtime = datetime.fromtimestamp(expanded_path.stat().st_mtime, tz=timezone.utc)
            if mtime > last_updated:
                stale += 1

    return stale


def main():
    config_file = find_config()

    if not config_file:
        print("[wiki-daily] No config found. Run wiki-setup to initialize your wiki.", file=sys.stderr)
        sys.exit(1)

    vault_path = read_config(config_file)

    if not vault_path:
        print(f"[wiki-daily] OBSIDIAN_VAULT_PATH not set in {config_file} — skipping", file=sys.stderr)
        sys.exit(1)

    # Vault-scoped state dir
    vault_hash = hashlib.md5(vault_path.encode()).hexdigest()[:8]
    state_dir = Path.home() / ".obsidian-wiki" / "state" / vault_hash
    state_dir.mkdir(parents=True, exist_ok=True)

    # Write vault path
    (state_dir / ".vault_path").write_text(vault_path)

    # Count stale sources
    stale_count = count_stale_sources(vault_path)

    # Write vault-scoped state
    now = int(time.time())
    (state_dir / ".last_update").write_text(str(now))
    (state_dir / ".pending_delta").write_text(str(stale_count))

    if stale_count > 0:
        print(f"[wiki-daily] {stale_count} source(s) have new content since last ingest. State: {state_dir}")
    else:
        print(f"[wiki-daily] Wiki is up to date. State: {state_dir}")


if __name__ == "__main__":
    main()
