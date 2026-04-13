"""Register project artifacts as raw staged files for later capture.

`wiki sync` reads the `[[projects]] source_globs` from `wiki.config.toml`,
walks the project repo, and creates a `state: raw` staged file per matched
artifact. Subsequent `/wiki-capture --from-staged=<path>` upgrades each raw
file into a proposed canonical page; `wiki promote` canonicalizes them.

This is the minimal v0.1.1 operational bridge between existing repo
documentation and the wiki. v0.2 will add hook-driven sync triggers and
content-hash dedupe; this module is path-dedupe only.

Design notes:
- Safe default: existing raw files for a given source_artifact are
  skipped. Callers pass `--force` to re-sync.
- Scoped `--force`: combined with `--path`, `--force` only deletes raw
  files whose `source_artifact` falls under the path filter. Raw files
  for unrelated subtrees are preserved.
- UTF-8 decode is required. Files that can't be decoded are reported as
  warnings and not staged — binary artifacts aren't eligible for wiki
  pages in v0.1.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from wiki_system.config import ProjectConfig, SyncConfig
from wiki_system.schema import (
    RawBodyMode,
    StagedFile,
    StagedFileOrigin,
    StagedState,
)
from wiki_system.storage import list_staged, read_staged, utc_now, write_staged


_SLUG_SAFE_RE = re.compile(r"[^a-z0-9]+")


@dataclass
class SyncResult:
    """What `wiki sync` did on a single run."""

    created: list[Path] = field(default_factory=list)
    removed: list[Path] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _normalize_path_filter(raw: str | None) -> str | None:
    """Normalize a user-supplied path filter to a repo-relative prefix.

    Accepts `docs/technical/`, `docs/technical`, `./docs/technical/`, or
    `/docs/technical/` and returns `docs/technical` (no leading slash,
    no trailing slash, no `./` prefix).
    """
    if raw is None:
        return None
    p = raw.strip()
    if p.startswith("./"):
        p = p[2:]
    p = p.lstrip("/").rstrip("/")
    return p or None


def _matches_path_filter(source_artifact: str, path_filter: str | None) -> bool:
    """True when source_artifact is the filter or lives under it.

    `path_filter` is the normalized repo-relative prefix. Matching rules:

    - No filter → always match
    - Exact path equality → match (single-file filter)
    - source_artifact starts with `<path_filter>/` → match (subtree filter)
    """
    if path_filter is None:
        return True
    if source_artifact == path_filter:
        return True
    return source_artifact.startswith(path_filter + "/")


def _slug_from_source(source_artifact: str) -> str:
    """Derive a filesystem-safe, unique-per-artifact slug.

    `docs/technical/pipeline-architecture.md` → `docs-technical-pipeline-architecture`.
    The slug preserves the directory structure so two files with the
    same basename in different subdirs don't collide.
    """
    p = Path(source_artifact)
    parts = [*p.parts[:-1], p.stem]
    joined = "-".join(parts).lower()
    slug = _SLUG_SAFE_RE.sub("-", joined).strip("-")
    return slug or "artifact"


def _collect_candidates(
    project_cfg: ProjectConfig, path_filter: str | None
) -> list[Path]:
    """Walk source_globs and return repo-relative paths of matching files.

    Returned paths are relative to `project_cfg.repo_path`. Directories
    and non-existent glob matches are filtered out. Results are sorted
    and deduplicated.
    """
    repo_path = Path(project_cfg.repo_path).expanduser().resolve()
    seen: set[str] = set()
    out: list[Path] = []
    for glob in project_cfg.source_globs:
        for abs_path in repo_path.glob(glob):
            if not abs_path.is_file():
                continue
            rel = abs_path.relative_to(repo_path)
            rel_str = str(rel)
            if rel_str in seen:
                continue
            if not _matches_path_filter(rel_str, path_filter):
                continue
            seen.add(rel_str)
            out.append(rel)
    return sorted(out, key=str)


def _existing_raw_by_source(
    wiki_root: Path, project: str, path_filter: str | None
) -> dict[str, Path]:
    """Map source_artifact → staging-file Path for every **raw** staged file.

    Used for `--force`-mode deletion: raw files are disposable and the
    force path re-creates them. Proposed files are NOT considered here
    — they carry real work and must never be deleted by sync.

    Scoped to the path filter so `--force docs/technical/` does not list
    unrelated raw files.
    """
    by_source: dict[str, Path] = {}
    for staged_path in list_staged(wiki_root, project):
        try:
            staged, _body = read_staged(staged_path)
        except Exception:
            continue
        if staged.state != StagedState.RAW.value:
            continue
        src = staged.source_artifact
        if src is None:
            continue
        if not _matches_path_filter(src, path_filter):
            continue
        by_source[src] = staged_path
    return by_source


def _occupied_source_artifacts(
    wiki_root: Path, project: str, path_filter: str | None
) -> dict[str, str]:
    """Map source_artifact → skip-reason for every staged file that
    'occupies' a source_artifact slot.

    A source artifact is occupied if:
    - A `state: raw` staged file exists with that `source_artifact`
      ('already staged as raw'), OR
    - A `state: proposed` staged file exists with `upgraded_from.source_artifact`
      matching that path ('already upgraded to proposed')

    The second case is the bug fix: without it, a sync → capture
    (raw→proposed) → sync cycle would recreate a raw file for a
    source doc that already has a live proposed file in the queue,
    producing competing items. By treating the source artifact as
    occupied when a proposed file has upgraded from it, sync skips
    it silently and the user sees it only as 'skipped: already
    upgraded to proposed' in the output.

    Scoped to `path_filter` so callers can run `--force docs/technical/`
    without touching unrelated proposed items.
    """
    occupied: dict[str, str] = {}
    for staged_path in list_staged(wiki_root, project):
        try:
            staged, _body = read_staged(staged_path)
        except Exception:
            continue
        src: str | None = None
        reason = ""
        if staged.state == StagedState.RAW.value:
            src = staged.source_artifact
            reason = "already staged as raw"
        elif (
            staged.state == StagedState.PROPOSED.value
            and staged.upgraded_from is not None
            and staged.upgraded_from.source_artifact
        ):
            src = staged.upgraded_from.source_artifact
            reason = "already upgraded to proposed"
        if src is None:
            continue
        if not _matches_path_filter(src, path_filter):
            continue
        # If both a raw and a proposed exist for the same source, the
        # raw record wins in this map (it's the deletable one), but
        # --force deletion is bounded by _existing_raw_by_source
        # anyway so there's no risk of nuking the proposed.
        if src not in occupied:
            occupied[src] = reason
    return occupied


def run_sync(
    *,
    wiki_root: Path,
    project_cfg: ProjectConfig,
    sync_cfg: SyncConfig,
    path_filter: str | None = None,
    force: bool = False,
    trigger: str = "manual",
) -> SyncResult:
    """Register all matching project artifacts as raw staged files.

    Algorithm:

    1. Collect candidate artifacts from `project_cfg.source_globs`, filtered
       to `path_filter` if given.
    2. Build the occupancy map: `source_artifact → skip-reason` for every
       staged file in scope that already "covers" a source artifact —
       either a raw file or a proposed file with `upgraded_from.source_artifact`
       pointing at it. This dedupe is tighter than raw-only dedupe because
       it prevents the sync → capture → sync cycle from producing
       competing raw/proposed pairs for the same source doc.
    3. If `force`, delete any raw staged files in scope and drop their
       entries from the occupancy map. Proposed files are NEVER deleted
       by sync; --force only affects disposable raw items.
    4. For each candidate not in the occupancy map, write a new raw
       staged file. Inline body if under `sync_cfg.inline_threshold_bytes`,
       pointer otherwise.
    5. Return a `SyncResult` with created / removed / skipped / warnings.
       Skipped entries record both the source path and the reason
       ('already staged as raw' vs 'already upgraded to proposed').

    Errors during UTF-8 decoding of a candidate file add a warning and
    skip that file; they do not abort the run.
    """
    normalized_filter = _normalize_path_filter(path_filter)
    result = SyncResult()

    candidates = _collect_candidates(project_cfg, normalized_filter)
    occupied = _occupied_source_artifacts(
        wiki_root, project_cfg.name, normalized_filter
    )

    if force:
        # Force only deletes raw files; proposed files stay.
        raw_existing = _existing_raw_by_source(
            wiki_root, project_cfg.name, normalized_filter
        )
        for src, staged_path in raw_existing.items():
            staged_path.unlink()
            result.removed.append(staged_path)
            occupied.pop(src, None)

    repo_path = Path(project_cfg.repo_path).expanduser().resolve()

    for rel in candidates:
        src = str(rel)
        if src in occupied:
            result.skipped.append(f"{src} ({occupied[src]})")
            continue
        artifact_abs = repo_path / rel
        try:
            content = artifact_abs.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            result.warnings.append(
                f"skipped {src}: not valid UTF-8 (binary artifact)"
            )
            continue
        size = len(content.encode("utf-8"))
        inline = size < sync_cfg.inline_threshold_bytes
        body = content if inline else ""
        staged = StagedFile(
            state=StagedState.RAW,
            origin=StagedFileOrigin.SYNC,
            created_at=utc_now(),
            created_by="wiki sync",
            source_artifact=src,
            trigger=trigger,
            raw_body_mode=(
                RawBodyMode.INLINE if inline else RawBodyMode.POINTER
            ),
            raw_body_bytes=size,
        )
        slug = _slug_from_source(src)
        path = write_staged(wiki_root, project_cfg.name, staged, body, slug=slug)
        result.created.append(path)

    return result
