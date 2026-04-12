"""Tests for `wiki_system.sync` — registering project artifacts as raw staged files."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from wiki_system.cli import main
from wiki_system.config import ProjectConfig, SyncConfig
from wiki_system.schema import StagedState
from wiki_system.storage import list_staged, read_staged
from wiki_system.sync import (
    _matches_path_filter,
    _normalize_path_filter,
    _slug_from_source,
    run_sync,
)


def _make_project(
    tmp_path: Path,
    name: str = "demo",
    source_globs: list[str] | None = None,
    files: dict[str, str] | None = None,
) -> ProjectConfig:
    """Build a ProjectConfig with a real repo populated with `files`.

    `files` is a map of repo-relative path → text content. Directories
    are auto-created. The repo_path defaults to tmp_path / "repo".
    """
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    for rel, content in (files or {}).items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return ProjectConfig(
        name=name,
        repo_path=str(repo),
        source_globs=source_globs or ["docs/**/*.md"],
    )


def _sync_cfg(threshold_bytes: int = 65536) -> SyncConfig:
    return SyncConfig(inline_threshold_bytes=threshold_bytes)


def _setup_cli_config(
    tmp_path: Path, wiki_root: Path, repo: Path, source_globs: list[str]
) -> Path:
    repo.mkdir(parents=True, exist_ok=True)
    cfg_path = tmp_path / "wiki.config.toml"
    globs_toml = ", ".join(f'"{g}"' for g in source_globs)
    cfg_path.write_text(
        f"""
[wiki]
root = "{wiki_root}"

[execution]
mode = "agent"

[execution.agent]
runtime = "claude-code"
model_hint = "opus"

