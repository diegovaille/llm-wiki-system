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
        "id": "lv-story-pipeline",
        "title": "LuminaVine Story Pipeline",
        "summary": "End-to-end view.",
        "type": "system",
        "project": "luminavine",
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
            "body": "# LuminaVine Story Pipeline\n\nBody content.",
        },
    }
    f = StagedFile.model_validate(data)
    assert f.state == StagedState.PROPOSED.value
    assert f.proposed_action == ProposedAction.CREATE.value
    assert f.target_page_id is None
    assert isinstance(f.canonical_page, CanonicalPageEmbed)
    assert f.canonical_page.frontmatter.id == "lv-story-pipeline"


def test_proposed_update_parses():
    data = {
        "state": "proposed",
        "origin": "capture",
        "created_at": "2026-04-12T14:35:00Z",
        "created_by": "capture",
        "proposed_action": "update",
        "target_page_id": "lv-story-pipeline",
        "canonical_page": {
            "frontmatter": _valid_page_fm(id="lv-story-pipeline"),
            "body": "# LuminaVine Story Pipeline\n\nUpdated body.",
        },
    }
    f = StagedFile.model_validate(data)
    assert f.proposed_action == ProposedAction.UPDATE.value
    assert f.target_page_id == "lv-story-pipeline"


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
