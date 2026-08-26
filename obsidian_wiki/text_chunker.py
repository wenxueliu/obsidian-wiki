"""Deterministic, dependency-free partitioning for supported text sources.

The chunker deliberately knows nothing about vaults, manifests, or language
models.  It scans a source incrementally, records exhaustive byte ranges, and
materialises only a requested range after verifying the source hash.
"""

from __future__ import annotations

import codecs
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator


CHUNK_PLAN_VERSION = 1
CHUNKER_VERSION = 1
DEFAULT_TARGET_BUDGET = 48_000
DEFAULT_HARD_BUDGET = 64_000
MAX_SAFE_HARD_BUDGET = DEFAULT_HARD_BUDGET
SUPPORTED_EXTENSIONS = frozenset({".md", ".markdown", ".mdx", ".txt", ".rst"})


class TextChunkError(ValueError):
    """Base class for deterministic chunking failures."""


class UnsupportedTextFormatError(TextChunkError):
    """Raised when a source extension is outside the V1 text scope."""


class InvalidTextEncodingError(TextChunkError):
    """Raised when a source is not valid UTF-8 (with an optional BOM)."""


class SourceChangedError(TextChunkError):
    """Raised when a source no longer matches the version that was planned."""


@dataclass(frozen=True)
class ChunkUnit:
    unit_id: str
    heading_path: tuple[str, ...]
    start_line: int
    end_line: int
    start_byte: int
    end_byte: int
    size_bytes: int
    estimated_tokens: int | None = None
    forced_split: bool = False
    split_reason: str | None = None
    # Populated by the planner/from_dict but intentionally omitted from the
    # public unit JSON. It binds read_text_chunk() to the planned source.
    _source_hash: str | None = field(default=None, repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "unit_id": self.unit_id,
            "heading_path": list(self.heading_path),
            "start_line": self.start_line,
            "end_line": self.end_line,
            "start_byte": self.start_byte,
            "end_byte": self.end_byte,
            "size_bytes": self.size_bytes,
            "estimated_tokens": self.estimated_tokens,
            "forced_split": self.forced_split,
        }
        if self.split_reason is not None:
            result["split_reason"] = self.split_reason
        return result

    @classmethod
    def from_dict(cls, value: dict[str, Any], *, source_hash: str | None = None) -> "ChunkUnit":
        return cls(
            unit_id=str(value["unit_id"]),
            heading_path=tuple(str(part) for part in value.get("heading_path", [])),
            start_line=int(value["start_line"]),
            end_line=int(value["end_line"]),
            start_byte=int(value["start_byte"]),
            end_byte=int(value["end_byte"]),
            size_bytes=int(value["size_bytes"]),
            estimated_tokens=value.get("estimated_tokens"),
            forced_split=bool(value.get("forced_split", False)),
            split_reason=value.get("split_reason"),
            _source_hash=source_hash,
        )


@dataclass(frozen=True)
class ChunkPlan:
    source_path: str
    content_hash: str
    encoding: str
    size_bytes: int
    line_count: int
    target_budget: int
    hard_budget: int
    units: tuple[ChunkUnit, ...]
    warnings: tuple[str, ...] = ()
    chunk_plan_version: int = CHUNK_PLAN_VERSION
    chunker_version: int = CHUNKER_VERSION

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "chunk_plan_version": self.chunk_plan_version,
            "chunker_version": self.chunker_version,
            "source": {
                "path": self.source_path,
                "content_hash": self.content_hash,
                "encoding": self.encoding,
                "size_bytes": self.size_bytes,
                "line_count": self.line_count,
            },
            "budget": {
                "mode": "utf8_bytes",
                "target": self.target_budget,
                "hard_max": self.hard_budget,
            },
            "units": [unit.to_dict() for unit in self.units],
        }
        if self.warnings:
            result["warnings"] = list(self.warnings)
        return result

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ChunkPlan":
        source = value["source"]
        budget = value["budget"]
        source_hash = str(source["content_hash"])
        return cls(
            source_path=str(source["path"]),
            content_hash=source_hash,
            encoding=str(source.get("encoding", "utf-8")),
            size_bytes=int(source["size_bytes"]),
            line_count=int(source["line_count"]),
            target_budget=int(budget["target"]),
            hard_budget=int(budget["hard_max"]),
            units=tuple(
                ChunkUnit.from_dict(unit, source_hash=source_hash)
                for unit in value.get("units", [])
            ),
            warnings=tuple(str(item) for item in value.get("warnings", [])),
            chunk_plan_version=int(value.get("chunk_plan_version", CHUNK_PLAN_VERSION)),
            chunker_version=int(value.get("chunker_version", CHUNKER_VERSION)),
        )


