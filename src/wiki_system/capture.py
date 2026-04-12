"""Capture prepare/submit backend — prepare side builds prompt packages; submit side writes proposed staged files."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from wiki_system.config import ProjectConfig
from wiki_system.schema import (
    CanonicalPageEmbed,
    PageFrontmatter,
    ProposedAction,
    RawBodyMode,
    StagedFile,
    StagedFileOrigin,
    StagedState,
    UpgradedFrom,
)
from wiki_system.storage import list_pages, read_page, read_staged, utc_now, write_staged


ALLOWED_ACTIONS = ["noop", "update", "create"]


@dataclass
class PromptPackage:
    system: str
    context: str
    schema: str
    instructions: str
    allowed_actions: list[str] = field(default_factory=lambda: list(ALLOWED_ACTIONS))

    def to_json(self) -> str:
        return json.dumps(
            {
                "system": self.system,
                "context": self.context,
                "schema": self.schema,
                "instructions": self.instructions,
                "allowed_actions": self.allowed_actions,
            },
            indent=2,
        )


SYSTEM_PROMPT = """You are compiling durable, agent-readable knowledge into a personal wiki.

Propose at most ONE canonical change. Bias hard toward noop and update — only create a new
page when no existing page reasonably covers the topic. Never propose more than one change.
"""


def _existing_pages_summary(wiki_root: Path, project: str) -> str:
    paths = list_pages(wiki_root, project)
    if not paths:
        return "(no existing pages yet)"
    lines = []
    for p in paths:
        fm, _ = read_page(p)
        lines.append(
            f"- id: {fm.id} | title: {fm.title} | type: "
            f"{fm.type} | "
            f"domains: {','.join(fm.domains)} | summary: {fm.summary}"
        )
    return "\n".join(lines)


def _schema_description() -> str:
    return json.dumps(
        {
            "PageFrontmatter": PageFrontmatter.model_json_schema(),
        },
        indent=2,
    )


def _dereference_raw(staged: StagedFile, raw_body: str, project_cfg: ProjectConfig) -> tuple[str, list[str]]:
    warnings: list[str] = []
    if staged.raw_body_mode == RawBodyMode.INLINE.value:
        return raw_body, warnings
    # pointer mode: re-read from project repo
    repo_root = Path(project_cfg.repo_path).expanduser().resolve()
    artifact_path = repo_root / staged.source_artifact
    if not artifact_path.exists():
        raise FileNotFoundError(
            f"source_artifact does not exist at {artifact_path}; "
            f"cannot dereference pointer-mode raw staged file"
        )
    content = artifact_path.read_text()
    # Note: v0.1 does not check source_commit against HEAD; we only emit a TODO warning
    if staged.source_commit:
        warnings.append(
            f"source_commit {staged.source_commit} drift check not implemented in v0.1"
        )
    return content, warnings


def prepare_capture(
    wiki_root: Path,
    project_cfg: ProjectConfig,
    *,
    session_notes: str | None,
    from_staged: Path | None,
) -> PromptPackage:
    project = project_cfg.name
    existing_summary = _existing_pages_summary(wiki_root, project)

    if from_staged is not None:
        staged, body = read_staged(from_staged)
        if staged.state != StagedState.RAW.value:
            raise ValueError(
                f"--from-staged expects state: raw, got state: {staged.state}"
            )
        artifact_content, warnings = _dereference_raw(staged, body, project_cfg)
        context = (
            f"## Existing canonical pages\n{existing_summary}\n\n"
            f"## Artifact to synthesize\n"
            f"- source_artifact: {staged.source_artifact}\n"
            f"- trigger: {staged.trigger}\n"
            f"- raw_body_mode: {staged.raw_body_mode}\n\n"
            f"### Artifact content\n{artifact_content}\n"
        )
        if warnings:
            context += "\n## Warnings\n" + "\n".join(f"- {w}" for w in warnings) + "\n"
        instructions = (
            "staged-upgrade mode. Upgrade the raw staged file into a state: proposed "
            "canonical page. Sources must include the original source_artifact."
        )
    else:
        if session_notes is None:
            session_notes = ""
        context = (
            f"## Existing canonical pages\n{existing_summary}\n\n"
            f"## Session notes\n{session_notes}\n"
        )
        instructions = (
            "session-origin mode. Propose at most one canonical change. "
            "Any new/updated page must include a source like "
            "'session:<YYYY-MM-DD>-<slug>' in its sources list."
        )

    return PromptPackage(
        system=SYSTEM_PROMPT,
        context=context,
        schema=_schema_description(),
        instructions=instructions,
        allowed_actions=list(ALLOWED_ACTIONS),
    )


class SubmitRejection(Exception):
    """Raised when a proposal cannot be submitted as a proposed staged file."""


@dataclass
class SubmitResult:
    action: str  # "noop" | "create" | "update"
    staging_path: str
    proposed_page_id: str | None


def _slug_for(fm: PageFrontmatter) -> str:
    return fm.id


def submit_capture(
    wiki_root: Path,
    *,
    project: str,
    proposal: dict[str, Any],
    from_staged: Path | None,
) -> SubmitResult:
    action = proposal.get("action")
    if action not in ALLOWED_ACTIONS:
        raise SubmitRejection(
            f"proposal.action must be one of {ALLOWED_ACTIONS}, got {action!r}"
        )

    if action == "noop":
        return SubmitResult(action="noop", staging_path="", proposed_page_id=None)

    cp = proposal.get("canonical_page")
    if not cp or "frontmatter" not in cp or "body" not in cp:
        raise SubmitRejection(
            "proposal must include canonical_page.frontmatter and canonical_page.body "
            "for create/update actions"
        )

    try:
        embed = CanonicalPageEmbed.model_validate(cp)
    except Exception as e:
        raise SubmitRejection(f"canonical_page schema invalid: {e}") from e

    target_page_id = proposal.get("target_page_id")
    upgraded_from: UpgradedFrom | None = None
    origin = StagedFileOrigin.CAPTURE

    if from_staged is not None:
        raw_sf, _ = read_staged(from_staged)
        if raw_sf.state != StagedState.RAW.value:
            raise SubmitRejection(
                f"--from-staged requires state: raw, got state: {raw_sf.state}"
            )
        if raw_sf.source_artifact not in embed.frontmatter.sources:
            raise SubmitRejection(
                f"proposed page sources must include the original source_artifact "
                f"({raw_sf.source_artifact})"
            )
        upgraded_from = UpgradedFrom(
            raw_file=f"staging/{from_staged.name}",
            origin=StagedFileOrigin(raw_sf.origin),
            trigger=raw_sf.trigger,
            source_artifact=raw_sf.source_artifact,
        )
    else:
        # session-origin: require a session:<date>-<slug> source entry
        if not any(s.startswith("session:") for s in embed.frontmatter.sources):
            raise SubmitRejection(
                "session-origin capture requires a source of the form "
                "'session:<YYYY-MM-DD>-<slug>' in canonical_page.frontmatter.sources"
            )

    try:
        staged = StagedFile(
            state=StagedState.PROPOSED,
            origin=origin,
            created_at=utc_now(),
            created_by="capture",
            proposed_action=ProposedAction(action),
            target_page_id=target_page_id,
            upgraded_from=upgraded_from,
            canonical_page=embed,
        )
    except Exception as e:
        raise SubmitRejection(f"staged envelope invalid: {e}") from e

    path = write_staged(
        wiki_root, project, staged, "", slug=_slug_for(embed.frontmatter)
    )
    if from_staged is not None:
        from_staged.unlink()
    return SubmitResult(
        action=action,
        staging_path=str(path),
        proposed_page_id=embed.frontmatter.id,
    )
