from datetime import datetime, timezone
from pathlib import Path

import pytest

from wiki_system.capture import prepare_capture, PromptPackage
from wiki_system.config import ProjectConfig
from wiki_system.schema import (
    Confidence,
    PageFrontmatter,
    PageStatus,
    PageType,
    RawBodyMode,
    StagedFile,
    StagedFileOrigin,
    StagedState,
)
from wiki_system.storage import write_staged


def _raw(mode: RawBodyMode) -> StagedFile:
    return StagedFile(
        state=StagedState.RAW,
        origin=StagedFileOrigin.SYNC,
        created_at=datetime(2026, 4, 12, 14, 30, tzinfo=timezone.utc),
        created_by="post-spec-hook",
        source_artifact="docs/foo.md",
        trigger="post-spec",
        raw_body_mode=mode,
    )


def test_prepare_session_origin(wiki_root: Path, tmp_path: Path):
    project_cfg = ProjectConfig(
        name="luminavine", repo_path=str(tmp_path / "repo"), source_globs=[]
    )
    (tmp_path / "repo").mkdir()
    pkg = prepare_capture(
        wiki_root,
        project_cfg,
        session_notes="I decided to split the pipeline into three stages.",
        from_staged=None,
    )
    assert isinstance(pkg, PromptPackage)
    assert "three stages" in pkg.context
    assert "session-origin" in pkg.instructions


def test_prepare_from_staged_inline_uses_body(wiki_root: Path, tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "foo.md").write_text("SOURCE ARTIFACT CONTENT")
    project_cfg = ProjectConfig(
        name="luminavine", repo_path=str(repo), source_globs=[]
    )
    sf = _raw(RawBodyMode.INLINE)
    staged_path = write_staged(wiki_root, "luminavine", sf, "INLINE BODY", slug="inline")
    pkg = prepare_capture(
        wiki_root, project_cfg, session_notes=None, from_staged=staged_path
    )
    assert "INLINE BODY" in pkg.context
    assert "SOURCE ARTIFACT CONTENT" not in pkg.context


def test_prepare_from_staged_pointer_reads_source_artifact(
    wiki_root: Path, tmp_path: Path
):
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "foo.md").write_text("SOURCE ARTIFACT CONTENT")
    project_cfg = ProjectConfig(
        name="luminavine", repo_path=str(repo), source_globs=[]
    )
    sf = _raw(RawBodyMode.POINTER)
    staged_path = write_staged(wiki_root, "luminavine", sf, "", slug="pointer")
    pkg = prepare_capture(
        wiki_root, project_cfg, session_notes=None, from_staged=staged_path
    )
    assert "SOURCE ARTIFACT CONTENT" in pkg.context


def test_prepare_from_staged_pointer_missing_artifact_raises(
    wiki_root: Path, tmp_path: Path
):
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    # no docs/foo.md created
    project_cfg = ProjectConfig(
        name="luminavine", repo_path=str(repo), source_globs=[]
    )
    sf = _raw(RawBodyMode.POINTER)
    staged_path = write_staged(wiki_root, "luminavine", sf, "", slug="pointer-missing")
    with pytest.raises(FileNotFoundError, match="cannot dereference"):
        prepare_capture(
            wiki_root, project_cfg, session_notes=None, from_staged=staged_path
        )


def test_prepare_from_staged_rejects_non_raw_state(wiki_root: Path, tmp_path: Path):
    from wiki_system.schema import CanonicalPageEmbed, ProposedAction
    from datetime import date

    repo = tmp_path / "repo"
    repo.mkdir()
    project_cfg = ProjectConfig(
        name="luminavine", repo_path=str(repo), source_globs=[]
    )
    # Write a state: proposed staged file, then try to prepare_capture against it.
    fm = PageFrontmatter(
        id="lv-foo",
        title="Foo",
        summary="",
        type=PageType.SYSTEM,
        project="luminavine",
        domains=[],
        status=PageStatus.ACTIVE,
        aliases=[],
        sources=["session:2026-04-12-x"],
        related=[],
        updated_at=date(2026, 4, 12),
        confidence=Confidence.HIGH,
    )
    proposed = StagedFile(
        state=StagedState.PROPOSED,
        origin=StagedFileOrigin.CAPTURE,
        created_at=datetime(2026, 4, 12, 14, 35, tzinfo=timezone.utc),
        created_by="capture",
        proposed_action=ProposedAction.CREATE,
        target_page_id=None,
        canonical_page=CanonicalPageEmbed(frontmatter=fm, body="# Foo\n"),
    )
    staged_path = write_staged(wiki_root, "luminavine", proposed, "", slug="not-raw")
    with pytest.raises(ValueError, match="state: raw"):
        prepare_capture(
            wiki_root, project_cfg, session_notes=None, from_staged=staged_path
        )


def test_prepare_package_carries_schema_and_allowed_actions(
    wiki_root: Path, tmp_path: Path
):
    project_cfg = ProjectConfig(
        name="luminavine", repo_path=str(tmp_path), source_globs=[]
    )
    pkg = prepare_capture(
        wiki_root, project_cfg, session_notes="note", from_staged=None
    )
    assert "session-origin" in pkg.instructions
    assert set(pkg.allowed_actions) == {"noop", "update", "create"}
    assert "PageFrontmatter" in pkg.schema or "frontmatter" in pkg.schema
