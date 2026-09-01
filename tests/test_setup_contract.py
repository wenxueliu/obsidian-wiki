from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "workflows" / "scripts"))

from build_setup_contract import normalize_text  # noqa: E402


def test_normalize_text_uses_lf_for_all_supported_newlines() -> None:
    assert normalize_text(b"one\r\ntwo\rthree\nfour") == "one\ntwo\nthree\nfour"


def test_lf_and_crlf_have_the_same_canonical_content() -> None:
    lf = normalize_text(b"# Title\n\nbody\n")
    crlf = normalize_text(b"# Title\r\n\r\nbody\r\n")

    assert lf == crlf
    assert lf.encode("utf-8") == crlf.encode("utf-8")
