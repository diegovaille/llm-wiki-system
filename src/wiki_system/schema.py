"""Pydantic schemas for wiki pages and staged files."""
from __future__ import annotations

import re
from datetime import date
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
