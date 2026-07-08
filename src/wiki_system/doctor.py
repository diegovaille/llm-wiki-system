"""Stale-page detection against an external code graph (read-only)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from wiki_system.index import load_index

CODE_SPAN_RE = re.compile(r"`([^`\n]+)`")
FENCED_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)
PY_PATH_RE = re.compile(r"^[\w./-]+\.py$")
FUNCTION_RE = re.compile(r"^\.?[a-z_][a-z0-9_]*\(\)$")
# Broad on purpose: 529/1825 class-like labels in a real graphify graph
# (LLMProvider, AIService, Chat, ...) fail a two-hump CamelCase regex.
# Residual noise from capitalized prose words is absorbed by the
# stoplist plus advisory-confidence reporting.
CLASS_RE = re.compile(r"^[A-Z][A-Za-z0-9]+$")
CLASS_STOPWORDS = frozenset({"True", "False", "None"})


@dataclass(frozen=True)
class Identifier:
    text: str
    kind: Literal["path", "function", "class"]


def extract_identifiers(body: str) -> list[Identifier]:
    prose = FENCED_BLOCK_RE.sub("", body)
    seen: dict[Identifier, None] = {}
    for span in CODE_SPAN_RE.findall(prose):
        span = span.strip()
        if PY_PATH_RE.match(span):
            seen.setdefault(Identifier(span, "path"))
        elif FUNCTION_RE.match(span):
            seen.setdefault(Identifier(span.lstrip("."), "function"))
        elif CLASS_RE.match(span) and span not in CLASS_STOPWORDS:
            seen.setdefault(Identifier(span, "class"))
    return list(seen)
