import pytest
from pydantic import ValidationError

from wiki_system.schema import StagedFile


def _page_fm(**overrides):
    base = {
        "id": "lv-foo",
        "title": "Foo",
        "summary": "",
        "type": "concept",
        "project": "luminavine",
        "domains": [],
        "status": "active",
        "aliases": [],
        "sources": ["session:2026-04-12-x"],
        "related": [],
        "updated_at": "2026-04-12",
        "confidence": "high",
    }
    base.update(overrides)
    return base


def _proposed(**overrides):
    base = {
        "state": "proposed",
        "origin": "capture",
        "created_at": "2026-04-12T14:35:00Z",
        "created_by": "capture",
        "proposed_action": "update",
        "target_page_id": "lv-foo",
        "canonical_page": {
            "frontmatter": _page_fm(id="lv-foo"),
            "body": "# Foo\n",
        },
    }
    base.update(overrides)
    return base


def test_update_with_matching_ids_accepted():
    f = StagedFile.model_validate(_proposed())
    assert f.target_page_id == f.canonical_page.frontmatter.id


def test_update_with_null_target_rejected():
    data = _proposed()
    data["target_page_id"] = None
    with pytest.raises(ValidationError, match="target_page_id"):
        StagedFile.model_validate(data)


def test_update_with_id_mismatch_rejected():
    data = _proposed()
    data["canonical_page"]["frontmatter"] = _page_fm(id="lv-bar")
    with pytest.raises(ValidationError, match="canonical_page.frontmatter.id"):
        StagedFile.model_validate(data)


def test_create_with_non_null_target_rejected():
    data = _proposed(proposed_action="create", target_page_id="lv-foo")
    with pytest.raises(ValidationError, match="target_page_id"):
        StagedFile.model_validate(data)


def test_create_with_null_target_accepted():
    data = _proposed(proposed_action="create", target_page_id=None)
    f = StagedFile.model_validate(data)
    assert f.proposed_action == "create"
    assert f.target_page_id is None
