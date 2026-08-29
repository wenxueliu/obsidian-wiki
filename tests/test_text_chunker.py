from __future__ import annotations

import json
import subprocess
import sys
import tracemalloc
from collections.abc import Iterable
from pathlib import Path

import pytest

from obsidian_wiki.text_chunker import (
    DEFAULT_CHUNK_STRATEGY,
    ChunkStrategyContext,
    ChunkPlan,
    InvalidTextEncodingError,
    SourceChangedError,
    TextBlock,
    TextChunkError,
    UnsupportedTextFormatError,
    plan_text_chunks,
    read_text_chunk,
    register_chunk_strategy,
    unregister_chunk_strategy,
    validate_chunk_plan,
)


def _covered_bytes(source: Path, plan: ChunkPlan) -> bytes:
    return b"".join(
        read_text_chunk(source, unit).encode("utf-8") for unit in plan.units
    )


def test_markdown_plan_is_deterministic_exhaustive_and_heading_aware(tmp_path):
    source = tmp_path / "notes.md"
    source.write_text(
        "# First\n\nalpha\n\n```md\n# not a heading\n```\n\n## Child\n\nbeta\n",
        encoding="utf-8",
    )

    first = plan_text_chunks(source, target_budget=24, hard_budget=32)
    second = plan_text_chunks(source, target_budget=24, hard_budget=32)

    assert first.to_dict() == second.to_dict()
    assert _covered_bytes(source, first) == source.read_bytes()
    assert all(unit.size_bytes <= 32 for unit in first.units)
    assert any(("First", "Child") in unit.heading_paths for unit in first.units)
    assert all("not a heading" not in unit.heading_path for unit in first.units)
    assert [unit.start_byte for unit in first.units] == sorted(
        unit.start_byte for unit in first.units
    )


def test_adaptive_strategy_merges_many_short_sections(tmp_path):
    source = tmp_path / "short-sections.md"
    source.write_text(
        "".join(f"## Section {index}\n\nshort {index}\n\n" for index in range(1, 7)),
        encoding="utf-8",
    )

    adaptive = plan_text_chunks(
        source, target_budget=160, hard_budget=200, min_budget=80,
    )
    strict = plan_text_chunks(
        source, target_budget=160, hard_budget=200, min_budget=80,
        chunk_strategy="strict_sections",
    )

    assert adaptive.chunk_strategy == DEFAULT_CHUNK_STRATEGY
    assert len(adaptive.units) < len(strict.units)
    assert len(adaptive.units[0].heading_paths) > 1
    assert len(strict.units) == 6
    assert _covered_bytes(source, adaptive) == source.read_bytes()


def test_adaptive_strategy_rebalances_a_small_tail_up_to_hard_cap(tmp_path):
    source = tmp_path / "tail.txt"
    source.write_text("a" * 34 + "\n\n" + "b" * 34 + "\n", encoding="utf-8")

    plan = plan_text_chunks(
        source, target_budget=60, hard_budget=80, min_budget=40,
    )

    assert len(plan.units) == 1
    assert plan.units[0].size_bytes > plan.target_budget
    assert plan.units[0].size_bytes <= plan.hard_budget
    assert _covered_bytes(source, plan) == source.read_bytes()


def test_registered_custom_chunk_strategy_is_validated_and_recorded(tmp_path):
    source = tmp_path / "custom.md"
    source.write_text("# One\n\nbody\n\n# Two\n\nbody\n", encoding="utf-8")
    observed: dict[str, object] = {}

    def one_block_per_unit(
        blocks: Iterable[TextBlock], context: ChunkStrategyContext
    ) -> list[tuple[TextBlock, ...]]:
        observed["options"] = context.options
        values = list(blocks)
        observed["block_count"] = len(values)
        return [(block,) for block in values]

    register_chunk_strategy("test_one_block", one_block_per_unit)
    try:
        plan = plan_text_chunks(
            source,
            target_budget=100,
            hard_budget=120,
            min_budget=25,
            chunk_strategy="test_one_block",
            strategy_options={"owner": "test"},
        )
    finally:
        unregister_chunk_strategy("test_one_block")

    assert plan.chunk_strategy == "test_one_block"
    assert plan.strategy_options == {"owner": "test"}
    assert observed["options"] == {"owner": "test"}
    assert len(plan.units) == observed["block_count"]
    assert _covered_bytes(source, plan) == source.read_bytes()


