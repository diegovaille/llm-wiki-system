from datetime import date, datetime, timezone
from pathlib import Path

from wiki_system.review import ReviewItem, list_review_queue
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
from wiki_system.storage import write_staged


def _raw(artifact: str = "docs/foo.md", slug: str = "raw-foo") -> tuple[StagedFile, str]:
    sf = StagedFile(
        state=StagedState.RAW,
        origin=StagedFileOrigin.SYNC,
        created_at=datetime(2026, 4, 12, 14, 30, tzinfo=timezone.utc),
        created_by="post-spec-hook",
        source_artifact=artifact,
        trigger="post-spec",
        raw_body_mode=RawBodyMode.INLINE,
    )
    return sf, slug


def _proposed(id_: str = "lv-foo", slug: str = "prop-foo") -> tuple[StagedFile, str]:
    fm = PageFrontmatter(
        id=id_,
        title=id_.replace("-", " ").title(),
        summary="A summary.",
        type=PageType.SYSTEM,
        project="luminavine",
        domains=["pipeline"],
        status=PageStatus.ACTIVE,
        aliases=[],
        sources=["session:2026-04-12-x"],
        related=[],
        updated_at=date(2026, 4, 12),
        confidence=Confidence.HIGH,
    )
    sf = StagedFile(
        state=StagedState.PROPOSED,
        origin=StagedFileOrigin.CAPTURE,
        created_at=datetime(2026, 4, 12, 14, 35, tzinfo=timezone.utc),
        created_by="capture",
        proposed_action=ProposedAction.CREATE,
        target_page_id=None,
        canonical_page=CanonicalPageEmbed(frontmatter=fm, body="# Body\n"),
    )
    return sf, slug


def test_list_review_empty(wiki_root: Path):
    assert list_review_queue(wiki_root, "luminavine") == []


def test_list_review_returns_raw_first_then_proposed(wiki_root: Path):
    raw, raw_slug = _raw()
    write_staged(wiki_root, "luminavine", raw, "body", slug=raw_slug)
    prop, prop_slug = _proposed()
    write_staged(wiki_root, "luminavine", prop, "", slug=prop_slug)
    items = list_review_queue(wiki_root, "luminavine")
    assert len(items) == 2
    assert items[0].state == "raw"
    assert items[1].state == "proposed"


def test_raw_item_carries_source_artifact(wiki_root: Path):
    raw, slug = _raw(artifact="docs/bar.md")
    write_staged(wiki_root, "luminavine", raw, "body", slug=slug)
    items = list_review_queue(wiki_root, "luminavine")
    assert items[0].source_artifact == "docs/bar.md"
    assert items[0].trigger == "post-spec"
    assert items[0].raw_body_mode == "inline"
    assert items[0].proposed_action is None


def test_proposed_item_carries_canonical_page_metadata(wiki_root: Path):
    prop, slug = _proposed(id_="lv-story")
    write_staged(wiki_root, "luminavine", prop, "", slug=slug)
    items = list_review_queue(wiki_root, "luminavine")
    assert items[0].proposed_page_id == "lv-story"
    assert items[0].proposed_title == "Lv Story"
    assert items[0].proposed_action == "create"
    assert items[0].source_artifact is None


def test_list_review_excludes_archive(wiki_root: Path):
    archive_dir = wiki_root / "luminavine" / "staging" / ".archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    (archive_dir / "old.md").write_text("---\nstate: raw\n---\n")
    prop, slug = _proposed()
    write_staged(wiki_root, "luminavine", prop, "", slug=slug)
    items = list_review_queue(wiki_root, "luminavine")
    assert len(items) == 1
    assert items[0].state == "proposed"