@dataclass(frozen=True)
class _Block:
    start_byte: int
    end_byte: int
    start_line: int
    end_line: int
    heading_path: tuple[str, ...]
    top_section: int
    kind: str
    data: bytes

    @property
    def size(self) -> int:
        return self.end_byte - self.start_byte


_ATX_HEADING = re.compile(r"^[ \t]{0,3}(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
_FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")
_RST_UNDERLINE = re.compile(r"^[ \t]*([=\-~^\"'`:+*#<>_])\1{2,}[ \t]*$")
_RST_LEVELS = "=-~^\"'`:+*#<>_"


def _normalise_hash(value: str) -> str:
    return value if value.startswith("sha256:") else f"sha256:{value}"


def _validate_source(source: Path) -> Path:
    path = Path(source).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"text source does not exist or is not a regular file: {path}")
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise UnsupportedTextFormatError(
            f"unsupported text format {path.suffix or '(no extension)'}; V1 supports: {supported}"
        )
    return path


def _validate_budgets(
    target_budget: int, hard_budget: int, *, allow_unsafe_hard_budget: bool
) -> None:
    if target_budget <= 0 or hard_budget <= 0:
        raise TextChunkError("target_budget and hard_budget must be positive")
    if target_budget > hard_budget:
        raise TextChunkError("target_budget cannot exceed hard_budget")
    if hard_budget > MAX_SAFE_HARD_BUDGET and not allow_unsafe_hard_budget:
        raise TextChunkError(
            f"hard_budget exceeds the documented safe maximum of {MAX_SAFE_HARD_BUDGET} bytes; "
            "an explicit unsafe-budget override is required"
        )


def _decode_line(raw: bytes, path: Path, byte_offset: int) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        absolute = byte_offset + exc.start
        raise InvalidTextEncodingError(
            f"{path} is not valid UTF-8 near byte {absolute}; convert it to UTF-8 and retry"
        ) from exc


def _markdown_blocks(
    path: Path, start_offset: int, warnings: list[str], stats: dict[str, int]
) -> Iterator[_Block]:
    heading_levels: list[str] = []
    top_section = 0
    current: list[tuple[bytes, str, int, int]] = []
    fence_marker: str | None = None
    line_no = 0

    def emit(kind: str = "paragraph") -> _Block | None:
        nonlocal current
        if not current:
            return None
        raw = b"".join(item[0] for item in current)
        block = _Block(
            start_byte=current[0][2], end_byte=current[-1][2] + len(current[-1][0]),
            start_line=current[0][3], end_line=current[-1][3],
            heading_path=tuple(heading_levels), top_section=top_section,
            kind=kind, data=raw,
        )
        current = []
        return block

    with path.open("rb") as stream:
        stream.seek(start_offset)
        byte_offset = start_offset
        for raw in stream:
            line_no += 1
            text = _decode_line(raw, path, byte_offset).rstrip("\r\n")
            fence = _FENCE.match(text)
            if fence_marker is not None:
                current.append((raw, text, byte_offset, line_no))
                if fence and fence.group(1)[0] == fence_marker[0] and len(fence.group(1)) >= len(fence_marker):
                    block = emit("code_fence")
                    if block is not None:
                        yield block
                    fence_marker = None
                byte_offset += len(raw)
                continue
            if fence:
                block = emit()
                if block is not None:
                    yield block
                fence_marker = fence.group(1)
                current.append((raw, text, byte_offset, line_no))
                byte_offset += len(raw)
                continue
            heading = _ATX_HEADING.match(text)
            if heading:
                block = emit()
                if block is not None:
                    yield block
                level = len(heading.group(1))
                title = heading.group(2).strip()
                heading_levels[level - 1:] = [title]
                if level == 1:
                    top_section += 1
                current.append((raw, text, byte_offset, line_no))
                block = emit("heading")
                if block is not None:
                    yield block
            else:
                current.append((raw, text, byte_offset, line_no))
                if not text.strip():
                    block = emit()
                    if block is not None:
                        yield block
            byte_offset += len(raw)
    if fence_marker is not None:
        warnings.append("malformed_markdown_fence: unclosed fence was split conservatively if needed")
        block = emit("code_fence")
    else:
        block = emit()
    if block is not None:
        yield block
    stats["line_count"] = line_no