def test_installed_entry_point_chunk_strategy_is_discovered(tmp_path, monkeypatch):
    source = tmp_path / "plugin.txt"
    source.write_text("one\n\ntwo\n", encoding="utf-8")

    def installed_strategy(
        blocks: Iterable[TextBlock], context: ChunkStrategyContext
    ) -> Iterable[Iterable[TextBlock]]:
        for block in blocks:
            yield (block,)

    class FakeEntryPoint:
        name = "installed_test"

        @staticmethod
        def load():
            return installed_strategy

    class FakeEntryPoints(list):
        def select(self, *, group: str):
            assert group == "obsidian_wiki.text_chunk_strategies"
            return self

    monkeypatch.setattr(
        "obsidian_wiki.text_chunker.metadata.entry_points",
        lambda: FakeEntryPoints([FakeEntryPoint()]),
    )

    plan = plan_text_chunks(
        source, target_budget=20, hard_budget=24,
        chunk_strategy="installed_test",
    )

    assert plan.chunk_strategy == "installed_test"
    assert len(plan.units) == 2
    assert _covered_bytes(source, plan) == source.read_bytes()


def test_bom_is_accepted_and_excluded_from_coverage(tmp_path):
    source = tmp_path / "bom.txt"
    source.write_bytes(b"\xef\xbb\xbfhello\nworld\n")
    plan = plan_text_chunks(source, target_budget=8, hard_budget=10)

    assert plan.encoding == "utf-8-sig"
    assert plan.units[0].start_byte == 3
    assert _covered_bytes(source, plan) == b"hello\nworld\n"


def test_invalid_utf8_and_unsupported_extensions_fail_explicitly(tmp_path):
    invalid = tmp_path / "invalid.txt"
    invalid.write_bytes(b"good\n\xffbad")
    with pytest.raises(InvalidTextEncodingError, match="convert it to UTF-8"):
        plan_text_chunks(invalid)

    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"plain text in disguise")
    with pytest.raises(UnsupportedTextFormatError):
        plan_text_chunks(pdf)


def test_oversized_unicode_line_splits_on_utf8_boundaries(tmp_path):
    source = tmp_path / "unicode.txt"
    source.write_text("界" * 30, encoding="utf-8")
    plan = plan_text_chunks(source, target_budget=10, hard_budget=11)

    assert len(plan.units) > 1
    assert all(unit.size_bytes <= 11 for unit in plan.units)
    assert all(unit.forced_split for unit in plan.units)
    assert {unit.split_reason for unit in plan.units} == {"oversized_line"}
    assert _covered_bytes(source, plan) == source.read_bytes()


def test_oversized_code_fence_is_marked_and_fully_covered(tmp_path):
    source = tmp_path / "code.md"
    source.write_text("```text\n" + "line\n" * 20 + "```\n", encoding="utf-8")
    plan = plan_text_chunks(source, target_budget=20, hard_budget=24)

    assert any(unit.split_reason == "oversized_code_fence" for unit in plan.units)
    assert _covered_bytes(source, plan) == source.read_bytes()


def test_rst_headings_and_headingless_text(tmp_path):
    rst = tmp_path / "guide.rst"
    rst.write_text("Title\n=====\n\nIntro.\n\nChild\n-----\n\nBody.\n", encoding="utf-8")
    plan = plan_text_chunks(rst, target_budget=30, hard_budget=40)
    assert any(unit.heading_path == ("Title", "Child") for unit in plan.units)

    plain = tmp_path / "plain.txt"
    plain.write_text(("paragraph words\n\n" * 20), encoding="utf-8")
    plain_plan = plan_text_chunks(plain, target_budget=40, hard_budget=48)
    assert len(plain_plan.units) > 1
    assert _covered_bytes(plain, plain_plan) == plain.read_bytes()


