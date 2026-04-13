from datetime import datetime

import pytest
from pydantic import ValidationError

from wiki_system.schema import (
    CanonicalPageEmbed,
    PageFrontmatter,
    ProposedAction,
    RawBodyMode,
    StagedFile,
    StagedFileOrigin,
    StagedState,
)
from wiki_system._yaml import dumps, loads


def _valid_page_fm(**overrides):
    base = {
        "id": "demo-story-pipeline",
        "title": "Demo Story Pipeline",
        "summary": "End-to-end view.",
        "type": "system",
        "project": "demo",
        "domains": ["pipeline"],
        "status": "active",
        "aliases": [],
        "sources": ["session:2026-04-12-story-flow"],
        "related": [],
        "updated_at": "2026-04-12",
        "confidence": "high",
    }
    base.update(overrides)
    return base


def test_raw_inline_parses():
    data = {
        "state": "raw",
        "origin": "sync",
        "created_at": "2026-04-12T14:30:00Z",
        "created_by": "post-spec-hook",
        "source_artifact": "docs/foo.md",
        "trigger": "post-spec",
        "raw_body_mode": "inline",
    }
    f = StagedFile.model_validate(data)
    assert f.state == StagedState.RAW.value
    assert f.raw_body_mode == RawBodyMode.INLINE.value
    assert f.canonical_page is None


def test_raw_pointer_parses():
    data = {
        "state": "raw",
        "origin": "sync",
        "created_at": "2026-04-12T14:30:00Z",
        "created_by": "post-spec-hook",
        "source_artifact": "docs/big.md",
        "trigger": "post-spec",
        "raw_body_mode": "pointer",
    }
    f = StagedFile.model_validate(data)
    assert f.raw_body_mode == RawBodyMode.POINTER.value


def test_raw_requires_source_artifact():
    with pytest.raises(ValidationError):
        StagedFile.model_validate(
            {
                "state": "raw",
                "origin": "sync",
                "created_at": "2026-04-12T14:30:00Z",
                "created_by": "post-spec-hook",
                "trigger": "post-spec",
                "raw_body_mode": "inline",
            }
        )


def test_proposed_create_parses():
    data = {
        "state": "proposed",
        "origin": "capture",
        "created_at": "2026-04-12T14:35:00Z",
        "created_by": "capture",
        "proposed_action": "create",
        "target_page_id": None,
        "canonical_page": {
            "frontmatter": _valid_page_fm(),
            "body": "# Demo Story Pipeline\n\nBody content.",
        },
    }
    f = StagedFile.model_validate(data)
    assert f.state == StagedState.PROPOSED.value
    assert f.proposed_action == ProposedAction.CREATE.value
    assert f.target_page_id is None
    assert isinstance(f.canonical_page, CanonicalPageEmbed)
    assert f.canonical_page.frontmatter.id == "demo-story-pipeline"


def test_proposed_update_parses():
    data = {
        "state": "proposed",
        "origin": "capture",
        "created_at": "2026-04-12T14:35:00Z",
        "created_by": "capture",
        "proposed_action": "update",
        "target_page_id": "demo-story-pipeline",
        "canonical_page": {
            "frontmatter": _valid_page_fm(id="demo-story-pipeline"),
            "body": "# Demo Story Pipeline\n\nUpdated body.",
        },
    }
    f = StagedFile.model_validate(data)
    assert f.proposed_action == ProposedAction.UPDATE.value
    assert f.target_page_id == "demo-story-pipeline"


def test_round_trip_byte_identical():
    data = {
        "state": "proposed",
        "origin": "capture",
        "created_at": "2026-04-12T14:35:00Z",
        "created_by": "capture",
        "proposed_action": "create",
        "target_page_id": None,
        "canonical_page": {
            "frontmatter": _valid_page_fm(),
            "body": "# Title\n\nParagraph one.\n\nParagraph two.\n",
        },
    }
    f = StagedFile.model_validate(data)
    first = dumps(f.model_dump(mode="json"))
    second = dumps(loads(first))
    assert first == second


def test_raw_must_not_carry_upgraded_from():
    data = {
        "state": "raw",
        "origin": "sync",
        "created_at": "2026-04-12T14:30:00Z",
        "created_by": "post-spec-hook",
        "source_artifact": "docs/foo.md",
        "trigger": "post-spec",
        "raw_body_mode": "inline",
        "upgraded_from": {
            "raw_file": "staged/foo.yaml",
            "origin": "sync",
        },
    }
    with pytest.raises(ValidationError, match="upgraded_from"):
        StagedFile.model_validate(data)


def test_proposed_must_not_carry_raw_only_fields():
    base = {
        "state": "proposed",
        "origin": "capture",
        "created_at": "2026-04-12T14:35:00Z",
        "created_by": "capture",
        "proposed_action": "create",
        "target_page_id": None,
        "canonical_page": {
            "frontmatter": _valid_page_fm(),
            "body": "# Title\n\nBody.\n",
        },
    }

    with pytest.raises(ValidationError, match="source_artifact"):
        StagedFile.model_validate({**base, "source_artifact": "docs/foo.md"})

    with pytest.raises(ValidationError, match="source_commit"):
        StagedFile.model_validate({**base, "source_commit": "abc123"})

    with pytest.raises(ValidationError, match="trigger"):
        StagedFile.model_validate({**base, "trigger": "post-spec"})

    with pytest.raises(ValidationError, match="raw_body_bytes"):
        StagedFile.model_validate({**base, "raw_body_bytes": 512})


