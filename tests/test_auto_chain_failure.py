from datetime import date
from pathlib import Path

from wiki_system.capture import submit_capture
from wiki_system.promote import promote
from wiki_system.schema import Confidence, PageFrontmatter, PageStatus, PageType
from wiki_system.storage import list_staged, write_page


def _valid_proposal() -> dict:
    return {
        "action": "create",
        "target_page_id": None,
        "rationale": "test",
        "canonical_page": {
            "frontmatter": {
                "id": "lv-foo",
                "title": "Foo",
                "summary": "",
                "type": "system",
                "project": "luminavine",
                "domains": ["pipeline"],
                "status": "active",
                "aliases": [],
                "sources": ["session:2026-04-12-foo"],
                "related": [],
                "updated_at": "2026-04-12",
                "confidence": "high",
            },
            "body": "# Foo\n",
        },
    }


def test_submit_then_failing_promote_preserves_staged_file(wiki_root: Path):
    # Write an existing page with same id so create collides and promote fails
    existing = PageFrontmatter(
        id="lv-foo",
        title="Existing Foo",
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
    write_page(wiki_root, "luminavine", existing, "# Existing\n")

    # submit succeeds — staged file is written
    result = submit_capture(
        wiki_root,
        project="luminavine",
        proposal=_valid_proposal(),
        from_staged=None,
    )
    assert result.action == "create"
    staged_path = Path(result.staging_path)
    assert staged_path.exists()

    # simulated auto-chain: promote --apply fails because id collides
    try:
        promote(wiki_root, "luminavine", staged_path, apply=True)
    except Exception:
        pass  # expected

    # staged file is still present and remains promotable on retry
    staged = list_staged(wiki_root, "luminavine")
    assert staged_path in staged

    # The user could retry; promote should still cleanly reject, and staged file survives.
    try:
        promote(wiki_root, "luminavine", staged_path, apply=True)
    except Exception:
        pass
    assert staged_path.exists()
