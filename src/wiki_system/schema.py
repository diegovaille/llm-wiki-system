"""Pydantic schemas for wiki pages and staged files."""
from __future__ import annotations

import re
from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$")


class PageType(str, Enum):
    DECISION = "decision"
    CONCEPT = "concept"
    PATTERN = "pattern"
    SYSTEM = "system"
    WORKFLOW = "workflow"
    PRD = "prd"
    RESEARCH = "research"
    RUNBOOK = "runbook"
    GLOSSARY = "glossary"


class PageStatus(str, Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    DRAFT = "draft"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class PageFrontmatter(BaseModel):
    """Frontmatter of a canonical page in pages/."""

    model_config = ConfigDict(use_enum_values=True, extra="forbid")

    id: str
    title: str
    summary: str = ""
    type: PageType
    project: str
    domains: list[str] = Field(default_factory=list)
    status: PageStatus = PageStatus.ACTIVE
    superseded_by: str | None = None
    aliases: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    related: list[str] = Field(default_factory=list)
    updated_at: date
    confidence: Confidence = Confidence.MEDIUM

    @field_validator("id")
    @classmethod
    def _id_must_be_slug(cls, v: str) -> str:
        if not SLUG_RE.match(v):
            raise ValueError(
                "id must be slug-like: lowercase letters, digits, and hyphens"
            )
        return v

    @model_validator(mode="after")
    def _validate_cross_field_rules(self) -> "PageFrontmatter":
        # superseded_by only valid when status == superseded
        if self.superseded_by and self.status != PageStatus.SUPERSEDED.value:
            raise ValueError("superseded_by is only valid when status == 'superseded'")
        # high confidence requires non-empty sources
        if self.confidence == Confidence.HIGH.value and not self.sources:
            raise ValueError("confidence: high requires at least one entry in sources")
        return self


class StagedState(str, Enum):
    RAW = "raw"
    PROPOSED = "proposed"


class StagedFileOrigin(str, Enum):
    SYNC = "sync"
    CAPTURE = "capture"
    BOOTSTRAP = "bootstrap"
    MANUAL = "manual"


class RawBodyMode(str, Enum):
    INLINE = "inline"
    POINTER = "pointer"


class ProposedAction(str, Enum):
    CREATE = "create"
    UPDATE = "update"


class UpgradedFrom(BaseModel):
    model_config = ConfigDict(use_enum_values=True, extra="forbid")

    raw_file: str
    origin: StagedFileOrigin
    trigger: str | None = None
    source_artifact: str | None = None


class BootstrapFrom(BaseModel):
    """Provenance for bootstrap-originated proposed staged files.

    Records the seed question (or ad-hoc question) that drove the
    bootstrap run. Lets `/wiki-review` display which question a page
    answers, and lets bootstrap dedupe check whether a given question
    already has a pending proposal.
    """

    model_config = ConfigDict(extra="forbid")

    question_text: str
    question_source: str  # "seed" | "ad-hoc"
    question_key: str  # normalized slug used for dedupe
    question_line: int | None = None  # 1-based line in queries/seed-questions.md

    @field_validator("question_source")
    @classmethod
    def _validate_source(cls, v: str) -> str:
        if v not in ("seed", "ad-hoc"):
            raise ValueError(
                f"question_source must be 'seed' or 'ad-hoc', got {v!r}"
            )
        return v


class CanonicalPageEmbed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frontmatter: PageFrontmatter
    body: str


class StagedFile(BaseModel):
    """Unified envelope for raw and proposed staged files."""

    model_config = ConfigDict(use_enum_values=True, extra="forbid")

    state: StagedState
    origin: StagedFileOrigin
    created_at: datetime
    created_by: str

    # raw-only fields
    source_artifact: str | None = None
    source_commit: str | None = None
    trigger: str | None = None
    raw_body_mode: RawBodyMode | None = None
    raw_body_bytes: int | None = None

    # proposed-only fields
    proposed_action: ProposedAction | None = None
    target_page_id: str | None = None
    upgraded_from: UpgradedFrom | None = None
    bootstrap_from: BootstrapFrom | None = None
    canonical_page: CanonicalPageEmbed | None = None

    @model_validator(mode="after")
    def _validate_state_shape(self) -> "StagedFile":
        if self.state == StagedState.RAW.value:
            if self.origin not in (StagedFileOrigin.SYNC.value, StagedFileOrigin.MANUAL.value):
                raise ValueError(
                    f"state: raw requires origin in (sync, manual), got {self.origin}"
                )
            if self.source_artifact is None:
                raise ValueError("state: raw requires source_artifact")
            if self.raw_body_mode is None:
                raise ValueError("state: raw requires raw_body_mode")
            if self.canonical_page is not None:
                raise ValueError("state: raw must not carry canonical_page")
            if self.proposed_action is not None:
                raise ValueError("state: raw must not carry proposed_action")
            if self.target_page_id is not None:
                raise ValueError("state: raw must not carry target_page_id")
            if self.upgraded_from is not None:
                raise ValueError("state: raw must not carry upgraded_from")
            if self.bootstrap_from is not None:
                raise ValueError("state: raw must not carry bootstrap_from")
            return self

        # state == proposed
        if self.origin not in (StagedFileOrigin.CAPTURE.value, StagedFileOrigin.BOOTSTRAP.value):
            raise ValueError(
                f"state: proposed requires origin in (capture, bootstrap), got {self.origin}"
            )
        if self.proposed_action is None:
            raise ValueError("state: proposed requires proposed_action")
        if self.canonical_page is None:
            raise ValueError("state: proposed requires canonical_page")
        if self.raw_body_mode is not None:
            raise ValueError("state: proposed must not carry raw_body_mode")
        if self.source_artifact is not None:
            raise ValueError("state: proposed must not carry source_artifact")
        if self.source_commit is not None:
            raise ValueError("state: proposed must not carry source_commit")
        if self.trigger is not None:
            raise ValueError("state: proposed must not carry trigger")
        if self.raw_body_bytes is not None:
            raise ValueError("state: proposed must not carry raw_body_bytes")

        # bootstrap_from is bootstrap-exclusive
        if (
            self.bootstrap_from is not None
            and self.origin != StagedFileOrigin.BOOTSTRAP.value
        ):
            raise ValueError(
                "bootstrap_from is only valid with origin: bootstrap"
            )

        # Page identity invariant
        emb_id = self.canonical_page.frontmatter.id
        if self.proposed_action == ProposedAction.UPDATE.value:
            if self.target_page_id is None:
                raise ValueError(
                    "proposed_action: update requires target_page_id to be non-null"
                )
            if self.target_page_id != emb_id:
                raise ValueError(
                    f"canonical_page.frontmatter.id ({emb_id}) must equal "
                    f"target_page_id ({self.target_page_id}) for update"
                )
        else:  # create
            if self.target_page_id is not None:
                raise ValueError(
                    "proposed_action: create requires target_page_id to be null"
                )
        return self