def _plain_or_rst_blocks(
    path: Path, start_offset: int, *, rst: bool, stats: dict[str, int]
) -> Iterator[_Block]:
    current: list[tuple[bytes, str, int, int]] = []
    heading_levels: list[str] = []
    top_section = 0
    line_no = 0

    def emit() -> _Block | None:
        nonlocal current, top_section
        if not current:
            return None
        nonblank = [item for item in current if item[1].strip()]
        block_heading = tuple(heading_levels)
        kind = "paragraph"
        heading_title: str | None = None
        heading_level = 0
        if len(nonblank) >= 2:
            underline = _RST_UNDERLINE.match(nonblank[1][1])
            allowed_plain_adornments = {"=", "-"}
            if (
                underline
                and nonblank[0][1].strip()
                and (rst or underline.group(1) in allowed_plain_adornments)
            ):
                heading_title = nonblank[0][1].strip()
                heading_level = _RST_LEVELS.index(underline.group(1)) + 1
        if rst and len(nonblank) >= 3:
            overline = _RST_UNDERLINE.match(nonblank[0][1])
            underline = _RST_UNDERLINE.match(nonblank[2][1])
            if (
                overline
                and underline
                and overline.group(1) == underline.group(1)
                and nonblank[1][1].strip()
            ):
                heading_title = nonblank[1][1].strip()
                heading_level = _RST_LEVELS.index(overline.group(1)) + 1
        if heading_title is not None:
            heading_levels[heading_level - 1:] = [heading_title]
            if heading_level == 1:
                top_section += 1
            block_heading = tuple(heading_levels)
            kind = "heading"
        raw = b"".join(item[0] for item in current)
        block = _Block(
            start_byte=current[0][2], end_byte=current[-1][2] + len(current[-1][0]),
            start_line=current[0][3], end_line=current[-1][3],
            heading_path=block_heading, top_section=top_section, kind=kind, data=raw,
        )
        current = []
        return block

    with path.open("rb") as stream:
        stream.seek(start_offset)
        byte_offset = start_offset
        for raw in stream:
            line_no += 1
            text = _decode_line(raw, path, byte_offset).rstrip("\r\n")
            current.append((raw, text, byte_offset, line_no))
            if not text.strip():
                block = emit()
                if block is not None:
                    yield block
            byte_offset += len(raw)
    block = emit()
    if block is not None:
        yield block
    stats["line_count"] = line_no


def _utf8_segments(data: bytes, maximum: int) -> Iterator[tuple[int, int]]:
    """Yield non-empty UTF-8-safe slices no larger than *maximum*."""
    start = 0
    while start < len(data):
        end = min(start + maximum, len(data))
        while end > start and end < len(data) and data[end] & 0b1100_0000 == 0b1000_0000:
            end -= 1
        if end == start:
            # maximum may be smaller than one encoded character. No valid
            # partition can satisfy that byte budget.
            raise TextChunkError("hard_budget is too small for a UTF-8 character in the source")
        yield start, end
        start = end


def _split_block(block: _Block, hard_budget: int) -> Iterable[_Block]:
    if block.size <= hard_budget:
        yield block
        return
    reason = "oversized_code_fence" if block.kind == "code_fence" else (
        "oversized_table" if b"|" in block.data else "oversized_block"
    )
    pieces = block.data.split(b"\n")
    raw_lines = [
        piece + (b"\n" if index < len(pieces) - 1 else b"")
        for index, piece in enumerate(pieces)
        if piece or index < len(pieces) - 1
    ]
    relative = 0
    line = block.start_line
    pending_data = bytearray()
    pending_relative = 0
    pending_start_line = line

    def emit_pending() -> _Block | None:
        nonlocal pending_data
        if not pending_data:
            return None
        data = bytes(pending_data)
        newline_count = data.count(b"\n")
        end_line = pending_start_line + newline_count - (1 if data.endswith(b"\n") else 0)
        result = _Block(
            block.start_byte + pending_relative,
            block.start_byte + pending_relative + len(data),
            pending_start_line, max(pending_start_line, end_line),
            block.heading_path, block.top_section, f"forced:{reason}", data,
        )
        pending_data = bytearray()
        return result

    for raw_line in raw_lines:
        if len(raw_line) > hard_budget:
            pending = emit_pending()
            if pending is not None:
                yield pending
            for start, end in _utf8_segments(raw_line, hard_budget):
                yield _Block(
                    block.start_byte + relative + start, block.start_byte + relative + end,
                    line, line, block.heading_path, block.top_section,
                    "forced:oversized_line", raw_line[start:end],
                )
        else:
            if pending_data and len(pending_data) + len(raw_line) > hard_budget:
                pending = emit_pending()
                if pending is not None:
                    yield pending
            if not pending_data:
                pending_relative = relative
                pending_start_line = line
            pending_data.extend(raw_line)
        relative += len(raw_line)
        if raw_line.endswith(b"\n"):
            line += 1
    pending = emit_pending()
    if pending is not None:
        yield pending


