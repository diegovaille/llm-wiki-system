"""Deterministic lexical + link-graph retrieval.

Scoring is inverse-document-frequency weighted token overlap over a fixed
field set, so a term that appears on most pages ("user", "district") carries
almost no weight and a rare one carries a lot. Function words are stripped
from the question before scoring; without that, pages carrying long lists of
sentence-shaped aliases win any sentence-shaped question on "a", "how", "so"
and "they" alone (measured 2026-08-31: 1 of 15 newcomer questions hit the
right page in the top three; 10 to 11 of 15 after IDF and stopwords).
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from wiki_system.config import RetrievalConfig
from wiki_system.index import PageMeta, load_index


TOKEN_RE = re.compile(r"[A-Za-z0-9]+")

# Pages in these states never score and never arrive through graph expansion.
UNRETRIEVABLE_STATUSES = frozenset({"superseded"})

# Stripped from the question only. Page text keeps every token, which is
# equivalent for scoring (a stripped query term can never match) and saves a
# reindex when the list changes. The list was fitted against real prompts
# rather than taken from a generic English stoplist: it also drops a few
# content-shaped verbs ("add", "check", "set") that turned out to match
# nothing useful in a corpus about settings, drift checks and adding users.
STOPWORDS = frozenset(
    """
    a an and are as at be been but by can could did do does for from get got had has have
    how i if in into is it its just like make made may me might more most must my need not
    now of on once one only or other our out over own re same should since so some such than
    that the their them then there these they this those to too under until up use used using
    very was way we were what when where which while who why will with would you your about
    add adds after all also any because before both check doing done each few give go
    going help here new no off see set take tell think want yes
    """.split()
)

# Scored fields, in the order reasons are reported. Weights come from
# `[retrieval] field_weights`; a field missing from the config takes the
# default here.
DEFAULT_FIELD_WEIGHTS = {
    "title": 5.0,
    "aliases": 4.0,
    "domains": 3.0,
    "type": 2.0,
    "headings": 2.0,
    "body": 1.0,
    "sources": 1.0,
}


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


def query_tokens(question: str) -> set[str]:
    """The tokens of a question that take part in scoring."""
    return {t for t in _tokenize(question) if t not in STOPWORDS}


def _field_tokens(page: PageMeta) -> dict[str, set[str]]:
    def many(items: list[str]) -> set[str]:
        out: set[str] = set()
        for item in items:
            out.update(_tokenize(item))
        return out

    return {
        "title": set(_tokenize(page.title)),
        "aliases": many(page.aliases),
        "domains": many(page.domains),
        "type": set(_tokenize(page.type)),
        "headings": many(page.headings),
        "body": set(_tokenize(page.body)),
        "sources": many(page.sources),
    }


def _document_frequency(docs: list[dict[str, set[str]]]) -> Counter[str]:
    """How many pages carry each token in any scored field."""
    df: Counter[str] = Counter()
    for fields in docs:
        df.update(set().union(*fields.values()))
    return df


def _idf(term: str, df: Counter[str], n: int) -> float:
    """Inverse document frequency, BM25-shaped so it stays positive on a
    corpus of one page and falls to ~0 for a term on every page."""
    d = df.get(term, 0)
    return math.log(1.0 + (n - d + 0.5) / (d + 0.5))


def _score_lexical(
    fields: dict[str, set[str]],
    q_tokens: set[str],
    weights: dict[str, float],
    df: Counter[str],
    n: int,
) -> tuple[float, list[str], list[str]]:
    score = 0.0
    matched: list[str] = []
    reasons: list[str] = []
    for name, default in DEFAULT_FIELD_WEIGHTS.items():
        hit = q_tokens & fields[name]
        if not hit:
            continue
        weight = weights.get(name, default)
        if name == "type":
            # One token, scored once: a page is of one type.
            contribution = weight * _idf(next(iter(hit)), df, n)
        else:
            contribution = weight * sum(_idf(t, df, n) for t in hit)
        score += contribution
        matched.append(name)
        reasons.append(f"{name} match: {sorted(hit)}")
    return score, matched, reasons


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
    pages = [p for p in idx.pages if p.status not in UNRETRIEVABLE_STATUSES]
    q_tokens = query_tokens(question)
    if not pages or not q_tokens:
        return []

    docs = [_field_tokens(p) for p in pages]
    df = _document_frequency(docs)
    n = len(pages)

    # Phase 1: lexical scoring
    lex_hits: dict[str, tuple[float, list[str], list[str]]] = {}
    for page, fields in zip(pages, docs):
        s, matched, reasons = _score_lexical(fields, q_tokens, cfg.field_weights, df, n)
        if s > 0:
            lex_hits[page.id] = (s, matched, reasons)

    results: dict[str, QueryResult] = {}
    id_to_page = {p.id: p for p in pages}

    for pid, (score, matched, reasons) in lex_hits.items():
        p = id_to_page[pid]
        results[pid] = QueryResult(
            id=p.id,
            title=p.title,
            summary=p.summary,
            path=p.path,
            score=score,
            matched_fields=matched,
            match_source="lexical",
            reasons=list(reasons),
            snippet=_snippet_for(p, q_tokens),
        )

    # Phase 2: 1-hop graph expansion. A neighbor that did not match the
    # question scores min(source * factor + edge_weight, source): it can
    # outrank weaker direct hits but never the page that led to it, and never
    # a sibling neighbor of the same source that did match the question -
    # four matched terms are better evidence than zero terms plus an edge.
    # Direct matches keep their own scores: lifting them to the neighbor
    # score was measured at -3 newcomer hits, because it amplifies the top
    # hit's neighborhood over the right answer at rank two or three.
    curated = [e for e in idx.edges if e.kind == "curated"]
    inferred = [e for e in idx.edges if e.kind in ("inferred_backlink", "inferred_source")]
    matched_sibling: dict[str, float] = {}
    for e in curated + inferred:
        if e.src in lex_hits and e.dst in lex_hits:
            matched_sibling[e.src] = max(matched_sibling.get(e.src, 0.0), lex_hits[e.dst][0])

    def expand(kind_label: str, edges, factor: float, weight: float) -> None:
        for e in edges:
            if e.src not in lex_hits or e.dst in lex_hits or e.dst not in id_to_page:
                continue
            base = lex_hits[e.src][0]
            score = min(base * factor + weight, base)
            if e.src in matched_sibling:
                score = min(score, matched_sibling[e.src])
            existing = results.get(e.dst)
            if existing is not None:
                if score > existing.score:
                    existing.score = score
                    existing.reasons.append(f"{kind_label} from {e.src}")
                continue
            p = id_to_page[e.dst]
            results[p.id] = QueryResult(
                id=p.id,
                title=p.title,
                summary=p.summary,
                path=p.path,
                score=score,
                matched_fields=[],
                match_source="graph",
                reasons=[f"{kind_label} from {e.src}"],
                snippet=_snippet_for(p, q_tokens),
            )

    expand("curated edge", curated, 0.6, cfg.curated_edge_weight)
    expand("inferred edge", inferred, 0.3, cfg.inferred_edge_weight)

    # Phase 3: by score; on a tie a direct match beats a graph row (so a
    # neighbor capped at its source's or its sibling's score never passes
    # them); then recency (very weak), then id.
    ranked = sorted(
        results.values(),
        key=lambda r: (
            -r.score,
            r.match_source != "lexical",
            -id_to_page[r.id].updated_at.toordinal(),
            r.id,
        ),
    )
    return ranked[:limit]
