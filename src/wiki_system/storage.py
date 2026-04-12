"""Filesystem read/write for pages, staged files, and manifest."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from wiki_system._yaml import dumps, loads
from wiki_system.schema import PageFrontmatter, StagedFile


FRONTMATTER_DELIM = "---"


def _split_frontmatter(text: str) -> tuple[str, str]:
    """Split a markdown file with YAML frontmatter into (yaml_text, body)."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip() != FRONTMATTER_DELIM:
        raise ValueError("file does not begin with '---' frontmatter delimiter")
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].rstrip() == FRONTMATTER_DELIM:
            end_idx = i
            break
    if end_idx is None:
        raise ValueError("unterminated frontmatter (no closing '---')")
    yaml_text = "".join(lines[1:end_idx])
    body = "".join(lines[end_idx + 1 :])
    if body.startswith("\n"):
        body = body[1:]
    return yaml_text, body


def _join_frontmatter(yaml_text: str, body: str) -> str:
    out = f"{FRONTMATTER_DELIM}\n{yaml_text}"
    if not yaml_text.endswith("\n"):
        out += "\n"
    out += f"{FRONTMATTER_DELIM}\n"
    if body:
        out += "\n" + body
    return out


def _pages_dir(wiki_root: Path, project: str) -> Path:
    return wiki_root / project / "pages"


def _staging_dir(wiki_root: Path, project: str) -> Path:
    return wiki_root / project / "staging"


def _sources_dir(wiki_root: Path, project: str) -> Path:
    return wiki_root / project / "sources"


# ---------- Pages ----------


def write_page(
    wiki_root: Path, project: str, fm: PageFrontmatter, body: str
) -> Path:
    _pages_dir(wiki_root, project).mkdir(parents=True, exist_ok=True)
    path = _pages_dir(wiki_root, project) / f"{fm.id}.md"
    yaml_text = dumps(fm.model_dump(mode="json"))
    text = _join_frontmatter(yaml_text, body)
    atomic_write(path, text)
    return path


def read_page(path: Path) -> tuple[PageFrontmatter, str]:
    text = path.read_text()
    yaml_text, body = _split_frontmatter(text)
    data = loads(yaml_text)
    fm = PageFrontmatter.model_validate(data)
    return fm, body


def list_pages(wiki_root: Path, project: str) -> list[Path]:
    d = _pages_dir(wiki_root, project)
    if not d.exists():
        return []
    return sorted(p for p in d.glob("*.md") if p.is_file())


# ---------- Staged files ----------


def write_staged(
    wiki_root: Path,
    project: str,
    staged: StagedFile,
    body: str,
    slug: str,
) -> Path:
    _staging_dir(wiki_root, project).mkdir(parents=True, exist_ok=True)
    ts = staged.created_at.strftime("%Y-%m-%d-%H%M%S")
    path = _staging_dir(wiki_root, project) / f"{ts}-{slug}.md"
    yaml_text = dumps(staged.model_dump(mode="json", exclude_none=True))
    text = _join_frontmatter(yaml_text, body)
    atomic_write(path, text)
    return path


def read_staged(path: Path) -> tuple[StagedFile, str]:
    text = path.read_text()
    yaml_text, body = _split_frontmatter(text)
    data = loads(yaml_text)
    staged = StagedFile.model_validate(data)
    return staged, body


def list_staged(wiki_root: Path, project: str) -> list[Path]:
    d = _staging_dir(wiki_root, project)
    if not d.exists():
        return []
    # Exclude the .archive subdirectory
    return sorted(
        p for p in d.glob("*.md") if p.is_file() and ".archive" not in p.parts
    )


def archive_staged(wiki_root: Path, project: str, staged_path: Path) -> Path:
    archive_dir = _staging_dir(wiki_root, project) / ".archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    dest = archive_dir / staged_path.name
    staged_path.rename(dest)
    return dest


# ---------- Manifest ----------


def append_manifest(wiki_root: Path, project: str, entry: dict[str, Any]) -> None:
    _sources_dir(wiki_root, project).mkdir(parents=True, exist_ok=True)
    path = _sources_dir(wiki_root, project) / "manifest.jsonl"
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


# ---------- Utilities ----------


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    tmp.replace(path)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
