"""Unit tests for the shared `staging_write.write_proposed_staged_file` helper.

Integration coverage of the helper lives in `test_capture_submit.py`
(exercising the capture flow) and `test_bootstrap.py` (exercising the
bootstrap flow). These tests pin the helper's own contract:

- Accepts well-formed proposals and writes the staged file
- Propagates `upgraded_from` and `bootstrap_from` into the envelope
- Rejects malformed proposals via `StagingWriteError`
- Rejects proposals whose canonical_page.frontmatter is invalid
- Rejects proposals that violate the page identity invariant
"""
from __future__ import annotations

from pathlib import Path

import pytest

from wiki_system.schema import (
    BootstrapFrom,
    StagedFileOrigin,
    StagedState,
    UpgradedFrom,
)
from wiki_system.staging_write import (
    StagingWriteError,
    write_proposed_staged_file,
)


def _valid_proposal(**overrides):
    base = {
        "action": "create",
        "target_page_id": None,
        "rationale": "unit test",
        "canonical_page": {
            "frontmatter": {
                "id": "demo-foo",
                "title": "Demo Foo",
                "summary": "A summary.",
                "type": "system",
                "project": "demo",
                "domains": ["pipeline"],
                "status": "active",
                "aliases": [],
                "sources": ["session:2026-04-12-demo"],
                "related": [],
                "updated_at": "2026-04-12",
                "confidence": "high",
            },
            "body": "# Demo Foo\n\nBody.\n",
        },
    }
    base.update(overrides)
    return base


def test_write_proposed_staged_file_happy_path(wiki_root: Path):
    result = write_proposed_staged_file(
        wiki_root=wiki_root,
        project="demo",
        proposal=_valid_proposal(),
        origin=StagedFileOrigin.CAPTURE,
        created_by="capture",
    )
    assert result.path.exists()
    assert result.action == "create"
    assert result.proposed_page_id == "demo-foo"
    assert result.staged.state == StagedState.PROPOSED.value
    assert result.staged.origin == StagedFileOrigin.CAPTURE.value


def test_write_proposed_staged_file_with_upgraded_from(wiki_root: Path):
    uf = UpgradedFrom(
        raw_file="staging/some-raw.md",
        origin=StagedFileOrigin.SYNC,
        trigger="manual",
        source_artifact="docs/foo.md",
    )
    result = write_proposed_staged_file(
        wiki_root=wiki_root,
        project="demo",
        proposal=_valid_proposal(),
        origin=StagedFileOrigin.CAPTURE,
        created_by="capture",
        upgraded_from=uf,
    )
    assert result.staged.upgraded_from is not None
    assert result.staged.upgraded_from.source_artifact == "docs/foo.md"


def test_write_proposed_staged_file_with_bootstrap_from(wiki_root: Path):
    bf = BootstrapFrom(
        question_text="How does the story pipeline work?",
        question_source="seed",
        question_key="how-does-the-story-pipeline-work",
        question_line=1,
    )
    result = write_proposed_staged_file(
        wiki_root=wiki_root,
        project="demo",
        proposal=_valid_proposal(),
        origin=StagedFileOrigin.BOOTSTRAP,
        created_by="wiki bootstrap",
        bootstrap_from=bf,
    )
    assert result.staged.bootstrap_from is not None
    assert result.staged.bootstrap_from.question_source == "seed"
    assert result.staged.origin == StagedFileOrigin.BOOTSTRAP.value


def test_rejects_noop_action(wiki_root: Path):
    """The helper is for create/update only; callers handle noop themselves."""
    with pytest.raises(StagingWriteError, match="create.*update"):
        write_proposed_staged_file(
            wiki_root=wiki_root,
            project="demo",
            proposal=_valid_proposal(action="noop"),
            origin=StagedFileOrigin.CAPTURE,
            created_by="capture",
        )


def test_rejects_missing_action(wiki_root: Path):
    proposal = _valid_proposal()
    del proposal["action"]
    with pytest.raises(StagingWriteError):
        write_proposed_staged_file(
            wiki_root=wiki_root,
            project="demo",
            proposal=proposal,
            origin=StagedFileOrigin.CAPTURE,
            created_by="capture",
        )


def test_rejects_missing_canonical_page(wiki_root: Path):
    proposal = _valid_proposal()
    del proposal["canonical_page"]
    with pytest.raises(StagingWriteError, match="canonical_page"):
        write_proposed_staged_file(
            wiki_root=wiki_root,
            project="demo",
            proposal=proposal,
            origin=StagedFileOrigin.CAPTURE,
            created_by="capture",
        )


def test_rejects_canonical_page_missing_frontmatter(wiki_root: Path):
    proposal = _valid_proposal()
    proposal["canonical_page"] = {"body": "# Body\n"}
    with pytest.raises(StagingWriteError, match="frontmatter"):
        write_proposed_staged_file(
            wiki_root=wiki_root,
            project="demo",
            proposal=proposal,
            origin=StagedFileOrigin.CAPTURE,
            created_by="capture",
        )


def test_rejects_invalid_page_frontmatter(wiki_root: Path):
    """A bad id (not a slug) should bubble up from PageFrontmatter's validator."""
    proposal = _valid_proposal()
    proposal["canonical_page"]["frontmatter"]["id"] = "NotASlug"
    with pytest.raises(StagingWriteError, match="canonical_page schema invalid"):
        write_proposed_staged_file(
            wiki_root=wiki_root,
            project="demo",
            proposal=proposal,
            origin=StagedFileOrigin.CAPTURE,
            created_by="capture",
        )


def test_rejects_update_without_target_page_id(wiki_root: Path):
    """Page identity invariant: update requires non-null target_page_id."""
    proposal = _valid_proposal(action="update", target_page_id=None)
    with pytest.raises(StagingWriteError, match="target_page_id"):
        write_proposed_staged_file(
            wiki_root=wiki_root,
            project="demo",
            proposal=proposal,
            origin=StagedFileOrigin.CAPTURE,
            created_by="capture",
        )


def test_rejects_update_with_id_mismatch(wiki_root: Path):
    """Page identity invariant: target_page_id must equal canonical_page id."""
    proposal = _valid_proposal(action="update", target_page_id="demo-other")
    with pytest.raises(StagingWriteError, match="canonical_page.frontmatter.id"):
        write_proposed_staged_file(
            wiki_root=wiki_root,
            project="demo",
            proposal=proposal,
            origin=StagedFileOrigin.CAPTURE,
            created_by="capture",
        )


def test_rejects_bootstrap_from_with_non_bootstrap_origin(wiki_root: Path):
    """Schema rule: bootstrap_from is bootstrap-exclusive."""
    bf = BootstrapFrom(
        question_text="anything",
        question_source="ad-hoc",
        question_key="anything",
    )
    with pytest.raises(StagingWriteError, match="bootstrap_from"):
        write_proposed_staged_file(
            wiki_root=wiki_root,
            project="demo",
            proposal=_valid_proposal(),
            origin=StagedFileOrigin.CAPTURE,
            created_by="capture",
            bootstrap_from=bf,
        )
