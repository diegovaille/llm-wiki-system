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
        project="demo",
        domains=domains or [],
        status=PageStatus.ACTIVE,
        aliases=aliases or [],
        sources=sources or ["session:2026-04-12-x"],
        related=related or [],
        updated_at=date(2026, 4, 12),
        confidence=Confidence.HIGH,
    )
    write_page(wiki_root, "demo", fm, body or f"# {id_}\n\nBody.\n")


def _index(wiki_root: Path):
    idx = build_index(wiki_root, "demo")
    save_index(wiki_root, "demo", idx)
    return idx


def test_empty_index_returns_no_results(wiki_root: Path):
    _index(wiki_root)
    results = run_query(wiki_root, "demo", "anything", RetrievalConfig(), limit=5)
    assert results == []


def test_exact_title_match_ranks_highest(wiki_root: Path):
    _mk(wiki_root, "demo-story-pipeline", title="Story Pipeline")
    _mk(wiki_root, "demo-unrelated", title="Unrelated")
    _index(wiki_root)
    results = run_query(wiki_root, "demo", "story pipeline", RetrievalConfig(), limit=5)
    assert results[0].id == "demo-story-pipeline"
    assert "title" in results[0].matched_fields
    assert results[0].match_source == "lexical"


def test_alias_match_scores_highly(wiki_root: Path):
    _mk(wiki_root, "demo-moderation", title="Moderation System", aliases=["content moderation"])
    _mk(wiki_root, "demo-other", title="Other Thing")
    _index(wiki_root)
    results = run_query(wiki_root, "demo", "content moderation", RetrievalConfig(), limit=5)
    assert results[0].id == "demo-moderation"
    assert "aliases" in results[0].matched_fields


def test_domain_match_contributes(wiki_root: Path):
    _mk(wiki_root, "demo-alpha", title="Alpha", domains=["pipeline"])
    _mk(wiki_root, "demo-beta", title="Beta", domains=["unrelated"])
    _index(wiki_root)
    results = run_query(wiki_root, "demo", "pipeline", RetrievalConfig(), limit=5)
    assert results[0].id == "demo-alpha"
    assert "domains" in results[0].matched_fields


def test_body_token_match_contributes(wiki_root: Path):
    _mk(wiki_root, "demo-alpha", title="Alpha", body="# Alpha\n\nThe moderation engine handles...\n")
    _mk(wiki_root, "demo-beta", title="Beta", body="# Beta\n\nUnrelated content.\n")
    _index(wiki_root)
    results = run_query(wiki_root, "demo", "moderation engine", RetrievalConfig(), limit=5)
    assert results[0].id == "demo-alpha"
    assert "body" in results[0].matched_fields


def test_curated_edge_expansion_returns_1_hop_neighbors(wiki_root: Path):
    _mk(wiki_root, "demo-alpha", title="Alpha", related=["demo-beta"], domains=["pipeline"])
    _mk(wiki_root, "demo-beta", title="Beta", domains=["unrelated"])
    _index(wiki_root)
    # Query matches alpha by title; beta should come along via curated edge.
    results = run_query(wiki_root, "demo", "alpha", RetrievalConfig(), limit=5)
    ids = [r.id for r in results]
    assert "demo-alpha" in ids
    assert "demo-beta" in ids
    beta = next(r for r in results if r.id == "demo-beta")
    assert beta.match_source == "graph"


def test_inferred_edge_distinct_from_curated(wiki_root: Path):
    _mk(wiki_root, "demo-alpha", title="Alpha", sources=["docs/shared.md"])
    _mk(wiki_root, "demo-beta", title="Beta", sources=["docs/shared.md"])
    _index(wiki_root)
    results = run_query(wiki_root, "demo", "alpha", RetrievalConfig(), limit=5)
    ids = [r.id for r in results]
    assert "demo-alpha" in ids
    # Beta must appear via the bidirectional inferred_source edge.
    assert "demo-beta" in ids
    beta = next(r for r in results if r.id == "demo-beta")
    assert beta.match_source == "graph"
    assert any("inferred" in reason for reason in beta.reasons)


def test_results_carry_reasons_and_snippet(wiki_root: Path):
    _mk(wiki_root, "demo-story-pipeline", title="Story Pipeline", body="# Story Pipeline\n\nThree stages.\n")
    _index(wiki_root)
    results = run_query(wiki_root, "demo", "story", RetrievalConfig(), limit=5)
    r = results[0]
    assert r.reasons, "expected non-empty reasons"
    assert r.snippet, "expected non-empty snippet"


# ---- 0.4.0: IDF, stopwords, sources, superseded ----------------------------


