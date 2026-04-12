from datetime import date, datetime, timezone
from pathlib import Path

import pytest

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
from wiki_system.storage import (
    append_manifest,
    list_pages,
    list_staged,
    read_page,
    read_staged,
    write_page,
    write_staged,
)


def _page(id_: str = "lv-foo") -> tuple[PageFrontmatter, str]:
    fm = PageFrontmatter(
        id=id_,
        title="Foo",
        summary="",
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
    return fm, "# Foo\n\nBody here.\n"


def test_write_and_read_page_round_trip(wiki_root: Path):
    fm, body = _page()
    path = write_page(wiki_root, "luminavine", fm, body)
    assert path.exists()
    loaded_fm, loaded_body = read_page(path)
    assert loaded_fm.id == fm.id
    assert loaded_fm.title == fm.title
    assert loaded_body.strip() == body.strip()


def test_list_pages_returns_all_markdown_in_pages_dir(wiki_root: Path):
    fm, body = _page(id_="lv-alpha")
    write_page(wiki_root, "luminavine", fm, body)
    fm2, body2 = _page(id_="lv-beta")
    write_page(wiki_root, "luminavine", fm2, body2)
    paths = list_pages(wiki_root, "luminavine")
    assert len(paths) == 2
    assert {p.stem for p in paths} == {"lv-alpha", "lv-beta"}


def test_write_and_read_staged_raw(wiki_root: Path):
    f = StagedFile(
        state=StagedState.RAW,
        origin=StagedFileOrigin.SYNC,
        created_at=datetime(2026, 4, 12, 14, 30, tzinfo=timezone.utc),
        created_by="post-spec-hook",
        source_artifact="docs/foo.md",
        trigger="post-spec",
        raw_body_mode=RawBodyMode.INLINE,
    )
    body = "Original artifact content."
    path = write_staged(wiki_root, "luminavine", f, body, slug="post-spec-foo")
    assert path.exists()
    loaded_f, loaded_body = read_staged(path)
    assert loaded_f.state == "raw"
    assert loaded_f.source_artifact == "docs/foo.md"
    assert loaded_body == body


def test_write_and_read_staged_proposed(wiki_root: Path):
    fm, page_body = _page()
    f = StagedFile(
        state=StagedState.PROPOSED,
        origin=StagedFileOrigin.CAPTURE,
        created_at=datetime(2026, 4, 12, 14, 35, tzinfo=timezone.utc),
        created_by="capture",
        proposed_action=ProposedAction.CREATE,
        target_page_id=None,
        canonical_page=CanonicalPageEmbed(frontmatter=fm, body=page_body),
    )
    path = write_staged(wiki_root, "luminavine", f, "", slug="capture-lv-foo")
    loaded_f, _ = read_staged(path)
    assert loaded_f.state == "proposed"
    assert loaded_f.canonical_page.frontmatter.id == "lv-foo"


def test_list_staged_returns_all(wiki_root: Path):
    f = StagedFile(
        state=StagedState.RAW,
        origin=StagedFileOrigin.SYNC,
        created_at=datetime(2026, 4, 12, tzinfo=timezone.utc),
        created_by="hook",
        source_artifact="docs/a.md",
        trigger="post-spec",
        raw_body_mode=RawBodyMode.INLINE,
    )
    write_staged(wiki_root, "luminavine", f, "content", slug="a")
    write_staged(wiki_root, "luminavine", f.model_copy(update={"source_artifact": "docs/b.md"}), "content", slug="b")
    paths = list_staged(wiki_root, "luminavine")
    assert len(paths) == 2


def test_append_manifest_jsonl(wiki_root: Path):
    append_manifest(
        wiki_root,
        "luminavine",
        {"id": "lv-foo", "action": "create", "promoted_at": "2026-04-12T15:00:00Z"},
    )
    append_manifest(
        wiki_root,
        "luminavine",
        {"id": "lv-bar", "action": "create", "promoted_at": "2026-04-12T15:01:00Z"},
    )
    manifest = (wiki_root / "luminavine" / "sources" / "manifest.jsonl").read_text()
    lines = manifest.strip().split("\n")
    assert len(lines) == 2
    assert '"id": "lv-foo"' in lines[0]
    assert '"id": "lv-bar"' in lines[1]


def test_read_page_rejects_unknown_fields(wiki_root: Path, tmp_path: Path):
    # Hand-written file with an unknown field
    bad = wiki_root / "luminavine" / "pages" / "bad.md"
    bad.write_text(
        """---
id: bad
title: Bad
summary: ""
type: system
project: luminavine
domains: []
status: active
aliases: []
sources: ["session:x-y"]
related: []
updated_at: 2026-04-12
confidence: high
extra_garbage: oops
---

Body
"""
    )
    with pytest.raises(Exception):
        read_page(bad)
