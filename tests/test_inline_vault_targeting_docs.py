from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class InlineVaultTargetingDocsTest(unittest.TestCase):
    def read(self, relpath: str) -> str:
        return (ROOT / relpath).read_text()

    def test_central_protocol_documents_inline_override_before_fallbacks(self) -> None:
        wiki_context = self.read(".skills/wiki-context/SKILL.md")
        agents = self.read("AGENTS.md")

        self.assertIn("invocation 含 `@name`", wiki_context)
        self.assertIn("严格按 `@name` 指定 config", wiki_context)
        self.assertIn("0. **Inline vault override (`@name`)", agents)
        self.assertIn("do **not** silently fall back to the default", agents)

    def test_skill_resolution_summaries_include_inline_override(self) -> None:
        stale = []
        for skill_file in sorted((ROOT / ".skills").glob("*/SKILL.md")):
            text = skill_file.read_text()
            if "follow the Config Resolution Protocol" not in text:
                continue
            if "walk up CWD for `.env`" in text and "inline `@name` override" not in text:
                stale.append(skill_file.relative_to(ROOT).as_posix())

        self.assertEqual(stale, [])

    def test_agent_bootstrap_files_mention_named_vault_routing(self) -> None:
        for relpath in [
            "AGENTS.md",
            ".agent/rules/obsidian-wiki.md",
            ".cursor/rules/obsidian-wiki.mdc",
            ".github/copilot-instructions.md",
            ".kiro/steering/obsidian-wiki.md",
            ".windsurf/rules/obsidian-wiki.md",
            "docs/installation.md",
            "SETUP.md",
        ]:
            with self.subTest(relpath=relpath):
                self.assertIn("@name", self.read(relpath))

    def test_install_docs_say_all_supported_agents_inherit_named_vault_routing(self) -> None:
        install = self.read("docs/installation.md")

        self.assertIn("All supported agents can use this syntax", install)
        self.assertIn("Claude Code, Cursor, Windsurf, Codex, Gemini", install)

    def test_core_workflows_delegate_named_vault_resolution(self) -> None:
        for relpath in (
            ".skills/wiki-query/SKILL.md",
            ".skills/wiki-update/SKILL.md",
        ):
            with self.subTest(relpath=relpath):
                self.assertIn("调用 `wiki-context` skill", self.read(relpath))
        self.assertIn("@research save this", self.read(".skills/wiki-capture/SKILL.md"))

    def test_wiki_query_does_not_prefer_default_over_inline_override(self) -> None:
        wiki_context = self.read(".skills/wiki-context/SKILL.md")

        self.assertIn("严格按 `@name` 指定 config", wiki_context)
        self.assertIn("再到全局 `~/.obsidian-wiki/config`", wiki_context)
        self.assertNotIn("Prefer `~/.obsidian-wiki/config`", wiki_context)


if __name__ == "__main__":
    unittest.main()