[[projects]]
name = "demo"
repo_path = "{repo}"
source_globs = [{globs_toml}]
"""
    )
    return cfg_path


# ---------- unit: path filter normalization ----------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("docs/technical", "docs/technical"),
        ("docs/technical/", "docs/technical"),
        ("./docs/technical/", "docs/technical"),
        ("/docs/technical/", "docs/technical"),
        ("  docs/technical  ", "docs/technical"),
        ("", None),
        (None, None),
    ],
)
def test_normalize_path_filter(raw: str | None, expected: str | None):
    assert _normalize_path_filter(raw) == expected


@pytest.mark.parametrize(
    "source,filt,expected",
    [
        ("docs/technical/a.md", None, True),
        ("docs/technical/a.md", "docs/technical", True),
        ("docs/technical/nested/b.md", "docs/technical", True),
        ("docs/other/c.md", "docs/technical", False),
        ("docs/technical/a.md", "docs/technical/a.md", True),
        ("docs/technical/a.md", "docs/technical-plus", False),
        ("docs/technical", "docs/technical", True),
    ],
)
def test_matches_path_filter(source: str, filt: str | None, expected: bool):
    assert _matches_path_filter(source, filt) is expected


# ---------- unit: slug derivation ----------


def test_slug_from_source_preserves_directory_structure():
    slug = _slug_from_source("docs/technical/pipeline-architecture.md")
    assert slug == "docs-technical-pipeline-architecture"


def test_slug_from_source_is_unique_for_same_basename_in_different_dirs():
    a = _slug_from_source("docs/a/readme.md")
    b = _slug_from_source("docs/b/readme.md")
    assert a != b


# ---------- integration: run_sync behavior ----------


def test_sync_creates_one_raw_file_per_matched_artifact(
    wiki_root: Path, tmp_path: Path
):
    project_cfg = _make_project(
        tmp_path,
        source_globs=["docs/**/*.md"],
        files={
            "docs/technical/pipeline.md": "# Pipeline\n\nBody.\n",
            "docs/technical/data-model.md": "# Data Model\n\nBody.\n",
            "docs/runbook.md": "# Runbook\n\nBody.\n",
        },
    )
    result = run_sync(
        wiki_root=wiki_root, project_cfg=project_cfg, sync_cfg=_sync_cfg()
    )
    assert len(result.created) == 3
    assert result.skipped == []
    assert result.removed == []
    # All three raw staged files exist and parse as state: raw
    for path in result.created:
        staged, _body = read_staged(path)
        assert staged.state == StagedState.RAW.value
        assert staged.origin == "sync"
        assert staged.created_by == "wiki sync"


def test_sync_inline_vs_pointer_mode_respects_threshold(
    wiki_root: Path, tmp_path: Path
):
    # Threshold = 100 bytes. Small file inlines, large file becomes pointer.
    project_cfg = _make_project(
        tmp_path,
        files={
            "docs/small.md": "# Tiny\n",
            "docs/large.md": "# Big\n\n" + ("X" * 200) + "\n",
        },
    )
    result = run_sync(
        wiki_root=wiki_root,
        project_cfg=project_cfg,
        sync_cfg=_sync_cfg(threshold_bytes=100),
    )
    assert len(result.created) == 2
    by_source: dict[str, Path] = {}
    for path in result.created:
        staged, body = read_staged(path)
        by_source[staged.source_artifact] = path
        if staged.source_artifact == "docs/small.md":
            assert staged.raw_body_mode == "inline"
            assert "Tiny" in body
        else:
            assert staged.source_artifact == "docs/large.md"
            assert staged.raw_body_mode == "pointer"
            assert body == ""


def test_sync_skips_existing_raw_files_by_default(
    wiki_root: Path, tmp_path: Path
):
    project_cfg = _make_project(
        tmp_path,
        files={"docs/a.md": "# A\n", "docs/b.md": "# B\n"},
    )
    first = run_sync(
        wiki_root=wiki_root, project_cfg=project_cfg, sync_cfg=_sync_cfg()
    )
    assert len(first.created) == 2
    # Second run: no new files, both skipped
    second = run_sync(
        wiki_root=wiki_root, project_cfg=project_cfg, sync_cfg=_sync_cfg()
    )
    assert second.created == []
    assert set(second.skipped) == {"docs/a.md", "docs/b.md"}
    assert second.removed == []


def test_sync_force_replaces_existing_raw_files(
    wiki_root: Path, tmp_path: Path
):
    project_cfg = _make_project(
        tmp_path, files={"docs/a.md": "# A\n"}
    )
    first = run_sync(
        wiki_root=wiki_root, project_cfg=project_cfg, sync_cfg=_sync_cfg()
    )
    original_path = first.created[0]
    # Edit the source file, force re-sync
    (Path(project_cfg.repo_path) / "docs/a.md").write_text("# A updated\n")
    second = run_sync(
        wiki_root=wiki_root,
        project_cfg=project_cfg,
        sync_cfg=_sync_cfg(),
        force=True,
    )
    assert len(second.removed) == 1
    assert len(second.created) == 1
    assert second.skipped == []
    # New file has updated content
    _, new_body = read_staged(second.created[0])
    assert "updated" in new_body


def test_sync_path_filter_scopes_candidates(wiki_root: Path, tmp_path: Path):
    project_cfg = _make_project(
        tmp_path,
        files={
            "docs/technical/a.md": "# A\n",
            "docs/technical/b.md": "# B\n",
            "docs/other/c.md": "# C\n",
            "docs/runbook.md": "# R\n",
        },
    )
    result = run_sync(
        wiki_root=wiki_root,
        project_cfg=project_cfg,
        sync_cfg=_sync_cfg(),
        path_filter="docs/technical/",
    )
    sources = {read_staged(p)[0].source_artifact for p in result.created}
    assert sources == {"docs/technical/a.md", "docs/technical/b.md"}


def test_sync_force_with_path_preserves_unrelated_raw_files(
    wiki_root: Path, tmp_path: Path
):
    project_cfg = _make_project(
        tmp_path,
        files={
            "docs/technical/a.md": "# A\n",
            "docs/other/c.md": "# C\n",
        },
    )
    # Initial full sync creates two raw files
    initial = run_sync(
        wiki_root=wiki_root, project_cfg=project_cfg, sync_cfg=_sync_cfg()
    )
    assert len(initial.created) == 2
    other_path = next(
        p
        for p in initial.created
        if read_staged(p)[0].source_artifact == "docs/other/c.md"
    )
    # Scoped force on docs/technical/ — should delete only the technical raw,
    # preserve the other raw untouched.
    result = run_sync(
        wiki_root=wiki_root,
        project_cfg=project_cfg,
        sync_cfg=_sync_cfg(),
        path_filter="docs/technical/",
        force=True,
    )
    removed_sources = {read_staged_or_none(p) for p in result.removed}
    # The `docs/other/c.md` raw file must still exist on disk
    assert other_path.exists()
    # Only the technical file was removed then re-created
    assert len(result.removed) == 1
    assert len(result.created) == 1
    assert read_staged(result.created[0])[0].source_artifact == "docs/technical/a.md"


def read_staged_or_none(path: Path):
    try:
        return read_staged(path)[0].source_artifact
    except Exception:
        return None


def test_sync_warns_on_binary_artifact(wiki_root: Path, tmp_path: Path):
    project_cfg = _make_project(tmp_path, files={"docs/a.md": "# A\n"})
    # Drop a binary file matching the glob
    (Path(project_cfg.repo_path) / "docs" / "blob.md").write_bytes(
        b"\x00\x01\x02\x03\xff\xfe"
    )
    result = run_sync(
        wiki_root=wiki_root, project_cfg=project_cfg, sync_cfg=_sync_cfg()
    )
    # One created (the valid file), one warning (the binary)
    assert len(result.created) == 1
    assert any("blob.md" in w for w in result.warnings)
    assert any("not valid UTF-8" in w for w in result.warnings)


def test_sync_trigger_is_recorded_on_raw_files(
    wiki_root: Path, tmp_path: Path
):
    project_cfg = _make_project(tmp_path, files={"docs/a.md": "# A\n"})
    result = run_sync(
        wiki_root=wiki_root,
        project_cfg=project_cfg,
        sync_cfg=_sync_cfg(),
        trigger="post-spec",
    )
    staged, _ = read_staged(result.created[0])
    assert staged.trigger == "post-spec"


def test_sync_handles_multiple_source_globs(wiki_root: Path, tmp_path: Path):
    project_cfg = _make_project(
        tmp_path,
        source_globs=["docs/**/*.md", "prompts/**/*.md"],
        files={
            "docs/a.md": "# A\n",
            "prompts/b.md": "# B\n",
            "other/c.md": "# ignored — not in any glob\n",
        },
    )
    result = run_sync(
        wiki_root=wiki_root, project_cfg=project_cfg, sync_cfg=_sync_cfg()
    )
    sources = {read_staged(p)[0].source_artifact for p in result.created}
    assert sources == {"docs/a.md", "prompts/b.md"}


# ---------- CLI ----------


def test_cli_sync_creates_raw_files_and_emits_json(
    wiki_root: Path, tmp_path: Path
):
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "a.md").write_text("# A\n")
    (repo / "docs" / "b.md").write_text("# B\n")
    cfg_path = _setup_cli_config(tmp_path, wiki_root, repo, ["docs/**/*.md"])
    runner = CliRunner()
    r = runner.invoke(
        main, ["--config", str(cfg_path), "sync", "demo"]
    )
    assert r.exit_code == 0, (r.stdout, r.stderr)
    payload = json.loads(r.stdout)
    assert len(payload["created"]) == 2
    assert payload["skipped"] == []
    assert payload["removed"] == []
    assert payload["warnings"] == []


def test_cli_sync_path_and_force_flags(wiki_root: Path, tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "docs/technical").mkdir(parents=True)
    (repo / "docs/other").mkdir(parents=True)
    (repo / "docs/technical" / "a.md").write_text("# A\n")
    (repo / "docs/other" / "c.md").write_text("# C\n")
    cfg_path = _setup_cli_config(tmp_path, wiki_root, repo, ["docs/**/*.md"])
    runner = CliRunner()
    # First pass: sync everything
    r1 = runner.invoke(main, ["--config", str(cfg_path), "sync", "demo"])
    assert r1.exit_code == 0
    # Second pass: scoped --force on docs/technical/
    r2 = runner.invoke(
        main,
        [
            "--config",
            str(cfg_path),
            "sync",
            "demo",
            "--path",
            "docs/technical/",
            "--force",
        ],
    )
    assert r2.exit_code == 0, (r2.stdout, r2.stderr)
    payload = json.loads(r2.stdout)
    # Exactly one file removed and one created (the technical one)
    assert len(payload["removed"]) == 1
    assert len(payload["created"]) == 1
    assert "technical" in payload["created"][0]
    # The docs/other raw file survived — confirm by listing staging
    all_staged = list_staged(wiki_root, "demo")
    other_still_there = any(
        read_staged(p)[0].source_artifact == "docs/other/c.md"
        for p in all_staged
    )
    assert other_still_there
