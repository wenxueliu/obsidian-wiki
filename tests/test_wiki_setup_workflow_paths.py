from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    return subprocess.run(
        [sys.executable, "-m", "obsidian_wiki", *args],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_setup_workflows_do_not_use_cac_relative_script_paths() -> None:
    for name in ("wiki-setup.yaml", "wiki-setup-contract.yaml"):
        workflow = (ROOT / "workflows" / name).read_text(encoding="utf-8")
        assert ".cac/ralph-flow" not in workflow
        assert "python3 -m obsidian_wiki" in workflow


def test_setup_contract_wrapper_resolves_bundled_resources_from_any_cwd(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    core = run_cli(
        "wiki-setup-contract-build",
        "core",
        "--output-dir",
        str(artifacts),
        cwd=elsewhere,
    )
    assert core.returncode == 0, core.stderr
    final = run_cli(
        "wiki-setup-contract-build",
        "finalize",
        "--output-dir",
        str(artifacts),
        cwd=elsewhere,
    )
    assert final.returncode == 0, final.stderr
    assert (artifacts / "setup-contract.json").is_file()
    contract = json.loads((artifacts / "setup-contract.json").read_text(encoding="utf-8"))
    assert contract["config_defaults"][
        "WIKI_FOLDER_INGEST_MAX_EXTRACTION_WORKERS"
    ] == 4
    assert contract["layout"]["available"]["default"]["profile"]["contract"][
        "name"
    ] == "default"


def test_layout_apply_wrapper_resolves_bundled_resources_from_any_cwd(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    artifacts = tmp_path / "artifacts"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    result = run_cli(
        "wiki-layout-apply",
        "--layout",
        "default",
        "--vault",
        str(vault),
        "--output-dir",
        str(artifacts),
        cwd=elsewhere,
    )

    assert result.returncode == 0, result.stderr
    marker = json.loads((vault / "_meta" / "layout.json").read_text())
    assert marker["name"] == "default"
    assert marker["profile_sha256"].startswith("sha256:")
    assert (artifacts / "layout-apply-report.json").is_file()


def test_layout_apply_can_refresh_same_pack_profile_hash(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    initial_artifacts = tmp_path / "initial-artifacts"
    refresh_artifacts = tmp_path / "refresh-artifacts"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    initial = run_cli(
        "wiki-layout-apply",
        "--layout",
        "default",
        "--vault",
        str(vault),
        "--output-dir",
        str(initial_artifacts),
        cwd=elsewhere,
    )
    assert initial.returncode == 0, initial.stderr

    marker_path = vault / "_meta" / "layout.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["profile_sha256"] = "sha256:stale"
    marker_path.write_text(json.dumps(marker), encoding="utf-8")

    refreshed = run_cli(
        "wiki-layout-apply",
        "--layout",
        "default",
        "--vault",
        str(vault),
        "--output-dir",
        str(refresh_artifacts),
        "--refresh-layout-marker",
        cwd=elsewhere,
    )

    assert refreshed.returncode == 0, refreshed.stderr
    refreshed_marker = json.loads(marker_path.read_text(encoding="utf-8"))
    assert refreshed_marker["profile_sha256"] != "sha256:stale"
    report = json.loads(
        (refresh_artifacts / "layout-apply-report.json").read_text(encoding="utf-8")
    )
    assert report["refreshed_files"] == ["_meta/layout.json"]
