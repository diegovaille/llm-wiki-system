"""Shared validation + write path for `state: proposed` staged files.

Both `wiki capture submit` and `wiki bootstrap submit` need the same core
work:

1. Validate the proposal dict has `action`, `target_page_id`, and (for
   non-noop actions) `canonical_page` with `frontmatter` + `body`.
2. Parse the canonical_page into a `CanonicalPageEmbed` (pydantic).
3. Build a `StagedFile` envelope with state=proposed plus the caller's
   origin and provenance extras (`upgraded_from` for capture staged-upgrade,
   `bootstrap_from` for bootstrap).
4. Write it via `storage.write_staged`.

Keeping this in one place means the page identity invariant, the forbid-
extras check, and the write path live in exactly one place. Callers
wrap `StagingWriteError` in their own command-specific rejection type so
external contracts (`SubmitRejection`, `BootstrapRejection`) stay distinct.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wiki_system.schema import (
    BootstrapFrom,
    CanonicalPageEmbed,
    PageFrontmatter,
    ProposedAction,
    StagedFile,
    StagedFileOrigin,
    StagedState,
    UpgradedFrom,
)
from wiki_system.storage import utc_now, write_staged


class StagingWriteError(Exception):
    """Raised when a proposal cannot be written as a proposed staged file.

    Callers re-raise as their command-specific rejection type to keep
    external contracts distinct.
    """


@dataclass
class StagingWriteResult:
    """Outcome of a successful `write_proposed_staged_file` call."""

    staged: StagedFile
    path: Path
    action: str  # proposed_action as a string
    proposed_page_id: str


def _slug_for(fm: PageFrontmatter) -> str:
    """Stable slug used in the staged filename. Matches pre-refactor behavior."""
    return fm.id


def write_proposed_staged_file(
    *,
    wiki_root: Path,
    project: str,
    proposal: dict[str, Any],
    origin: StagedFileOrigin,
    created_by: str,
    upgraded_from: UpgradedFrom | None = None,
    bootstrap_from: BootstrapFrom | None = None,
) -> StagingWriteResult:
    """Validate the proposal and write a `state: proposed` staged file.

    The proposal dict shape:

        {
            "action": "create" | "update",
            "target_page_id": str | None,
            "canonical_page": {
                "frontmatter": {...PageFrontmatter fields...},
                "body": str,
            },
            ...           # ignored extras (e.g. rationale, bootstrap_question)
        }

    Caller responsibilities BEFORE calling this function:
    - Handle `action: noop` (this function rejects noop; noop doesn't write
      anything and the caller should return its own result type directly).
    - Translate `upgraded_from` / `bootstrap_from` from the caller's
      command-specific data (e.g. reading the original raw file in the
      capture staged-upgrade flow, or building from bootstrap_question
      metadata in the bootstrap submit flow).
    - Enforce command-specific rules that don't belong in the schema —
      e.g. "session-origin capture requires a session:* source entry",
      or "staged-upgrade requires source_artifact in sources".

    Raises `StagingWriteError` on any shape, schema, or write failure.
    Callers wrap this in their own rejection type.
    """
    action = proposal.get("action")
    try:
        action_enum = ProposedAction(action)
    except (TypeError, ValueError) as e:
        raise StagingWriteError(
            f"proposal.action must be 'create' or 'update', got {action!r}"
        ) from e

    cp = proposal.get("canonical_page")
    if not cp or not isinstance(cp, dict):
        raise StagingWriteError(
            "proposal must include canonical_page for create/update actions"
        )
    if "frontmatter" not in cp or "body" not in cp:
        raise StagingWriteError(
            "canonical_page must include both frontmatter and body"
        )

    try:
        embed = CanonicalPageEmbed.model_validate(cp)
    except Exception as e:
        raise StagingWriteError(f"canonical_page schema invalid: {e}") from e

    target_page_id = proposal.get("target_page_id")

    try:
        staged = StagedFile(
            state=StagedState.PROPOSED,
            origin=origin,
            created_at=utc_now(),
            created_by=created_by,
            proposed_action=action_enum,
            target_page_id=target_page_id,
            upgraded_from=upgraded_from,
            bootstrap_from=bootstrap_from,
            canonical_page=embed,
        )
    except Exception as e:
        raise StagingWriteError(f"staged envelope invalid: {e}") from e

    path = write_staged(
        wiki_root, project, staged, "", slug=_slug_for(embed.frontmatter)
    )
    return StagingWriteResult(
        staged=staged,
        path=path,
        action=action_enum.value,
        proposed_page_id=embed.frontmatter.id,
    )
