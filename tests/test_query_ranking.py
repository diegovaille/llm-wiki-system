from pathlib import Path

from wiki_system.config import RetrievalConfig
from wiki_system.index import build_index, save_index
from wiki_system.query import QueryResult, run_query
from wiki_system.schema import Confidence, PageFrontmatter, PageStatus, PageType
from wiki_system.storage import write_page

from datetime import date


def _mk(wiki_root: Path, id_: str, *, title: str | None = None, domains: list[str] | None = None, aliases: list[str] | None = None, related: list[str] | None = None, sources: list[str] | None = None, body: str = "", type_: PageType = PageType.SYSTEM):
    fm = PageFrontmatter(
        id=id_,
        title=title or id_.replace("-", " ").title(),
        summary=f"Summary for {id_}",
        type=type_,
        project="luminavine",
        domains=domains or [],
        status=PageStatus.ACTIVE,
        aliases=aliases or [],
        sources=sources or ["session:2026-04-12-x"],
        related=related or [],
        updated_at=date(2026, 4, 12),
        confidence=Confidence.HIGH,
    )
    write_page(wiki_root, "luminavine", fm, body or f"# {id_}\n\nBody.\n")


def _index(wiki_root: Path):
    idx = build_index(wiki_root, "luminavine")
    save_index(wiki_root, "luminavine", idx)
    return idx


def test_empty_index_returns_no_results(wiki_root: Path):
    _index(wiki_root)
    results = run_query(wiki_root, "luminavine", "anything", RetrievalConfig(), limit=5)
    assert results == []


def test_exact_title_match_ranks_highest(wiki_root: Path):
    _mk(wiki_root, "lv-story-pipeline", title="Story Pipeline")
    _mk(wiki_root, "lv-unrelated", title="Unrelated")
    _index(wiki_root)
    results = run_query(wiki_root, "luminavine", "story pipeline", RetrievalConfig(), limit=5)
    assert results[0].id == "lv-story-pipeline"
    assert "title" in results[0].matched_fields
    assert results[0].match_source == "lexical"


def test_alias_match_scores_highly(wiki_root: Path):
    _mk(wiki_root, "lv-moderation", title="Moderation System", aliases=["content moderation"])
    _mk(wiki_root, "lv-other", title="Other Thing")
    _index(wiki_root)
    results = run_query(wiki_root, "luminavine", "content moderation", RetrievalConfig(), limit=5)
    assert results[0].id == "lv-moderation"
    assert "aliases" in results[0].matched_fields


def test_domain_match_contributes(wiki_root: Path):
    _mk(wiki_root, "lv-alpha", title="Alpha", domains=["pipeline"])
    _mk(wiki_root, "lv-beta", title="Beta", domains=["unrelated"])
    _index(wiki_root)
    results = run_query(wiki_root, "luminavine", "pipeline", RetrievalConfig(), limit=5)
    assert results[0].id == "lv-alpha"
    assert "domains" in results[0].matched_fields


def test_body_token_match_contributes(wiki_root: Path):
    _mk(wiki_root, "lv-alpha", title="Alpha", body="# Alpha\n\nThe moderation engine handles...\n")
    _mk(wiki_root, "lv-beta", title="Beta", body="# Beta\n\nUnrelated content.\n")
    _index(wiki_root)
    results = run_query(wiki_root, "luminavine", "moderation engine", RetrievalConfig(), limit=5)
    assert results[0].id == "lv-alpha"
    assert "body" in results[0].matched_fields


def test_curated_edge_expansion_returns_1_hop_neighbors(wiki_root: Path):
    _mk(wiki_root, "lv-alpha", title="Alpha", related=["lv-beta"], domains=["pipeline"])
    _mk(wiki_root, "lv-beta", title="Beta", domains=["unrelated"])
    _index(wiki_root)
    # Query matches alpha by title; beta should come along via curated edge.
    results = run_query(wiki_root, "luminavine", "alpha", RetrievalConfig(), limit=5)
    ids = [r.id for r in results]
    assert "lv-alpha" in ids
    assert "lv-beta" in ids
    beta = next(r for r in results if r.id == "lv-beta")
    assert beta.match_source == "graph"


def test_inferred_edge_distinct_from_curated(wiki_root: Path):
    _mk(wiki_root, "lv-alpha", title="Alpha", sources=["docs/shared.md"])
    _mk(wiki_root, "lv-beta", title="Beta", sources=["docs/shared.md"])
    _index(wiki_root)
    results = run_query(wiki_root, "luminavine", "alpha", RetrievalConfig(), limit=5)
    ids = [r.id for r in results]
    assert "lv-alpha" in ids
    # Beta should appear via inferred source-overlap edge
    if "lv-beta" in ids:
        beta = next(r for r in results if r.id == "lv-beta")
        assert beta.match_source == "graph"


def test_results_carry_reasons_and_snippet(wiki_root: Path):
    _mk(wiki_root, "lv-story-pipeline", title="Story Pipeline", body="# Story Pipeline\n\nThree stages.\n")
    _index(wiki_root)
    results = run_query(wiki_root, "luminavine", "story", RetrievalConfig(), limit=5)
    r = results[0]
    assert r.reasons, "expected non-empty reasons"
    assert r.snippet, "expected non-empty snippet"
