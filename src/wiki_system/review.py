"""Deterministic listing of the staging review queue."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wiki_system.schema import StagedFile, StagedState
from wiki_system.storage import list_staged, read_staged


@dataclass
class ReviewItem:
    staging_path: str
    state: str
    origin: str
    created_at: str
    created_by: str
    # raw-only (None for proposed)
    source_artifact: str | None = None
    trigger: str | None = None
    raw_body_mode: str | None = None
    # proposed-only (None for raw)
    proposed_action: str | None = None
    target_page_id: str | None = None
    proposed_page_id: str | None = None
    proposed_title: str | None = None
    proposed_summary: str | None = None
    # Parse warning for files that failed to parse
    parse_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


def list_review_queue(wiki_root: Path, project: str) -> list[ReviewItem]:
    """Return the staging review queue for a project.

    Ordering:
      1. Raw items first (they need upgrade via capture).
      2. Proposed items second (they're ready to promote).
      3. Within each state, ordered by created_at ascending.

    Archive files under staging/.archive/ are excluded (handled by list_staged).

    Files that fail to parse are included with state='<unparseable>' and a
    parse_error so /wiki-review can surface them to the user.
    """
    items: list[ReviewItem] = []
    for path in list_staged(wiki_root, project):
        try:
            staged, _body = read_staged(path)
        except Exception as e:
            items.append(
                ReviewItem(
                    staging_path=str(path),
                    state="<unparseable>",
                    origin="<unknown>",
                    created_at="",
                    created_by="",
                    parse_error=str(e),
                )
            )
            continue
        items.append(_item_from(staged, path))
    items.sort(
        key=lambda i: (
            _state_order(i.state),
            i.created_at,
            i.staging_path,
        )
    )
    return items


def _state_order(state: str) -> int:
    if state == StagedState.RAW.value:
        return 0
    if state == StagedState.PROPOSED.value:
        return 1
    return 2  # unparseable / unknown


def _item_from(sf: StagedFile, path: Path) -> ReviewItem:
    item = ReviewItem(
        staging_path=str(path),
        state=sf.state,
        origin=sf.origin,
        created_at=sf.created_at.isoformat(),
        created_by=sf.created_by,
    )
    if item.state == StagedState.RAW.value:
        item.source_artifact = sf.source_artifact
        item.trigger = sf.trigger
        item.raw_body_mode = sf.raw_body_mode
    else:
        item.proposed_action = sf.proposed_action
        item.target_page_id = sf.target_page_id
        if sf.canonical_page is not None:
            item.proposed_page_id = sf.canonical_page.frontmatter.id
            item.proposed_title = sf.canonical_page.frontmatter.title
            item.proposed_summary = sf.canonical_page.frontmatter.summary
    return item