def test_raw_with_capture_origin_rejected():
    data = {
        "state": "raw",
        "origin": "capture",
        "created_at": "2026-04-12T14:30:00Z",
        "created_by": "post-spec-hook",
        "source_artifact": "docs/foo.md",
        "raw_body_mode": "inline",
    }
    with pytest.raises(ValidationError, match="origin in \\(sync, manual\\)"):
        StagedFile.model_validate(data)


def test_proposed_with_sync_origin_rejected():
    data = {
        "state": "proposed",
        "origin": "sync",
        "created_at": "2026-04-12T14:35:00Z",
        "created_by": "capture",
        "proposed_action": "create",
        "target_page_id": None,
        "canonical_page": {
            "frontmatter": _valid_page_fm(),
            "body": "# Title\n\nBody.\n",
        },
    }
    with pytest.raises(ValidationError, match="origin in \\(capture, bootstrap\\)"):
        StagedFile.model_validate(data)


def _valid_bootstrap_from(**overrides):
    base = {
        "question_text": "How does the story pipeline work?",
        "question_source": "seed",
        "question_key": "how-does-the-story-pipeline-work",
        "question_line": 1,
    }
    base.update(overrides)
    return base


def test_proposed_bootstrap_with_bootstrap_from_accepted():
    data = {
        "state": "proposed",
        "origin": "bootstrap",
        "created_at": "2026-04-12T14:35:00Z",
        "created_by": "wiki bootstrap",
        "proposed_action": "create",
        "target_page_id": None,
        "bootstrap_from": _valid_bootstrap_from(),
        "canonical_page": {
            "frontmatter": _valid_page_fm(),
            "body": "# Title\n\nBody.\n",
        },
    }
    f = StagedFile.model_validate(data)
    assert f.origin == "bootstrap"
    assert f.bootstrap_from is not None
    assert f.bootstrap_from.question_source == "seed"
    assert f.bootstrap_from.question_key == "how-does-the-story-pipeline-work"


def test_proposed_bootstrap_without_bootstrap_from_accepted():
    """bootstrap_from is soft-required (by writer convention, not schema),
    so an origin: bootstrap file without it still parses — back-compat with
    any hand-written bootstrap files that predate the provenance field.
    """
    data = {
        "state": "proposed",
        "origin": "bootstrap",
        "created_at": "2026-04-12T14:35:00Z",
        "created_by": "operator",
        "proposed_action": "create",
        "target_page_id": None,
        "canonical_page": {
            "frontmatter": _valid_page_fm(),
            "body": "# Title\n\nBody.\n",
        },
    }
    f = StagedFile.model_validate(data)
    assert f.bootstrap_from is None


def test_proposed_capture_with_bootstrap_from_rejected():
    """bootstrap_from is bootstrap-exclusive — capture-origin proposed
    files must not carry it.
    """
    data = {
        "state": "proposed",
        "origin": "capture",
        "created_at": "2026-04-12T14:35:00Z",
        "created_by": "capture",
        "proposed_action": "create",
        "target_page_id": None,
        "bootstrap_from": _valid_bootstrap_from(),
        "canonical_page": {
            "frontmatter": _valid_page_fm(),
            "body": "# Title\n\nBody.\n",
        },
    }
    with pytest.raises(
        ValidationError, match="bootstrap_from is only valid with origin: bootstrap"
    ):
        StagedFile.model_validate(data)


def test_raw_with_bootstrap_from_rejected():
    """raw files never carry bootstrap_from."""
    data = {
        "state": "raw",
        "origin": "sync",
        "created_at": "2026-04-12T14:30:00Z",
        "created_by": "wiki sync",
        "source_artifact": "docs/foo.md",
        "trigger": "manual",
        "raw_body_mode": "inline",
        "bootstrap_from": _valid_bootstrap_from(),
    }
    with pytest.raises(ValidationError, match="state: raw must not carry bootstrap_from"):
        StagedFile.model_validate(data)


def test_bootstrap_from_question_source_validated():
    """question_source must be 'seed' or 'ad-hoc' — anything else is rejected."""
    data = {
        "state": "proposed",
        "origin": "bootstrap",
        "created_at": "2026-04-12T14:35:00Z",
        "created_by": "wiki bootstrap",
        "proposed_action": "create",
        "target_page_id": None,
        "bootstrap_from": _valid_bootstrap_from(question_source="hallucinated"),
        "canonical_page": {
            "frontmatter": _valid_page_fm(),
            "body": "# Title\n\nBody.\n",
        },
    }
    with pytest.raises(ValidationError, match="question_source"):
        StagedFile.model_validate(data)