def test_rst_overline_and_clear_plain_text_sections(tmp_path):
    rst = tmp_path / "overline.rst"
    rst.write_text("=====\nTitle\n=====\n\nBody.\n", encoding="utf-8")
    assert plan_text_chunks(rst).units[0].heading_path == ("Title",)

    plain = tmp_path / "sections.txt"
    plain.write_text("Overview\n========\n\nBody.\n", encoding="utf-8")
    assert plan_text_chunks(plain).units[0].heading_path == ("Overview",)


def test_materialization_rejects_changed_source_and_round_trips_plan(tmp_path):
    source = tmp_path / "source.md"
    source.write_text("# Heading\n\nbody\n", encoding="utf-8")
    plan = plan_text_chunks(source, target_budget=12, hard_budget=20)
    restored = ChunkPlan.from_dict(plan.to_dict())
    validate_chunk_plan(restored)
    assert read_text_chunk(source, restored.units[0])

    source.write_text("changed", encoding="utf-8")
    with pytest.raises(SourceChangedError):
        read_text_chunk(source, restored.units[0])


def test_budget_validation(tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("x", encoding="utf-8")
    with pytest.raises(TextChunkError):
        plan_text_chunks(source, target_budget=20, hard_budget=10)
    with pytest.raises(TextChunkError, match="safe maximum"):
        plan_text_chunks(source, target_budget=1, hard_budget=64_001)
    assert plan_text_chunks(
        source, target_budget=1, hard_budget=64_001, allow_unsafe_hard_budget=True
    ).hard_budget == 64_001


def test_cli_plan_and_exact_read(tmp_path):
    source = tmp_path / "cli.md"
    source.write_text("# CLI\n\nhello 世界\n", encoding="utf-8")
    plan_result = subprocess.run(
        [sys.executable, "-m", "obsidian_wiki", "text-chunk-plan", str(source),
         "--target-budget", "20", "--hard-budget", "24"],
        capture_output=True, text=True,
    )
    assert plan_result.returncode == 0, plan_result.stderr
    plan = json.loads(plan_result.stdout)
    unit = plan["units"][0]
    read_result = subprocess.run(
        [sys.executable, "-m", "obsidian_wiki", "text-chunk-read", str(source),
         "--start-byte", str(unit["start_byte"]), "--end-byte", str(unit["end_byte"]),
         "--expect-hash", plan["source"]["content_hash"]],
        capture_output=True,
    )
    assert read_result.returncode == 0, read_result.stderr.decode()
    assert read_result.stdout == source.read_bytes()[unit["start_byte"]:unit["end_byte"]]


def test_cli_lists_strategies_and_reads_options_file(tmp_path):
    source = tmp_path / "cli-options.md"
    source.write_text("## One\n\nshort\n\n## Two\n\nshort\n", encoding="utf-8")
    options = tmp_path / "options.json"
    options.write_text('{"owner":"cli"}', encoding="utf-8")

    listed = subprocess.run(
        [sys.executable, "-m", "obsidian_wiki", "text-chunk-strategies"],
        capture_output=True, text=True,
    )
    planned = subprocess.run(
        [
            sys.executable, "-m", "obsidian_wiki", "text-chunk-plan", str(source),
            "--strategy-options-file", str(options),
        ],
        capture_output=True, text=True,
    )

    assert listed.returncode == 0, listed.stderr
    assert {"adaptive_sections", "strict_sections"}.issubset(
        json.loads(listed.stdout)["strategies"]
    )
    assert planned.returncode == 0, planned.stderr
    assert json.loads(planned.stdout)["chunking"] == {
        "strategy": "adaptive_sections", "options": {"owner": "cli"},
    }


def test_large_paragraph_fixture_is_scanned_with_bounded_memory(tmp_path):
    source = tmp_path / "large.txt"
    paragraph = ("bounded streaming paragraph " * 32 + "\n\n").encode("utf-8")
    with source.open("wb") as stream:
        for _ in range(6_000):
            stream.write(paragraph)
    assert source.stat().st_size > 5_000_000

    tracemalloc.start()
    plan = plan_text_chunks(source)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert len(plan.units) > 50
    assert peak < source.stat().st_size // 2
