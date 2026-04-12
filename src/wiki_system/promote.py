"""Promotion of proposed staged files to canonical pages."""
from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path

from wiki_system.index import build_index, save_index, render_views
from wiki_system.schema import ProposedAction, StagedState
from wiki_system.storage import (
    append_manifest,
    archive_staged,
    list_pages,
    read_page,
    read_staged,
    utc_now,
    write_page,
)


class PromoteRejection(Exception):
    """Raised when a staged file cannot be promoted."""


@dataclass
class PromoteResult:
    action: str
    page_id: str
    path: str
    dry_run: bool
    diff: str


def promote(
    wiki_root: Path,
    project: str,
    staged_path: Path,
    *,
    apply: bool,
    repo_path: str = "",
) -> PromoteResult:
    staged, _ = read_staged(staged_path)

    if staged.state == StagedState.RAW.value:
        raise PromoteRejection(
            f"staged file is state: raw, cannot promote. "
            f"Run `wiki capture --from-staged={staged_path}` first."
        )

    cp = staged.canonical_page
    assert cp is not None  # validated by schema
    new_fm = cp.frontmatter
    new_body = cp.body
    existing_ids = {p.stem for p in list_pages(wiki_root, project)}

    if staged.proposed_action == ProposedAction.CREATE.value:
        if new_fm.id in existing_ids:
            raise PromoteRejection(
                f"create rejected: page id '{new_fm.id}' already exists"
            )
        diff = _new_page_diff(new_fm.id, new_body)
        if not apply:
            return PromoteResult(
                action="create",
                page_id=new_fm.id,
                path="",
                dry_run=True,
                diff=diff,
            )
        written = write_page(wiki_root, project, new_fm, new_body)
        _post_write_housekeeping(
            wiki_root, project, staged_path, new_fm.id, "create", repo_path
        )
        return PromoteResult(
            action="create",
            page_id=new_fm.id,
            path=str(written),
            dry_run=False,
            diff=diff,
        )

    # update
    target = staged.target_page_id
    if target not in existing_ids:
        raise PromoteRejection(
            f"update rejected: target page '{target}' does not exist"
        )
    existing_path = wiki_root / project / "pages" / f"{target}.md"
    _, old_body = read_page(existing_path)
    diff = _diff(old_body, new_body, target)
    if not apply:
        return PromoteResult(
            action="update",
            page_id=target,
            path=str(existing_path),
            dry_run=True,
            diff=diff,
        )
    written = write_page(wiki_root, project, new_fm, new_body)
    _post_write_housekeeping(
        wiki_root, project, staged_path, target, "update", repo_path
    )
    return PromoteResult(
        action="update",
        page_id=target,
        path=str(written),
        dry_run=False,
        diff=diff,
    )


def _new_page_diff(page_id: str, body: str) -> str:
    return f"+++ pages/{page_id}.md (new)\n{body}"


def _diff(old_body: str, new_body: str, page_id: str) -> str:
    diff = difflib.unified_diff(
        old_body.splitlines(keepends=True),
        new_body.splitlines(keepends=True),
        fromfile=f"pages/{page_id}.md (old)",
        tofile=f"pages/{page_id}.md (new)",
    )
    return "".join(diff)


def _post_write_housekeeping(
    wiki_root: Path,
    project: str,
    staged_path: Path,
    page_id: str,
    action: str,
    repo_path: str,
) -> None:
    append_manifest(
        wiki_root,
        project,
        {
            "id": page_id,
            "action": action,
            "promoted_at": utc_now().isoformat(),
            "from_staged": staged_path.name,
        },
    )
    archive_staged(wiki_root, project, staged_path)
    idx = build_index(wiki_root, project)
    save_index(wiki_root, project, idx)
    render_views(wiki_root, project, idx, repo_path=repo_path or "")