def test_function_words_do_not_carry_an_alias_heavy_page(wiki_root: Path):
    # An alias list made of sentences used to win any sentence-shaped
    # question on its function words alone.
    _mk(
        wiki_root,
        "demo-ci-orchestrator",
        title="Selective CI Orchestrator",
        aliases=[
            "how does the pipeline decide what to build",
            "why did a job get skipped so it can deploy",
            "what does ci do when they push",
            "can a new branch skip the build in a pr",
        ],
        body="# CI\n\nThe orchestrator gates jobs on changed paths.\n",
    )
    _mk(
        wiki_root,
        "demo-user-lifecycle",
        title="User Lifecycle and Invitations",
        body="# Accounts\n\nA new student gets an account when the invitation is consumed at first login.\n",
    )
    _index(wiki_root)
    results = run_query(
        wiki_root, "demo", "how does a new student get an account so they can log in",
        RetrievalConfig(), limit=3,
    )
    assert results[0].id == "demo-user-lifecycle"
    ci = next((r for r in results if r.id == "demo-ci-orchestrator"), None)
    assert ci is None or ci.match_source == "graph", ci and ci.reasons


def test_rare_terms_outweigh_common_ones(wiki_root: Path):
    for i in range(3):
        _mk(wiki_root, f"demo-common-{i}", title=f"Common {i}", body="# c\n\nalpha beta gamma\n")
    _mk(wiki_root, "demo-rare", title="Rare", body="# r\n\nalpha zeta\n")
    _index(wiki_root)
    # Two matches on near-universal terms lose to one match on a rare term.
    results = run_query(wiki_root, "demo", "beta gamma zeta", RetrievalConfig(), limit=5)
    assert results[0].id == "demo-rare"


def test_sources_field_reaches_a_ticket_id(wiki_root: Path):
    _mk(wiki_root, "demo-pagination", title="SDK List Pagination", sources=["linear:CLA-1810"],
        body="# Pagination\n\nIterate the response.\n")
    _mk(wiki_root, "demo-other", title="Other", sources=["linear:CLA-2000"],
        body="# Other\n\nCLA tickets are named in the body here.\n")
    _index(wiki_root)
    results = run_query(wiki_root, "demo", "CLA-1810", RetrievalConfig(), limit=5)
    assert results[0].id == "demo-pagination"
    assert "sources" in results[0].matched_fields


def test_superseded_pages_never_score_or_expand(wiki_root: Path):
    fm_old = PageFrontmatter(
        id="demo-old-story-pipeline", title="Story Pipeline", summary="old",
        type=PageType.SYSTEM, project="demo", domains=[], status=PageStatus.SUPERSEDED,
        aliases=[], sources=["session:2026-04-12-x"], related=["demo-neighbor"],
        updated_at=date(2026, 4, 12), confidence=Confidence.HIGH,
        superseded_by="demo-story-pipeline",
    )
    write_page(wiki_root, "demo", fm_old, "# old\n\nStory pipeline, old.\n")
    _mk(wiki_root, "demo-story-pipeline", title="Story Pipeline", sources=["session:a"])
    _mk(wiki_root, "demo-neighbor", title="Neighbor", sources=["session:b"])
    _index(wiki_root)
    ids = [r.id for r in run_query(wiki_root, "demo", "story pipeline", RetrievalConfig(), limit=5)]
    assert ids[0] == "demo-story-pipeline"
    assert "demo-old-story-pipeline" not in ids
    assert "demo-neighbor" not in ids  # its only edge came from the superseded page


def test_a_question_of_only_stopwords_returns_nothing(wiki_root: Path):
    _mk(wiki_root, "demo-story-pipeline", title="Story Pipeline")
    _index(wiki_root)
    assert run_query(wiki_root, "demo", "how do I", RetrievalConfig(), limit=5) == []


def test_single_page_corpus_still_retrieves(wiki_root: Path):
    # IDF must stay positive when every page (of one) carries the term.
    _mk(wiki_root, "demo-story-pipeline", title="Story Pipeline")
    _index(wiki_root)
    results = run_query(wiki_root, "demo", "story", RetrievalConfig(), limit=5)
    assert [r.id for r in results] == ["demo-story-pipeline"]


def test_graph_neighbor_never_outranks_its_source_but_can_beat_weak_hits(wiki_root: Path):
    # "story pipeline" matches alpha on title (strong), and gamma on one body
    # token (weak). beta is only alpha's curated neighbor.
    _mk(wiki_root, "demo-alpha", title="Story Pipeline", related=["demo-beta"], sources=["s:a"])
    _mk(wiki_root, "demo-beta", title="Beta", sources=["s:b"])
    _mk(wiki_root, "demo-gamma", title="Gamma", sources=["s:c"], body="# g\n\nA pipeline of sorts.\n")
    _index(wiki_root)
    results = run_query(wiki_root, "demo", "story pipeline", RetrievalConfig(), limit=5)
    ids = [r.id for r in results]
    assert ids[0] == "demo-alpha"
    assert ids.index("demo-beta") < ids.index("demo-gamma")
    beta = next(r for r in results if r.id == "demo-beta")
    assert beta.score <= results[0].score
