"""`wiki` click entrypoint."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import click

from wiki_system.capture import (
    SubmitRejection,
    prepare_capture,
    submit_capture,
)
from wiki_system.config import WikiConfig, load_config
from wiki_system.index import build_index, render_views, save_index
from wiki_system.promote import PromoteRejection, promote as promote_op
from wiki_system.query import run_query
from wiki_system.review import list_review_queue


DEFAULT_CONFIG = Path("~/Git/wiki/wiki.config.toml").expanduser()


def _load_config_or_die(ctx: click.Context) -> WikiConfig:
    cfg_path: Path = ctx.obj["config_path"]
    if not cfg_path.exists():
        click.echo(f"config not found: {cfg_path}", err=True)
        ctx.exit(1)
    return load_config(cfg_path)


def _get_project_or_die(ctx: click.Context, cfg: WikiConfig, name: str):
    try:
        return cfg.get_project(name)
    except KeyError as e:
        click.echo(str(e), err=True)
        ctx.exit(1)


def _emit(ctx: click.Context, payload: Any, text_fn=None) -> None:
    """Emit JSON to stdout by default, or text if --no-json and text_fn provided."""
    if ctx.obj["json"] or text_fn is None:
        click.echo(json.dumps(payload, indent=2, default=str))
    else:
        click.echo(text_fn(payload))


@click.group()
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to wiki.config.toml",
)
@click.option(
    "--json/--no-json",
    "json_mode",
    default=True,
    help="Emit JSON on stdout (default, machine-readable) or human text (--no-json).",
)
@click.pass_context
def main(
    ctx: click.Context, config_path: Path | None, json_mode: bool
) -> None:
    """wiki-system CLI.

    All commands emit JSON on stdout by default (machine-first). Use --no-json for
    human-readable output. Diagnostics and error messages always go to stderr.
    """
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config_path or DEFAULT_CONFIG
    ctx.obj["json"] = json_mode


# ---------- query ----------


@main.command()
@click.argument("project")
@click.argument("question")
@click.option("--limit", type=int, default=5)
@click.pass_context
def query(ctx: click.Context, project: str, question: str, limit: int) -> None:
    cfg = _load_config_or_die(ctx)
    _get_project_or_die(ctx, cfg, project)
    wiki_root = cfg.wiki_root_path()
    results = run_query(wiki_root, project, question, cfg.retrieval, limit=limit)
    payload = [
        {
            "id": r.id,
            "title": r.title,
            "summary": r.summary,
            "path": r.path,
            "score": r.score,
            "matched_fields": r.matched_fields,
            "match_source": r.match_source,
            "reasons": r.reasons,
            "snippet": r.snippet,
        }
        for r in results
    ]

    def _text(p):
        if not p:
            return "(no results)"
        lines = []
        for i, hit in enumerate(p, start=1):
            lines.append(
                f"{i}. {hit['title']} ({hit['id']})  [score={hit['score']:.2f}]"
            )
            if hit.get("summary"):
                lines.append(f"   {hit['summary']}")
            if hit.get("snippet"):
                lines.append(f"   > {hit['snippet']}")
            if hit.get("reasons"):
                lines.append(f"   reasons: {', '.join(hit['reasons'])}")
        return "\n".join(lines)

    _emit(ctx, payload, _text)
    if not results:
        ctx.exit(2)


# ---------- index ----------


@main.command("index")
@click.argument("project")
@click.option("--strict", is_flag=True, help="Exit nonzero on schema warnings")
@click.pass_context
def index_cmd(ctx: click.Context, project: str, strict: bool) -> None:
    cfg = _load_config_or_die(ctx)
    project_cfg = _get_project_or_die(ctx, cfg, project)
    wiki_root = cfg.wiki_root_path()
    idx = build_index(wiki_root, project)
    save_index(wiki_root, project, idx)
    render_views(wiki_root, project, idx, repo_path=project_cfg.repo_path)
    payload = {"pages_indexed": len(idx.pages), "warnings_count": 0}
    _emit(
        ctx,
        payload,
        lambda p: f"indexed {p['pages_indexed']} page(s), {p['warnings_count']} warning(s)",
    )


# ---------- capture ----------


@main.group()
def capture() -> None:
    """capture prepare/submit."""


@capture.command("prepare")
@click.option("--project", required=True)
@click.option("--session-notes", default=None, help="Path or '-' for stdin")
@click.option(
    "--from-staged",
    default=None,
    type=click.Path(exists=True, path_type=Path),
)
@click.pass_context
def capture_prepare(
    ctx: click.Context,
    project: str,
    session_notes: str | None,
    from_staged: Path | None,
) -> None:
    cfg = _load_config_or_die(ctx)
    project_cfg = _get_project_or_die(ctx, cfg, project)
    wiki_root = cfg.wiki_root_path()
    notes_text: str | None = None
    if session_notes == "-":
        notes_text = sys.stdin.read()
    elif session_notes is not None:
        notes_text = Path(session_notes).read_text()
    try:
        pkg = prepare_capture(
            wiki_root,
            project_cfg,
            session_notes=notes_text,
            from_staged=from_staged,
        )
    except FileNotFoundError as e:
        click.echo(str(e), err=True)
        ctx.exit(1)
    # Prepare output is always JSON (it IS a prompt package). --no-json
    # still emits JSON here because there is no meaningful text projection.
    click.echo(pkg.to_json())


@capture.command("submit")
@click.option("--project", required=True)
@click.option("--proposal", required=True, help="Path or '-' for stdin")
@click.option(
    "--from-staged",
    default=None,
    type=click.Path(exists=True, path_type=Path),
)
@click.pass_context
def capture_submit(
    ctx: click.Context,
    project: str,
    proposal: str,
    from_staged: Path | None,
) -> None:
    cfg = _load_config_or_die(ctx)
    _get_project_or_die(ctx, cfg, project)
    wiki_root = cfg.wiki_root_path()
    if proposal == "-":
        proposal_data = json.loads(sys.stdin.read())
    else:
        proposal_data = json.loads(Path(proposal).read_text())
    try:
        result = submit_capture(
            wiki_root,
            project=project,
            proposal=proposal_data,
            from_staged=from_staged,
        )
    except SubmitRejection as e:
        click.echo(str(e), err=True)
        ctx.exit(2)
    payload = {
        "action": result.action,
        "staging_path": result.staging_path,
        "proposed_page_id": result.proposed_page_id,
    }

    def _text(p):
        if p["action"] == "noop":
            return "no capture needed"
        return f"staged: {p['action']} {p['proposed_page_id']} -> {p['staging_path']}"

    _emit(ctx, payload, _text)
    if result.action == "noop":
        ctx.exit(3)


# ---------- promote ----------


@main.command()
@click.argument("project")
@click.argument("staged_file", type=click.Path(exists=True, path_type=Path))
@click.option("--apply", is_flag=True)
@click.pass_context
def promote(
    ctx: click.Context, project: str, staged_file: Path, apply: bool
) -> None:
    cfg = _load_config_or_die(ctx)
    project_cfg = _get_project_or_die(ctx, cfg, project)
    wiki_root = cfg.wiki_root_path()
    try:
        result = promote_op(
            wiki_root,
            project,
            staged_file,
            apply=apply,
            repo_path=project_cfg.repo_path,
        )
    except PromoteRejection as e:
        click.echo(str(e), err=True)
        ctx.exit(2)
    payload = {
        "action": result.action,
        "page_id": result.page_id,
        "path": result.path,
        "dry_run": result.dry_run,
    }

    def _text(p):
        if p["dry_run"]:
            return f"dry-run: {p['action']} {p['page_id']} (see stderr for diff)"
        return f"promoted: {p['action']} {p['page_id']} -> {p['path']}"

    _emit(ctx, payload, _text)
    # diff is always human-readable diagnostic output on stderr
    click.echo(result.diff, err=True)
    if result.dry_run:
        ctx.exit(3)


# ---------- review ----------


@main.command()
@click.argument("project")
@click.pass_context
def review(ctx: click.Context, project: str) -> None:
    cfg = _load_config_or_die(ctx)
    _get_project_or_die(ctx, cfg, project)
    wiki_root = cfg.wiki_root_path()
    items = list_review_queue(wiki_root, project)
    payload = [item.to_dict() for item in items]

    def _text(p):
        if not p:
            return "(staging queue empty)"
        lines = [f"Staging queue for {project} ({len(p)} item(s)):", ""]
        raw = [i for i in p if i["state"] == "raw"]
        proposed = [i for i in p if i["state"] == "proposed"]
        if raw:
            lines.append("RAW (needs upgrade via /wiki-capture --from-staged=<path>)")
            for i in raw:
                lines.append(f"- {i['staging_path']}")
                lines.append(
                    f"  origin: {i['origin']} | trigger: {i.get('trigger','-')} "
                    f"| source: {i.get('source_artifact','-')}"
                )
            lines.append("")
        if proposed:
            lines.append("PROPOSED (ready to promote via /wiki-promote <path>)")
            for i in proposed:
                lines.append(f"- {i['staging_path']}")
                action = i.get("proposed_action", "?")
                title = i.get("proposed_title", "?")
                pid = i.get("proposed_page_id", "?")
                lines.append(f"  {action}: {title} (id: {pid})")
                if i.get("proposed_summary"):
                    lines.append(f"  summary: {i['proposed_summary']}")
            lines.append("")
        return "\n".join(lines)

    _emit(ctx, payload, _text)
    if not items:
        ctx.exit(3)


if __name__ == "__main__":
    main()
