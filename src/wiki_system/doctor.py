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


@dataclass
class GraphSymbols:
    files: set[str] = field(default_factory=set)
    symbols: set[str] = field(default_factory=set)
    node_count: int = 0


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


def load_graph_symbols(path: Path) -> GraphSymbols:
    if not path.exists():
        raise FileNotFoundError(path)
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise ValueError(f"graph is not valid JSON: {e}") from e
    nodes = data.get("nodes")
    if not isinstance(nodes, list):
        raise ValueError("graph JSON has no 'nodes' list")
    g = GraphSymbols(node_count=len(nodes))
    for n in nodes:
        src = n.get("source_file")
        if src:
            g.files.add(src)
        label = (n.get("norm_label") or n.get("label") or "").lower()
        label = label.lstrip(".").removesuffix("()")
        if label:
            g.symbols.add(label)
    return g


@dataclass(frozen=True)
class Finding:
    page_id: str
    identifier: str
    kind: str
    confidence: Literal["high", "advisory"]


@dataclass
class DoctorReport:
    project: str
    pages_checked: int
    identifiers_checked: int
    findings: list[Finding]


def _path_in_graph(span: str, files: set[str]) -> bool:
    if span in files:
        return True
    return any(f.endswith("/" + span) or span.endswith("/" + f) for f in files)


def run_doctor(wiki_root: Path, project: str, graph_path: Path) -> DoctorReport:
    idx = load_index(wiki_root, project)
    g = load_graph_symbols(graph_path)
    findings: list[Finding] = []
    checked = 0
    for page in idx.pages:
        for ident in extract_identifiers(page.body):
            checked += 1
            if ident.kind == "path":
                if not _path_in_graph(ident.text, g.files):
                    findings.append(Finding(page.id, ident.text, ident.kind, "high"))
            else:
                name = ident.text.lower().removesuffix("()")
                if name not in g.symbols:
                    findings.append(
                        Finding(page.id, ident.text, ident.kind, "advisory")
                    )
    return DoctorReport(
        project=project,
        pages_checked=len(idx.pages),
        identifiers_checked=checked,
        findings=findings,
    )