def _unit_id(content_hash: str, start_byte: int, end_byte: int) -> str:
    identity = f"{CHUNKER_VERSION}\0{content_hash}\0{start_byte}\0{end_byte}".encode("ascii")
    return f"unit-{hashlib.sha256(identity).hexdigest()}"


def _make_unit(blocks: list[_Block], content_hash: str) -> ChunkUnit:
    first, last = blocks[0], blocks[-1]
    forced_kinds = [block.kind.split(":", 1)[1] for block in blocks if block.kind.startswith("forced:")]
    size = last.end_byte - first.start_byte
    return ChunkUnit(
        unit_id=_unit_id(content_hash, first.start_byte, last.end_byte),
        heading_path=first.heading_path,
        start_line=first.start_line,
        end_line=last.end_line,
        start_byte=first.start_byte,
        end_byte=last.end_byte,
        size_bytes=size,
        forced_split=bool(forced_kinds),
        split_reason=forced_kinds[0] if forced_kinds else None,
        _source_hash=content_hash,
    )


def _pack_blocks(
    blocks: Iterable[_Block], content_hash: str, target_budget: int, hard_budget: int
) -> tuple[ChunkUnit, ...]:
    units: list[ChunkUnit] = []
    pending: list[_Block] = []
    pending_size = 0
    pending_top: int | None = None
    pending_heading: tuple[str, ...] | None = None

    def flush() -> None:
        nonlocal pending, pending_size, pending_top, pending_heading
        if pending:
            units.append(_make_unit(pending, content_hash))
        pending, pending_size, pending_top, pending_heading = [], 0, None, None

    for original in blocks:
        for block in _split_block(original, hard_budget):
            crosses_top_section = (
                pending_top is not None
                and block.top_section != pending_top
                and block.top_section > 0
                and pending_top > 0
            )
            crosses_heading = pending_heading is not None and block.heading_path != pending_heading
            if pending and (
                pending_size + block.size > target_budget
                or crosses_top_section
                or crosses_heading
            ):
                flush()
            # A natural block between target and hard is a valid unit. A forced
            # piece is kept isolated so its warning remains unambiguous.
            if block.size > target_budget or block.kind.startswith("forced:"):
                flush()
                units.append(_make_unit([block], content_hash))
                continue
            if not pending:
                pending_top = block.top_section
                pending_heading = block.heading_path
            pending.append(block)
            pending_size += block.size
    flush()
    return tuple(units)


def _validate_plan(plan: ChunkPlan, *, coverage_start: int) -> None:
    cursor = coverage_start
    for unit in plan.units:
        if unit.start_byte != cursor:
            raise AssertionError("chunk ranges contain a gap or overlap")
        if unit.end_byte <= unit.start_byte or unit.size_bytes != unit.end_byte - unit.start_byte:
            raise AssertionError("invalid chunk byte range")
        if unit.size_bytes > plan.hard_budget:
            raise AssertionError("chunk exceeds hard budget")
        if unit.start_line < 1 or unit.end_line < unit.start_line:
            raise AssertionError("invalid chunk line range")
        cursor = unit.end_byte
    if cursor != plan.size_bytes:
        raise AssertionError("chunk ranges do not cover the source")


