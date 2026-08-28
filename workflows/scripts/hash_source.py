#!/usr/bin/env python3
"""Print a stable SHA-256 fingerprint for one file or directory."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


CHUNK_SIZE = 1 << 20


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hash_directory(path: Path) -> str:
    """Hash file names and contents in a deterministic traversal order."""
    digest = hashlib.sha256()
    files = sorted(candidate for candidate in path.rglob("*") if candidate.is_file())
    for file_path in files:
        relative_path = file_path.relative_to(path).as_posix()
        digest.update(relative_path.encode("utf-8"))
        digest.update(hash_file(file_path).encode("ascii"))
    return digest.hexdigest()


def hash_source(path: Path) -> str:
    if path.is_dir():
        return hash_directory(path)
    if path.is_file():
        return hash_file(path)
    raise FileNotFoundError(f"source does not exist or is not a regular file: {path}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compute the wiki-ingest content hash for a file or directory."
    )
    parser.add_argument("source", type=Path)
    args = parser.parse_args()

    try:
        fingerprint = hash_source(args.source)
    except (OSError, ValueError) as error:
        parser.exit(1, f"hash_source.py: error: {error}\n")

    print(f"sha256:{fingerprint}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
