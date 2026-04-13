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
        project="demo",
        domains=domains or ["pipeline"],
        status=PageStatus.ACTIVE,
        aliases=[],
        sources=sources or ["session:2026-04-12-x"],
        related=related or [],
        updated_at=date(2026, 4, 12),
        confidence=Confidence.HIGH,
    )
    write_page(wiki_root, "demo", fm, f"# {id_}\n\n## Heading one\n\nBody.\n")


def test_build_index_single_page(wiki_root: Path):
    _write_page(wiki_root, "demo-alpha")
    idx = build_index(wiki_root, "demo")
    assert isinstance(idx, IndexData)
    assert len(idx.pages) == 1
    assert idx.pages[0].id == "demo-alpha"


def test_curated_edges_extracted(wiki_root: Path):
    _write_page(wiki_root, "demo-alpha", related=["demo-beta"])
    _write_page(wiki_root, "demo-beta")
    idx = build_index(wiki_root, "demo")
    edges = {(e.src, e.dst, e.kind) for e in idx.edges}
    assert ("demo-alpha", "demo-beta", "curated") in edges


def test_inferred_backlinks_computed(wiki_root: Path):
    _write_page(wiki_root, "demo-alpha", related=["demo-beta"])
    _write_page(wiki_root, "demo-beta")
    idx = build_index(wiki_root, "demo")
    inferred = {(e.src, e.dst, e.kind) for e in idx.edges if e.kind == "inferred_backlink"}
    assert ("demo-beta", "demo-alpha", "inferred_backlink") in inferred


def test_inferred_source_overlap_edges(wiki_root: Path):
    _write_page(wiki_root, "demo-alpha", sources=["docs/a.md", "docs/b.md"])
    _write_page(wiki_root, "demo-beta", sources=["docs/b.md"])
    _write_page(wiki_root, "demo-gamma", sources=["docs/x.md"])
    idx = build_index(wiki_root, "demo")
    overlap = {(e.src, e.dst, e.kind) for e in idx.edges if e.kind == "inferred_source"}
    assert ("demo-alpha", "demo-beta", "inferred_source") in overlap
    assert ("demo-beta", "demo-alpha", "inferred_source") in overlap
    # gamma shares nothing
    gamma = [e for e in idx.edges if "demo-gamma" in (e.src, e.dst) and e.kind == "inferred_source"]
    assert gamma == []


def test_save_and_load_index_round_trip(wiki_root: Path):
    _write_page(wiki_root, "demo-alpha", related=["demo-beta"])
    _write_page(wiki_root, "demo-beta")
    idx = build_index(wiki_root, "demo")
    save_index(wiki_root, "demo", idx)
    loaded = load_index(wiki_root, "demo")
    assert [p.id for p in loaded.pages] == [p.id for p in idx.pages]
    assert loaded.pages[0].body == idx.pages[0].body
    assert loaded.built_at == idx.built_at
    assert [(e.src, e.dst, e.kind) for e in loaded.edges] == [(e.src, e.dst, e.kind) for e in idx.edges]


def test_render_views_creates_index_md(wiki_root: Path):
    _write_page(wiki_root, "demo-alpha", type_=PageType.SYSTEM)
    _write_page(wiki_root, "demo-beta", type_=PageType.WORKFLOW)
    idx = build_index(wiki_root, "demo")
    render_views(wiki_root, "demo", idx, repo_path="/tmp/demo-repo")
    index_view = (wiki_root / "demo" / "views" / "index.md").read_text()
    assert "demo-alpha" in index_view
    assert "demo-beta" in index_view
    assert "Do not edit by hand" in index_view


def test_render_views_is_single_writer(wiki_root: Path):
    _write_page(wiki_root, "demo-alpha")
    idx = build_index(wiki_root, "demo")
    render_views(wiki_root, "demo", idx, repo_path="/tmp/x")
    view_path = wiki_root / "demo" / "views" / "index.md"
    view_path.write_text("HAND EDITED — should be overwritten")
    render_views(wiki_root, "demo", idx, repo_path="/tmp/x")
    assert "HAND EDITED" not in view_path.read_text()
    assert "demo-alpha" in view_path.read_text()


def test_heading_extraction(wiki_root: Path):
    _write_page(wiki_root, "demo-alpha")
    idx = build_index(wiki_root, "demo")
    page_meta = next(p for p in idx.pages if p.id == "demo-alpha")
    assert "Heading one" in page_meta.headings


def test_views_emit_relative_markdown_links_to_pages(wiki_root: Path):
    """Views must use `../pages/<id>.md` for links so standard markdown
    renderers (Obsidian, VS Code preview, GitHub, mkdocs) can resolve
    them. Bare-id links like `[Title](demo-alpha)` only happen to work
    in Obsidian's fuzzy resolver and break everywhere else.
    """
    _write_page(wiki_root, "demo-alpha", type_=PageType.SYSTEM, domains=["pipeline"])
    _write_page(wiki_root, "demo-beta", type_=PageType.WORKFLOW, domains=["workflow"])
    idx = build_index(wiki_root, "demo")
    render_views(wiki_root, "demo", idx, repo_path="/tmp/x")

    for view_name in ("index.md", "by-type.md", "by-domain.md"):
        content = (wiki_root / "demo" / "views" / view_name).read_text()
        # Every page must appear as a relative link to ../pages/<id>.md
        assert "../pages/demo-alpha.md" in content, f"{view_name} missing demo-alpha link"
        assert "../pages/demo-beta.md" in content, f"{view_name} missing demo-beta link"


def test_self_related_yields_no_curated_edge(wiki_root: Path):
    _write_page(wiki_root, "demo-alpha", related=["demo-alpha"])
    idx = build_index(wiki_root, "demo")
    assert all(e.src != e.dst for e in idx.edges)


def test_load_index_rejects_stale_schema(wiki_root: Path, tmp_path: Path):
    import json
    import pytest
    project_dir = wiki_root / "demo"
    project_dir.mkdir(parents=True, exist_ok=True)
    stale = {"schema_version": 0, "project": "demo", "built_at": "2026-04-12T00:00:00+00:00", "pages": [], "edges": []}
    (project_dir / ".wiki-index.json").write_text(json.dumps(stale))
    with pytest.raises(ValueError, match="stale wiki index"):
        load_index(wiki_root, "demo")
