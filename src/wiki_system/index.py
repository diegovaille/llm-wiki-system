"""Retrieval index construction and view generation."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from wiki_system.schema import PageFrontmatter
from wiki_system.storage import atomic_write, list_pages, read_page


HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)


@dataclass
class PageMeta:
    id: str
    title: str
    summary: str
    type: str
    domains: list[str]
    aliases: list[str]
    sources: list[str]
    related: list[str]
    status: str
    updated_at: date
    path: str
    headings: list[str]
    body: str


@dataclass
class Edge:
    src: str
    dst: str
    kind: str  # "curated" | "inferred_backlink" | "inferred_source"


@dataclass
class IndexData:
    project: str
    pages: list[PageMeta] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    built_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def build_index(wiki_root: Path, project: str) -> IndexData:
    idx = IndexData(project=project)
    for path in list_pages(wiki_root, project):
        fm, body = read_page(path)
        idx.pages.append(_page_meta_from(fm, body, path))
    _compute_edges(idx)
    return idx


def _page_meta_from(fm: PageFrontmatter, body: str, path: Path) -> PageMeta:
    return PageMeta(
        id=fm.id,
        title=fm.title,
        summary=fm.summary,
        type=fm.type,
        domains=list(fm.domains),
        aliases=list(fm.aliases),
        sources=list(fm.sources),
        related=list(fm.related),
        status=fm.status,
        updated_at=fm.updated_at,
        path=str(path),
        headings=HEADING_RE.findall(body),
        body=body,
    )


def _compute_edges(idx: IndexData) -> None:
    ids = {p.id for p in idx.pages}
    # Curated: related: list
    for p in idx.pages:
        for target in p.related:
            if target != p.id and target in ids:
                idx.edges.append(Edge(src=p.id, dst=target, kind="curated"))
    # Inferred backlinks: reverse of curated
    for e in list(idx.edges):
        if e.kind == "curated":
            idx.edges.append(
                Edge(src=e.dst, dst=e.src, kind="inferred_backlink")
            )
    # Inferred source overlap: pages sharing at least one source
    for i, a in enumerate(idx.pages):
        for b in idx.pages[i + 1 :]:
            if set(a.sources) & set(b.sources):
                idx.edges.append(Edge(src=a.id, dst=b.id, kind="inferred_source"))
                idx.edges.append(Edge(src=b.id, dst=a.id, kind="inferred_source"))


def save_index(wiki_root: Path, project: str, idx: IndexData) -> Path:
    path = wiki_root / project / ".wiki-index.json"
    payload = {
        "schema_version": 1,
        "project": idx.project,
        "built_at": idx.built_at.isoformat(),
        "pages": [
            {
                "id": p.id,
                "title": p.title,
                "summary": p.summary,
                "type": p.type,
                "domains": p.domains,
                "aliases": p.aliases,
                "sources": p.sources,
                "related": p.related,
                "status": p.status,
                "updated_at": p.updated_at.isoformat(),
                "path": p.path,
                "headings": p.headings,
                "body": p.body,
            }
            for p in idx.pages
        ],
        "edges": [
            {"src": e.src, "dst": e.dst, "kind": e.kind} for e in idx.edges
        ],
    }
    atomic_write(path, json.dumps(payload, indent=2))
    return path


def load_index(wiki_root: Path, project: str) -> IndexData:
    path = wiki_root / project / ".wiki-index.json"
    payload = json.loads(path.read_text())
    version = payload.get("schema_version")
    if version != 1:
        raise ValueError(
            f"stale wiki index at {path} (schema_version={version}); "
            "run `wiki index` to rebuild"
        )
    idx = IndexData(
        project=payload["project"],
        built_at=datetime.fromisoformat(payload["built_at"]),
    )
    for p in payload["pages"]:
        idx.pages.append(
            PageMeta(
                id=p["id"],
                title=p["title"],
                summary=p["summary"],
                type=p["type"],
                domains=p["domains"],
                aliases=p["aliases"],
                sources=p["sources"],
                related=p["related"],
                status=p["status"],
                updated_at=date.fromisoformat(p["updated_at"]),
                path=p["path"],
                headings=p["headings"],
                body=p["body"],
            )
        )
    for e in payload["edges"]:
        idx.edges.append(Edge(src=e["src"], dst=e["dst"], kind=e["kind"]))
    return idx


def render_views(
    wiki_root: Path, project: str, idx: IndexData, *, repo_path: str
) -> None:
    views_dir = wiki_root / project / "views"
    views_dir.mkdir(parents=True, exist_ok=True)
    _render_index_view(views_dir / "index.md", idx, project, repo_path)
    _render_by_type_view(views_dir / "by-type.md", idx, project)
    _render_by_domain_view(views_dir / "by-domain.md", idx, project)


def _render_index_view(path: Path, idx: IndexData, project: str, repo_path: str) -> None:
    by_type: dict[str, list[PageMeta]] = {}
    for p in idx.pages:
        by_type.setdefault(p.type, []).append(p)
    all_domains = sorted({d for p in idx.pages for d in p.domains})

    lines: list[str] = [
        f"# {project} Wiki — Map",
        "",
        f"This project's wiki lives at `{wiki_root_rel(path, project)}/`.",
        "",
        f"**What's here:** {len(idx.pages)} canonical page(s) "
        f"covering {len(all_domains)} domain(s).",
        "",
        "## Canonical pages by type",
        "",
    ]
    for type_name in sorted(by_type):
        lines.append(f"### {type_name}")
        lines.append("")
        for p in sorted(by_type[type_name], key=lambda x: x.id):
            summary = p.summary or ""
            lines.append(
                f"- [**{p.title}**](../pages/{p.id}.md) "
                f"(`{p.id}`) — {summary}"
            )
        lines.append("")
    lines.extend(
        [
            "## How to use",
            "",
            f"- `wiki query {project} \"your question\"` — search this wiki",
            "- `/wiki-capture` — capture a session learning (agent mode)",
            "- `/wiki-review` — see pending staged items",
            f"- Fall back to `{repo_path}/docs/` only when the wiki doesn't answer",
            "",
            f"Generated: {idx.built_at.isoformat()}. "
            "Do not edit by hand — regenerated by `wiki index`.",
            "",
        ]
    )
    atomic_write(path, "\n".join(lines))


def _render_by_type_view(path: Path, idx: IndexData, project: str) -> None:
    by_type: dict[str, list[PageMeta]] = {}
    for p in idx.pages:
        by_type.setdefault(p.type, []).append(p)
    lines = [f"# {project} — Pages by type", ""]
    for type_name in sorted(by_type):
        lines.append(f"## {type_name}")
        lines.append("")
        for p in sorted(by_type[type_name], key=lambda x: x.id):
            lines.append(f"- [{p.title}](../pages/{p.id}.md) — {p.summary}")
        lines.append("")
    lines.append("Do not edit by hand — regenerated by `wiki index`.")
    atomic_write(path, "\n".join(lines))


def _render_by_domain_view(path: Path, idx: IndexData, project: str) -> None:
    by_domain: dict[str, list[PageMeta]] = {}
    for p in idx.pages:
        for d in p.domains:
            by_domain.setdefault(d, []).append(p)
    lines = [f"# {project} — Pages by domain", ""]
    for domain in sorted(by_domain):
        lines.append(f"## {domain}")
        lines.append("")
        for p in sorted(by_domain[domain], key=lambda x: x.id):
            lines.append(f"- [{p.title}](../pages/{p.id}.md) — {p.summary}")
        lines.append("")
    lines.append("Do not edit by hand — regenerated by `wiki index`.")
    atomic_write(path, "\n".join(lines))


def wiki_root_rel(view_path: Path, project: str) -> str:
    # For the rendered view, point at the project subtree root
    return f"{project}"
