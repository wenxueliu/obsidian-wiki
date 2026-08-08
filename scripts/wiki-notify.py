#!/usr/bin/env python3
"""
Source this from your shell rc file to get wiki freshness reminders on terminal open.

Setup (shell-specific):
  zsh/bash:  python3 /path/to/obsidian-wiki/scripts/wiki-notify.py
  fish:      python3 /path/to/obsidian-wiki/scripts/wiki-notify.py

State is vault-scoped under ~/.obsidian-wiki/state/<vault-id>/
Multiple vaults are supported — all stale vaults are shown.
"""

import time
from pathlib import Path

STATE_BASE = Path.home() / ".obsidian-wiki" / "state"


def main():
    if not STATE_BASE.is_dir():
        return

    now = int(time.time())
    shown = 0

    for state_dir in sorted(STATE_BASE.iterdir()):
        if not state_dir.is_dir():
            continue

        last_update_file = state_dir / ".last_update"
        if not last_update_file.is_file():
            continue

        try:
            last = int(last_update_file.read_text().strip())
        except (ValueError, OSError):
            continue

        age_s = now - last

        # Only show if >20 hours stale
        if age_s <= 72000:
            continue

        age_h = age_s // 3600

        try:
            stale = (state_dir / ".pending_delta").read_text().strip()
        except OSError:
            stale = "0"

        try:
            vault_path = (state_dir / ".vault_path").read_text().strip()
        except OSError:
            vault_path = "unknown vault"

        vault_name = Path(vault_path).name

        stale_msg = f" · {stale} source(s) have new content" if stale and stale != "0" else ""
        print(f"┌─ wiki: last synced {age_h}h ago · {vault_name}{stale_msg}")
        print("│  /wiki-history-ingest claude   sync Claude sessions")
        print("│  /wiki-status                  see full delta")
        print("└─ /memory-bridge diff           compare tool memories")
        shown += 1


if __name__ == "__main__":
    main()
