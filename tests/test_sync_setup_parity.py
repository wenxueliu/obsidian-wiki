"""Regression guard for issue #153.

Both `setup.py` (source/curl installs) and `obsidian-wiki setup` (pip/uv CLI)
delegate to obsidian_wiki/sync.py. These tests pin that setup.py calls into the
CLI instead of re-implementing git plumbing, and that the CLI exposes the
subcommands setup.py (and agents, via wiki-setup) depend on.
"""
from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SetupPyDelegatesToCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.setup_py = (ROOT / "setup.py").read_text()

    def test_calls_sync_setup_subcommand(self) -> None:
        self.assertIn("sync-setup", self.setup_py)

    def test_calls_cli_module_not_a_standalone_git_flow(self) -> None:
        self.assertIn("obsidian_wiki.cli", self.setup_py)

    def test_does_not_hand_roll_git_init(self) -> None:
        self.assertNotIn('git -C "$VAULT_PATH" init', self.setup_py)

    def test_does_not_generate_a_standalone_sync_script(self) -> None:
        self.assertNotIn("Wrote ~/.obsidian-wiki/sync.sh", self.setup_py)


class EnvExampleDoesNotOverclaimTest(unittest.TestCase):
    def test_no_dangling_vault_github_remote_var(self) -> None:
        env_example = (ROOT / ".env.example").read_text()
        self.assertNotIn("VAULT_GITHUB_REMOTE", env_example)


class CliExposesSyncSubcommandsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.cli = (ROOT / "obsidian_wiki" / "cli.py").read_text()

    def test_sync_setup_subcommand_registered(self) -> None:
        self.assertIn('sub.add_parser(\n        "sync-setup"', self.cli)

    def test_sync_subcommand_registered(self) -> None:
        self.assertIn('sub.add_parser("sync"', self.cli)

    def test_setup_command_offers_sync(self) -> None:
        self.assertIn("_maybe_configure_sync", self.cli)


class SetupShRemovedTest(unittest.TestCase):
    def test_setup_sh_no_longer_exists(self) -> None:
        self.assertFalse((ROOT / "setup.sh").exists(),
                         "setup.sh has been replaced by setup.py — remove stale references")


if __name__ == "__main__":
    unittest.main()
