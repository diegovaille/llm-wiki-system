from datetime import datetime, timezone
from pathlib import Path

import pytest

from wiki_system.capture import SubmitRejection, submit_capture
from wiki_system.schema import RawBodyMode, StagedFile, StagedFileOrigin, StagedState
from wiki_system.storage import list_staged, read_staged, write_staged


def _valid_proposal(action: str = "create", target: str | None = None) -> dict:
    return {
        "action": action,
        "target_page_id": target,
        "rationale": "Because test.",
        "canonical_page": {
            "frontmatter": {
                "id": "demo-foo",
                "title": "Foo",
                "summary": "Summary",
                "type": "system",
                "project": "demo",
                "domains": ["pipeline"],
                "status": "active",
                "aliases": [],
                "sources": ["session:2026-04-12-foo"],
                "related": [],
                "updated_at": "2026-04-12",
                "confidence": "high",
            },
            "body": "# Foo\n\nBody here.\n",
        },
    }


def test_submit_session_origin_create_writes_proposed(wiki_root: Path):
    result = submit_capture(
        wiki_root,
        project="demo",
        proposal=_valid_proposal(),
        from_staged=None,
    )
    assert result.action == "create"
    staged = list_staged(wiki_root, "demo")
    assert len(staged) == 1
    sf, _ = read_staged(staged[0])
    assert sf.state == "proposed"
    assert sf.origin == "capture"
    assert sf.canonical_page.frontmatter.id == "demo-foo"
    assert any(s.startswith("session:") for s in sf.canonical_page.frontmatter.sources)


def test_submit_session_origin_requires_session_source(wiki_root: Path):
    prop = _valid_proposal()
    prop["canonical_page"]["frontmatter"]["sources"] = ["docs/random.md"]
    with pytest.raises(SubmitRejection, match="session:"):
        submit_capture(
            wiki_root, project="demo", proposal=prop, from_staged=None
        )


def test_submit_noop_writes_nothing(wiki_root: Path):
    result = submit_capture(
        wiki_root,
        project="demo",
        proposal={"action": "noop", "rationale": "nothing worth capturing"},
        from_staged=None,
    )
    assert result.action == "noop"
    assert list_staged(wiki_root, "demo") == []


def test_submit_invalid_proposal_raises(wiki_root: Path):
    with pytest.raises(SubmitRejection):
        submit_capture(
            wiki_root,
            project="demo",
            proposal={"action": "create"},  # missing canonical_page
            from_staged=None,
        )


def test_submit_from_staged_upgrades_raw(wiki_root: Path):
    raw = StagedFile(
        state=StagedState.RAW,
        origin=StagedFileOrigin.SYNC,
        created_at=datetime(2026, 4, 12, tzinfo=timezone.utc),
        created_by="post-spec-hook",
        source_artifact="docs/foo.md",
        trigger="post-spec",
        raw_body_mode=RawBodyMode.INLINE,
    )
    raw_path = write_staged(wiki_root, "demo", raw, "ARTIFACT", slug="raw-foo")
    prop = _valid_proposal()
    prop["canonical_page"]["frontmatter"]["sources"] = ["docs/foo.md"]
    result = submit_capture(
        wiki_root, project="demo", proposal=prop, from_staged=raw_path
    )
    assert result.action == "create"
    staged = list_staged(wiki_root, "demo")
    # Raw path gone, one proposed file in its place
    assert not raw_path.exists()
    assert len(staged) == 1
    sf, _ = read_staged(staged[0])
    assert sf.state == "proposed"
    assert sf.upgraded_from is not None
    assert sf.upgraded_from.source_artifact == "docs/foo.md"


def test_submit_from_staged_upgrade_requires_source_artifact_in_sources(
    wiki_root: Path,
):
    raw = StagedFile(
        state=StagedState.RAW,
        origin=StagedFileOrigin.SYNC,
        created_at=datetime(2026, 4, 12, tzinfo=timezone.utc),
        created_by="post-spec-hook",
        source_artifact="docs/foo.md",
        trigger="post-spec",
        raw_body_mode=RawBodyMode.INLINE,
    )
    raw_path = write_staged(wiki_root, "demo", raw, "ART", slug="raw-foo2")
    prop = _valid_proposal()
    # sources lacks docs/foo.md
    prop["canonical_page"]["frontmatter"]["sources"] = ["docs/something-else.md"]
    with pytest.raises(SubmitRejection, match="docs/foo.md"):
        submit_capture(
            wiki_root, project="demo", proposal=prop, from_staged=raw_path
        )
