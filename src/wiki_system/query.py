"""Deterministic lexical + link-graph retrieval."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from wiki_system.config import RetrievalConfig
from wiki_system.index import PageMeta, load_index


TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


@dataclass
class QueryResult:
    id: str
    title: str
    summary: str
    path: str
    score: float
    matched_fields: list[str]
    match_source: Literal["lexical", "graph"]
    reasons: list[str]
    snippet: str


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in TOKEN_RE.findall(text)]


def _score_lexical(
    page: PageMeta, q_tokens: set[str], cfg: RetrievalConfig
) -> tuple[float, list[str], list[str]]:
    score = 0.0
    fields: list[str] = []
    reasons: list[str] = []

    title_tokens = set(_tokenize(page.title))
    if q_tokens & title_tokens:
        overlap = len(q_tokens & title_tokens)
        score += cfg.field_weights.get("title", 5.0) * overlap
        fields.append("title")
        reasons.append(f"title match: {sorted(q_tokens & title_tokens)}")

    alias_tokens = set()
    for a in page.aliases:
        alias_tokens.update(_tokenize(a))
    if q_tokens & alias_tokens:
        overlap = len(q_tokens & alias_tokens)
        score += cfg.field_weights.get("aliases", 4.0) * overlap
        fields.append("aliases")
        reasons.append(f"alias match: {sorted(q_tokens & alias_tokens)}")

    domain_tokens = set()
    for d in page.domains:
        domain_tokens.update(_tokenize(d))
    if q_tokens & domain_tokens:
        overlap = len(q_tokens & domain_tokens)
        score += cfg.field_weights.get("domains", 3.0) * overlap
        fields.append("domains")
        reasons.append(f"domain match: {sorted(q_tokens & domain_tokens)}")

    type_tokens = set(_tokenize(page.type))
    if q_tokens & type_tokens:
        score += cfg.field_weights.get("type", 2.0)
        fields.append("type")
        reasons.append(f"type match: {page.type}")

    heading_tokens = set()
    for h in page.headings:
        heading_tokens.update(_tokenize(h))
    if q_tokens & heading_tokens:
        overlap = len(q_tokens & heading_tokens)
        score += cfg.field_weights.get("headings", 2.0) * overlap
        fields.append("headings")
        reasons.append("heading match")

    body_tokens = set(_tokenize(page.body))
    body_overlap = q_tokens & body_tokens
    if body_overlap:
        score += cfg.field_weights.get("body", 1.0) * len(body_overlap)
        fields.append("body")
        reasons.append(f"body match: {sorted(body_overlap)}")

    return score, fields, reasons


def _snippet_for(page: PageMeta, q_tokens: set[str]) -> str:
    lines = [line for line in page.body.splitlines() if line.strip()]
    if not lines:
        return page.summary or ""
    # Prefer a line containing a query token
    for line in lines:
        toks = set(_tokenize(line))
        if q_tokens & toks:
            return line.strip()[:180]
    return lines[0].strip()[:180]


def run_query(
    wiki_root: Path,
    project: str,
    question: str,
    cfg: RetrievalConfig,
    *,
    limit: int = 5,
) -> list[QueryResult]:
    idx = load_index(wiki_root, project)
    q_tokens = set(_tokenize(question))

    # Phase 1: lexical scoring
    lex_hits: dict[str, tuple[float, list[str], list[str]]] = {}
    for page in idx.pages:
        s, fields, reasons = _score_lexical(page, q_tokens, cfg)
        if s > 0:
            lex_hits[page.id] = (s, fields, reasons)

    results: dict[str, QueryResult] = {}
    id_to_page = {p.id: p for p in idx.pages}

    for pid, (score, fields, reasons) in lex_hits.items():
        p = id_to_page[pid]
        results[pid] = QueryResult(
            id=p.id,
            title=p.title,
            summary=p.summary,
            path=p.path,
            score=score,
            matched_fields=fields,
            match_source="lexical",
            reasons=list(reasons),
            snippet=_snippet_for(p, q_tokens),
        )

    # Phase 2: 1-hop graph expansion through curated edges
    curated_edges = [e for e in idx.edges if e.kind == "curated"]
    for e in curated_edges:
        if e.src in lex_hits and e.dst not in results:
            p = id_to_page[e.dst]
            base = lex_hits[e.src][0]
            results[p.id] = QueryResult(
                id=p.id,
                title=p.title,
                summary=p.summary,
                path=p.path,
                score=base * 0.6 + cfg.curated_edge_weight,
                matched_fields=[],
                match_source="graph",
                reasons=[f"curated edge from {e.src}"],
                snippet=_snippet_for(p, q_tokens),
            )

    # Phase 2b: inferred edges, lighter weight, distinct class
    inferred_edges = [
        e for e in idx.edges if e.kind in ("inferred_backlink", "inferred_source")
    ]
    for e in inferred_edges:
        if e.src in lex_hits and e.dst not in results:
            p = id_to_page[e.dst]
            base = lex_hits[e.src][0]
            results[p.id] = QueryResult(
                id=p.id,
                title=p.title,
                summary=p.summary,
                path=p.path,
                score=base * 0.3 + cfg.inferred_edge_weight,
                matched_fields=[],
                match_source="graph",
                reasons=[f"inferred edge ({e.kind}) from {e.src}"],
                snippet=_snippet_for(p, q_tokens),
            )

    # Phase 3: recency tiebreaker (very weak)
    ranked = sorted(
        results.values(),
        key=lambda r: (-r.score, -id_to_page[r.id].updated_at.toordinal(), r.id),
    )
    return ranked[:limit]
