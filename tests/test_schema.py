from datetime import date

import pytest
from pydantic import ValidationError

from wiki_system.schema import PageFrontmatter, PageType, PageStatus


def _valid_page_data(**overrides):
    base = {
        "id": "cc-moderation-system",
        "title": "ClassCloud Moderation System",
        "summary": "End-to-end overview.",
        "type": "system",
        "project": "classcloud",
        "domains": ["moderation", "policy"],
        "status": "active",
        "aliases": ["moderation engine"],
        "sources": ["docs/content-moderation.md"],
        "related": [],
        "updated_at": "2026-04-12",
        "confidence": "high",
    }
    base.update(overrides)
    return base


def test_valid_page_parses():
    page = PageFrontmatter.model_validate(_valid_page_data())
    assert page.id == "cc-moderation-system"
    assert page.type == PageType.SYSTEM
    assert page.status == PageStatus.ACTIVE
    assert page.updated_at == date(2026, 4, 12)


def test_invalid_type_rejected():
    with pytest.raises(ValidationError):
        PageFrontmatter.model_validate(_valid_page_data(type="gibberish"))


def test_invalid_status_rejected():
    with pytest.raises(ValidationError):
        PageFrontmatter.model_validate(_valid_page_data(status="unknown"))


def test_superseded_by_only_valid_when_status_superseded():
    # Allowed
    data = _valid_page_data(status="superseded", superseded_by="cc-moderation-v2")
    p = PageFrontmatter.model_validate(data)
    assert p.superseded_by == "cc-moderation-v2"
    # Disallowed: active + superseded_by
    with pytest.raises(ValidationError, match="superseded_by"):
        PageFrontmatter.model_validate(
            _valid_page_data(status="active", superseded_by="cc-moderation-v2")
        )


def test_high_confidence_requires_nonempty_sources():
    with pytest.raises(ValidationError, match="sources"):
        PageFrontmatter.model_validate(
            _valid_page_data(confidence="high", sources=[])
        )


def test_low_confidence_allows_empty_sources():
    p = PageFrontmatter.model_validate(
        _valid_page_data(confidence="low", sources=[])
    )
    assert p.sources == []


def test_session_source_form_accepted():
    p = PageFrontmatter.model_validate(
        _valid_page_data(sources=["session:2026-04-12-moderation-refactor"])
    )
    assert p.sources[0].startswith("session:")


def test_id_must_be_slug_like():
    with pytest.raises(ValidationError, match="id"):
        PageFrontmatter.model_validate(_valid_page_data(id="Not A Slug!"))
