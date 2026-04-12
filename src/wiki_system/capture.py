"""Capture prepare/submit backend."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from wiki_system.config import ProjectConfig
from wiki_system.schema import (
    PageFrontmatter,
    RawBodyMode,
    StagedFile,
    StagedState,
)
from wiki_system.storage import list_pages, read_page, read_staged


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
