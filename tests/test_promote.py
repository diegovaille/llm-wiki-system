import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from wiki_system.promote import PromoteRejection, PromoteResult, promote
from wiki_system.schema import (
    CanonicalPageEmbed,
    Confidence,
    PageFrontmatter,
    PageStatus,
    PageType,
    ProposedAction,
    RawBodyMode,
    StagedFile,
    StagedFileOrigin,
    StagedState,
)
from wiki_system.storage import list_pages, read_page, write_page, write_staged


def _fm(id_: str = "demo-foo") -> PageFrontmatter:
    return PageFrontmatter(
        id=id_,
        title=id_.replace("-", " ").title(),
        summary="",
        type=PageType.SYSTEM,
        project="demo",
        domains=["pipeline"],
        status=PageStatus.ACTIVE,
        aliases=[],
        sources=["session:2026-04-12-x"],
        related=[],
        updated_at=date(2026, 4, 12),
        confidence=Confidence.HIGH,
    )


def _proposed_create(fm: PageFrontmatter, body: str = "# Body\n") -> StagedFile:
    return StagedFile(
        state=StagedState.PROPOSED,
        origin=StagedFileOrigin.CAPTURE,
        created_at=datetime(2026, 4, 12, 14, 35, tzinfo=timezone.utc),
        created_by="capture",
        proposed_action=ProposedAction.CREATE,
        target_page_id=None,
        canonical_page=CanonicalPageEmbed(frontmatter=fm, body=body),
    )


def _proposed_update(existing_id: str, fm: PageFrontmatter, body: str = "# Updated\n") -> StagedFile:
    return StagedFile(
        state=StagedState.PROPOSED,
        origin=StagedFileOrigin.CAPTURE,
        created_at=datetime(2026, 4, 12, 14, 35, tzinfo=timezone.utc),
        created_by="capture",
        proposed_action=ProposedAction.UPDATE,
        target_page_id=existing_id,
        canonical_page=CanonicalPageEmbed(frontmatter=fm, body=body),
    )


def test_promote_create_dry_run(wiki_root: Path):
    fm = _fm()
    sf = _proposed_create(fm)
    staged_path = write_staged(wiki_root, "demo", sf, "", slug="create-foo")
    result = promote(wiki_root, "demo", staged_path, apply=False)
    assert isinstance(result, PromoteResult)
    assert result.action == "create"
    assert result.page_id == "demo-foo"
    assert result.dry_run is True
    # No page written
    assert list_pages(wiki_root, "demo") == []
    # Staged file still present
    assert staged_path.exists()


def test_promote_create_apply(wiki_root: Path):
    fm = _fm()
    sf = _proposed_create(fm)
    staged_path = write_staged(wiki_root, "demo", sf, "", slug="create-foo")
    result = promote(wiki_root, "demo", staged_path, apply=True)
    assert result.action == "create"
    assert result.dry_run is False
    pages = list_pages(wiki_root, "demo")
    assert len(pages) == 1
    loaded_fm, _ = read_page(pages[0])
    assert loaded_fm.id == "demo-foo"
    # Staged file archived
    assert not staged_path.exists()
    archive = wiki_root / "demo" / "staging" / ".archive" / staged_path.name
    assert archive.exists()
    # Manifest updated with a structured entry
    manifest = (wiki_root / "demo" / "sources" / "manifest.jsonl").read_text()
    entries = [json.loads(line) for line in manifest.splitlines() if line]
    assert any(
        e["id"] == "demo-foo"
        and e["action"] == "create"
        and e["from_staged"] == staged_path.name
        for e in entries
    )


def test_promote_rejects_state_raw(wiki_root: Path):
    raw = StagedFile(
        state=StagedState.RAW,
        origin=StagedFileOrigin.SYNC,
        created_at=datetime(2026, 4, 12, tzinfo=timezone.utc),
        created_by="post-spec-hook",
        source_artifact="docs/foo.md",
        trigger="post-spec",
        raw_body_mode=RawBodyMode.INLINE,
    )
    staged_path = write_staged(wiki_root, "demo", raw, "artifact", slug="raw-foo")
    with pytest.raises(PromoteRejection) as excinfo:
        promote(wiki_root, "demo", staged_path, apply=True)
    assert "raw" in str(excinfo.value)


def test_promote_update_applies_diff(wiki_root: Path):
    # Existing canonical page
    fm0 = _fm()
    write_page(wiki_root, "demo", fm0, "# Foo\n\nOld body.\n")
    # Proposed update
    fm1 = _fm()  # same id
    sf = _proposed_update("demo-foo", fm1, body="# Foo\n\nNew body.\n")
    staged_path = write_staged(wiki_root, "demo", sf, "", slug="update-foo")
    result = promote(wiki_root, "demo", staged_path, apply=True)
    assert result.action == "update"
    assert "+New body.\n" in result.diff
    assert "-Old body.\n" in result.diff
    pages = list_pages(wiki_root, "demo")
    assert len(pages) == 1
    _, body = read_page(pages[0])
    assert "New body" in body


def test_promote_rejects_create_when_id_collides(wiki_root: Path):
    # Existing page with id demo-foo
    fm0 = _fm()
    write_page(wiki_root, "demo", fm0, "# Foo\n")
    # Proposed create for same id
    fm1 = _fm()
    sf = _proposed_create(fm1)
    staged_path = write_staged(wiki_root, "demo", sf, "", slug="create-dup")
    with pytest.raises(PromoteRejection) as excinfo:
        promote(wiki_root, "demo", staged_path, apply=True)
    assert "collide" in str(excinfo.value).lower() or "exists" in str(excinfo.value).lower()


def test_promote_rejects_update_when_target_missing(wiki_root: Path):
    fm = _fm(id_="demo-missing")
    sf = _proposed_update("demo-missing", fm)
    staged_path = write_staged(wiki_root, "demo", sf, "", slug="update-missing")
    with pytest.raises(PromoteRejection) as excinfo:
        promote(wiki_root, "demo", staged_path, apply=True)
    assert "missing" in str(excinfo.value).lower() or "does not exist" in str(excinfo.value).lower()
