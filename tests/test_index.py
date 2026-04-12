from datetime import date
from pathlib import Path

from wiki_system.index import IndexData, build_index, render_views, save_index, load_index
from wiki_system.schema import (
    Confidence,
    PageFrontmatter,
    PageStatus,
    PageType,
)
from wiki_system.storage import write_page


def _write_page(wiki_root: Path, id_: str, *, related: list[str] | None = None, sources: list[str] | None = None, type_: PageType = PageType.SYSTEM, domains: list[str] | None = None) -> None:
    fm = PageFrontmatter(
        id=id_,
        title=id_.replace("-", " ").title(),
        summary=f"Summary for {id_}",
        type=type_,
        project="luminavine",
        domains=domains or ["pipeline"],
        status=PageStatus.ACTIVE,
        aliases=[],
        sources=sources or ["session:2026-04-12-x"],
        related=related or [],
        updated_at=date(2026, 4, 12),
        confidence=Confidence.HIGH,
    )
    write_page(wiki_root, "luminavine", fm, f"# {id_}\n\n## Heading one\n\nBody.\n")


def test_build_index_single_page(wiki_root: Path):
    _write_page(wiki_root, "lv-alpha")
    idx = build_index(wiki_root, "luminavine")
    assert isinstance(idx, IndexData)
    assert len(idx.pages) == 1
    assert idx.pages[0].id == "lv-alpha"


def test_curated_edges_extracted(wiki_root: Path):
    _write_page(wiki_root, "lv-alpha", related=["lv-beta"])
    _write_page(wiki_root, "lv-beta")
    idx = build_index(wiki_root, "luminavine")
    edges = {(e.src, e.dst, e.kind) for e in idx.edges}
    assert ("lv-alpha", "lv-beta", "curated") in edges


def test_inferred_backlinks_computed(wiki_root: Path):
    _write_page(wiki_root, "lv-alpha", related=["lv-beta"])
    _write_page(wiki_root, "lv-beta")
    idx = build_index(wiki_root, "luminavine")
    inferred = {(e.src, e.dst, e.kind) for e in idx.edges if e.kind == "inferred_backlink"}
    assert ("lv-beta", "lv-alpha", "inferred_backlink") in inferred


def test_inferred_source_overlap_edges(wiki_root: Path):
    _write_page(wiki_root, "lv-alpha", sources=["docs/a.md", "docs/b.md"])
    _write_page(wiki_root, "lv-beta", sources=["docs/b.md"])
    _write_page(wiki_root, "lv-gamma", sources=["docs/x.md"])
    idx = build_index(wiki_root, "luminavine")
    overlap = {(e.src, e.dst, e.kind) for e in idx.edges if e.kind == "inferred_source"}
    assert ("lv-alpha", "lv-beta", "inferred_source") in overlap
    assert ("lv-beta", "lv-alpha", "inferred_source") in overlap
    # gamma shares nothing
    gamma = [e for e in idx.edges if "lv-gamma" in (e.src, e.dst) and e.kind == "inferred_source"]
    assert gamma == []


def test_save_and_load_index_round_trip(wiki_root: Path):
    _write_page(wiki_root, "lv-alpha")
    idx = build_index(wiki_root, "luminavine")
    save_index(wiki_root, "luminavine", idx)
    loaded = load_index(wiki_root, "luminavine")
    assert loaded.pages[0].id == "lv-alpha"


def test_render_views_creates_index_md(wiki_root: Path):
    _write_page(wiki_root, "lv-alpha", type_=PageType.SYSTEM)
    _write_page(wiki_root, "lv-beta", type_=PageType.WORKFLOW)
    idx = build_index(wiki_root, "luminavine")
    render_views(wiki_root, "luminavine", idx, repo_path="/tmp/luminavine-repo")
    index_view = (wiki_root / "luminavine" / "views" / "index.md").read_text()
    assert "lv-alpha" in index_view
    assert "lv-beta" in index_view
    assert "Do not edit by hand" in index_view


def test_render_views_is_single_writer(wiki_root: Path):
    _write_page(wiki_root, "lv-alpha")
    idx = build_index(wiki_root, "luminavine")
    render_views(wiki_root, "luminavine", idx, repo_path="/tmp/x")
    view_path = wiki_root / "luminavine" / "views" / "index.md"
    view_path.write_text("HAND EDITED — should be overwritten")
    render_views(wiki_root, "luminavine", idx, repo_path="/tmp/x")
    assert "HAND EDITED" not in view_path.read_text()
    assert "lv-alpha" in view_path.read_text()


def test_heading_extraction(wiki_root: Path):
    _write_page(wiki_root, "lv-alpha")
    idx = build_index(wiki_root, "luminavine")
    page_meta = next(p for p in idx.pages if p.id == "lv-alpha")
    assert "Heading one" in page_meta.headings