def validate_chunk_plan(plan: ChunkPlan) -> None:
    """Validate the serialized V1 plan invariants without reading its source."""
    if plan.chunk_plan_version != CHUNK_PLAN_VERSION:
        raise TextChunkError(f"unsupported chunk plan version: {plan.chunk_plan_version}")
    if plan.chunker_version != CHUNKER_VERSION:
        raise TextChunkError(f"unsupported chunker version: {plan.chunker_version}")
    if not plan.content_hash.startswith("sha256:"):
        raise TextChunkError("chunk plan source hash must use the sha256: prefix")
    _validate_budgets(
        plan.target_budget, plan.hard_budget,
        allow_unsafe_hard_budget=plan.hard_budget > MAX_SAFE_HARD_BUDGET,
    )
    coverage_start = 3 if plan.encoding == "utf-8-sig" else 0
    try:
        _validate_plan(plan, coverage_start=coverage_start)
    except AssertionError as exc:
        raise TextChunkError(str(exc)) from exc
    for unit in plan.units:
        if unit.unit_id != _unit_id(plan.content_hash, unit.start_byte, unit.end_byte):
            raise TextChunkError(f"unstable or invalid unit id: {unit.unit_id}")


def plan_text_chunks(
    source: Path,
    *,
    target_budget: int = DEFAULT_TARGET_BUDGET,
    hard_budget: int = DEFAULT_HARD_BUDGET,
    allow_unsafe_hard_budget: bool = False,
) -> ChunkPlan:
    """Plan deterministic, exhaustive ranges for one supported UTF-8 file."""
    path = _validate_source(source)
    _validate_budgets(
        target_budget, hard_budget,
        allow_unsafe_hard_budget=allow_unsafe_hard_budget,
    )
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
            size += len(chunk)
    content_hash = f"sha256:{digest.hexdigest()}"
    with path.open("rb") as stream:
        prefix = stream.read(3)
    bom = prefix == codecs.BOM_UTF8
    start_offset = 3 if bom else 0

    warnings: list[str] = []
    stats = {"line_count": 0}
    if path.suffix.lower() in {".md", ".markdown", ".mdx"}:
        blocks = _markdown_blocks(path, start_offset, warnings, stats)
    else:
        blocks = _plain_or_rst_blocks(
            path, start_offset, rst=path.suffix.lower() == ".rst", stats=stats
        )
    units = _pack_blocks(blocks, content_hash, target_budget, hard_budget)
    plan = ChunkPlan(
        source_path=str(path), content_hash=content_hash, encoding="utf-8-sig" if bom else "utf-8",
        size_bytes=size, line_count=stats["line_count"], target_budget=target_budget,
        hard_budget=hard_budget, units=units, warnings=tuple(warnings),
    )
    _validate_plan(plan, coverage_start=start_offset)
    return plan


def read_text_chunk(source: Path, unit: ChunkUnit) -> str:
    """Verify the planned source version and decode exactly one chunk range."""
    path = _validate_source(source)
    if unit._source_hash is None:
        raise TextChunkError("chunk unit has no expected source hash")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    actual = f"sha256:{digest.hexdigest()}"
    if _normalise_hash(unit._source_hash) != actual:
        raise SourceChangedError(
            f"source hash changed after planning: expected {_normalise_hash(unit._source_hash)}, got {actual}"
        )
    if unit.start_byte < 0 or unit.end_byte <= unit.start_byte:
        raise TextChunkError("invalid chunk byte range")
    with path.open("rb") as stream:
        stream.seek(unit.start_byte)
        raw = stream.read(unit.end_byte - unit.start_byte)
    if len(raw) != unit.end_byte - unit.start_byte:
        raise TextChunkError("chunk range extends beyond the source")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TextChunkError("chunk range does not fall on UTF-8 boundaries") from exc


def unit_for_range(
    *, start_byte: int, end_byte: int, expected_hash: str,
    start_line: int = 1, end_line: int = 1,
    allow_unsafe_hard_budget: bool = False,
) -> ChunkUnit:
    """Construct a hash-bound unit for the low-level CLI range reader."""
    size = end_byte - start_byte
    if size > MAX_SAFE_HARD_BUDGET and not allow_unsafe_hard_budget:
        raise TextChunkError(
            f"requested range exceeds the documented safe maximum of "
            f"{MAX_SAFE_HARD_BUDGET} bytes; an explicit unsafe-budget override is required"
        )
    expected_hash = _normalise_hash(expected_hash)
    return ChunkUnit(
        unit_id=_unit_id(expected_hash, start_byte, end_byte), heading_path=(),
        start_line=start_line, end_line=end_line, start_byte=start_byte,
        end_byte=end_byte, size_bytes=size, _source_hash=expected_hash,
    )
