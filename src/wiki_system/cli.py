"""`wiki` click entrypoint."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import click

from wiki_system.bootstrap import (
    BootstrapAllExhausted,
    BootstrapRejection,
    run_prepare_bootstrap,
    run_submit_bootstrap,
)
from wiki_system.capture import (
    SubmitRejection,
    prepare_capture,
    submit_capture,
)
from wiki_system.config import WikiConfig, load_config
from wiki_system.index import build_index, render_views, save_index
from wiki_system.init import run_init
from wiki_system.promote import PromoteRejection, promote as promote_op
from wiki_system.query import run_query
from wiki_system.review import list_review_queue
from wiki_system.sync import run_sync


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
    try:
        results = run_query(wiki_root, project, question, cfg.retrieval, limit=limit)
    except FileNotFoundError:
        # Exit 4: index unavailable. Distinct from exit 2 (no results) so
        # machine callers can tell "wiki has nothing on this topic" apart
        # from "wiki isn't in a queryable state."
        click.echo(
            f"wiki index not found for project '{project}'. "
            f"Run `wiki index {project}` first, then retry.",
            err=True,
        )
        ctx.exit(4)
    except ValueError as e:
        # Raised by load_index on a stale schema_version — same class
        # as missing index: infrastructure unavailable, not a query failure.
        click.echo(
            f"wiki index unreadable for project '{project}': {e}. "
            f"Run `wiki index {project}` to rebuild.",
            err=True,
        )
        ctx.exit(4)
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
@click.option(
    "--session-notes",
    default=None,
    help=(
        "Path to a plain-text notes file, or '-' to read from stdin. "
        "For anything beyond a few paragraphs, prefer a file — piping "
        "large bodies via bash heredoc is fragile."
    ),
)
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
        try:
            notes_text = Path(session_notes).read_text()
        except FileNotFoundError as e:
            click.echo(f"session-notes file not found: {e}", err=True)
            ctx.exit(1)
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
@click.option(
    "--proposal",
    required=True,
    help=(
        "Path to a proposal JSON file, or '-' to read from stdin. "
        "For proposals >1KB or with embedded backticks, pipes, or "
        "backslashes, prefer a file path — shell heredocs silently "
        "corrupt those characters. Write the JSON with "
        "`python -c 'import json; json.dump(data, open(path, \"w\"))'` "
        "and pass --proposal=<path>."
    ),
)
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
    try:
        if proposal == "-":
            raw_proposal = sys.stdin.read()
        else:
            raw_proposal = Path(proposal).read_text()
    except FileNotFoundError as e:
        click.echo(f"proposal file not found: {e}", err=True)
        ctx.exit(1)
    try:
        proposal_data = json.loads(raw_proposal)
    except json.JSONDecodeError as e:
        lines = [f"proposal JSON invalid: {e}"]
        if proposal == "-":
            lines.append(
                "Hint: if you piped the proposal via a bash heredoc, the "
                "shell may have corrupted embedded backticks, pipes, or "
                "backslashes in the canonical_page.body. Write the JSON "
                "to a file with "
                "`python -c 'import json; json.dump(data, open(path, \"w\"))'` "
                "and pass --proposal=<file-path> instead."
            )
        click.echo("\n".join(lines), err=True)
        ctx.exit(2)
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


# ---------- bootstrap ----------


@main.group()
def bootstrap() -> None:
    """Seed-question-driven page synthesis (prepare/submit)."""


@bootstrap.command("prepare")
@click.argument("project")
@click.option(
    "--question",
    "question_arg",
    default=None,
    help=(
        "The seed question (or substring thereof) to bootstrap. Matched "
        "against queries/seed-questions.md — exact or unambiguous substring. "
        "To run with a free-text question that is NOT in the seed file, also "
        "pass --ad-hoc. Mutually exclusive with --all."
    ),
)
@click.option(
    "--all",
    "all_mode",
    is_flag=True,
    help=(
        "Iterate queries/seed-questions.md in file order and emit the prompt "
        "package for the next seed question that has no pending bootstrap "
        "proposal. Each invocation returns exactly one question; the agent "
        "re-invokes after each submit. Exits 3 ('nothing to do') when every "
        "seed question is already processed. Mutually exclusive with --question."
    ),
)
@click.option(
    "--max-proposals",
    default=None,
    type=int,
    help=(
        "Session cap for --all mode. Emitted in the prompt package as a hint "
        "the agent reads and uses to bound its own loop — the CLI does not "
        "track state across invocations. Ignored in single-question mode."
    ),
)
@click.option(
    "--ad-hoc",
    is_flag=True,
    help=(
        "Allow --question to be free text that doesn't match any seed "
        "question. Without this flag, mismatched --question is an error "
        "(prevents typos from silently becoming ad-hoc runs). Ignored "
        "with --all."
    ),
)
@click.option(
    "--limit-docs",
    default=5,
    type=int,
    help="Max number of source docs to include in the prompt package. Default: 5.",
)
@click.option(
    "--paths",
    "path_filter",
    default=None,
    help=(
        "Restrict source doc candidates to a repo-relative prefix "
        "(e.g. 'docs/technical/'). Narrows within source_globs."
    ),
)
@click.option(
    "--replace-pending",
    is_flag=True,
    help=(
        "Allow prepare even if a pending bootstrap proposal already exists "
        "for this question_key. The pending file is kept on disk; submit "
        "with --replace-pending deletes it."
    ),
)
@click.pass_context
def bootstrap_prepare(
    ctx: click.Context,
    project: str,
    question_arg: str | None,
    all_mode: bool,
    max_proposals: int | None,
    ad_hoc: bool,
    limit_docs: int,
    path_filter: str | None,
    replace_pending: bool,
) -> None:
    """Build a prompt package for a seed question.

    Single-question mode (`--question`): resolves the question against
    seed-questions.md and builds one prompt package.

    --all mode: iterates seed-questions.md in file order, picks the next
    unprocessed question (one with no pending proposal), and builds
    one prompt package for it. Agents re-invoke `prepare --all` after
    each successful submit to get the next question. Exits 3 when the
    queue is drained.

    Emits the PromptPackage as JSON on stdout (same shape as
    `capture prepare`). The agent reads it, synthesizes a proposal,
    and calls `wiki bootstrap submit`.
    """
    if all_mode and question_arg is not None:
        click.echo("--all and --question are mutually exclusive", err=True)
        ctx.exit(1)
    if not all_mode and question_arg is None:
        click.echo(
            "either --question or --all is required",
            err=True,
        )
        ctx.exit(1)

    cfg = _load_config_or_die(ctx)
    project_cfg = _get_project_or_die(ctx, cfg, project)
    wiki_root = cfg.wiki_root_path()
    try:
        result = run_prepare_bootstrap(
            wiki_root=wiki_root,
            project_cfg=project_cfg,
            retrieval_cfg=cfg.retrieval,
            question_arg=question_arg,
            all_mode=all_mode,
            ad_hoc=ad_hoc,
            limit_docs=limit_docs,
            path_filter=path_filter,
            replace_pending=replace_pending,
            max_proposals=max_proposals,
        )
    except BootstrapAllExhausted as e:
        # --all queue drained — semantically "nothing to do", exit 3
        # matching review/capture noop/empty conventions.
        click.echo(str(e), err=True)
        ctx.exit(3)
    except BootstrapRejection as e:
        click.echo(str(e), err=True)
        ctx.exit(2)
    click.echo(result.package.to_json())


@bootstrap.command("submit")
@click.argument("project")
@click.option(
    "--proposal",
    required=True,
    help=(
        "Path to a proposal JSON file, or '-' to read from stdin. "
        "Same rules as `capture submit --proposal`: prefer a file path "
        "for anything with a non-trivial canonical_page.body to avoid "
        "shell-heredoc corruption."
    ),
)
@click.option(
    "--replace-pending",
    is_flag=True,
    help=(
        "If a pending bootstrap proposal already exists for this question, "
        "delete it and write the new one. Without this flag, submit refuses."
    ),
)
@click.pass_context
def bootstrap_submit(
    ctx: click.Context,
    project: str,
    proposal: str,
    replace_pending: bool,
) -> None:
    """Validate a bootstrap proposal and write a state: proposed staged file."""
    cfg = _load_config_or_die(ctx)
    _get_project_or_die(ctx, cfg, project)
    wiki_root = cfg.wiki_root_path()
    try:
        if proposal == "-":
            raw_proposal = sys.stdin.read()
        else:
            raw_proposal = Path(proposal).read_text()
    except FileNotFoundError as e:
        click.echo(f"proposal file not found: {e}", err=True)
        ctx.exit(1)
    try:
        proposal_data = json.loads(raw_proposal)
    except json.JSONDecodeError as e:
        lines = [f"proposal JSON invalid: {e}"]
        if proposal == "-":
            lines.append(
                "Hint: if you piped via bash heredoc, embedded backticks/"
                "pipes/backslashes may be corrupted. Write to a file and "
                "pass --proposal=<file-path>."
            )
        click.echo("\n".join(lines), err=True)
        ctx.exit(2)
    try:
        result = run_submit_bootstrap(
            wiki_root=wiki_root,
            project=project,
            proposal=proposal_data,
            replace_pending=replace_pending,
        )
    except BootstrapRejection as e:
        click.echo(str(e), err=True)
        ctx.exit(2)
    payload = {
        "action": result.action,
        "staging_path": result.staging_path,
        "proposed_page_id": result.proposed_page_id,
        "question_key": result.question_key,
    }

    def _text(p):
        if p["action"] == "noop":
            return f"noop: no staged file written for question {p['question_key']!r}"
        return (
            f"staged: {p['action']} {p['proposed_page_id']} -> {p['staging_path']} "
            f"(question: {p['question_key']})"
        )

    _emit(ctx, payload, _text)
    if result.action == "noop":
        ctx.exit(3)


# ---------- sync ----------


@main.command("sync")
@click.argument("project")
@click.option(
    "--path",
    "path_filter",
    default=None,
    help=(
        "Restrict sync to a repo-relative path prefix (e.g. 'docs/technical/'). "
        "Matches the path exactly or any file under it. Combined with --force, "
        "only raw files inside this subtree are affected — unrelated raw items "
        "are preserved."
    ),
)
@click.option(
    "--force",
    is_flag=True,
    help=(
        "Delete existing raw staged files (scoped to --path if given) before "
        "re-creating them. Default is to skip artifacts that already have a "
        "raw staged file. Use this to pick up edits to the source files."
    ),
)
@click.option(
    "--trigger",
    default="manual",
    help="Trigger label to record on the raw staged files. Default: manual.",
)
@click.pass_context
def sync_cmd(
    ctx: click.Context,
    project: str,
    path_filter: str | None,
    force: bool,
    trigger: str,
) -> None:
    """Register project source_globs as raw staged files.

    Walks `[[projects]] source_globs` from wiki.config.toml and creates one
    `state: raw` staged file per matched artifact. Inline body for files
    under `[sync] inline_threshold_bytes`, pointer mode otherwise.

    Downstream loop: `wiki review` shows the queue, `/wiki-capture
    --from-staged=<path>` upgrades each raw file into a proposed canonical
    page, `wiki promote` canonicalizes it.
    """
    cfg = _load_config_or_die(ctx)
    project_cfg = _get_project_or_die(ctx, cfg, project)
    wiki_root = cfg.wiki_root_path()
    result = run_sync(
        wiki_root=wiki_root,
        project_cfg=project_cfg,
        sync_cfg=cfg.sync,
        path_filter=path_filter,
        force=force,
        trigger=trigger,
    )
    payload = {
        "created": [str(p) for p in result.created],
        "removed": [str(p) for p in result.removed],
        "skipped": result.skipped,
        "warnings": result.warnings,
    }

    def _text(p):
        lines: list[str] = []
        if p["removed"]:
            lines.append(
                f"Removed {len(p['removed'])} existing raw file(s) (--force):"
            )
            for path in p["removed"]:
                lines.append(f"  - {path}")
            lines.append("")
        lines.append(f"Created {len(p['created'])} raw staged file(s):")
        for path in p["created"]:
            lines.append(f"  - {path}")
        if p["skipped"]:
            lines.append("")
            lines.append(
                f"Skipped {len(p['skipped'])} artifact(s) already staged "
                "(pass --force to re-create):"
            )
            for src in p["skipped"]:
                lines.append(f"  - {src}")
        if p["warnings"]:
            lines.append("")
            lines.append(f"Warnings ({len(p['warnings'])}):")
            for w in p["warnings"]:
                lines.append(f"  - {w}")
        return "\n".join(lines)

    _emit(ctx, payload, _text)


# ---------- init ----------


@main.command("init")
@click.option(
    "--wiki-system-root",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to the wiki-system checkout. Defaults to the package's own "
    "parent (derived from this file's location).",
)
@click.option(
    "--wiki-data-root",
    type=click.Path(path_type=Path),
    default=Path("~/Git/wiki"),
    help="Path to the wiki data repo. Defaults to ~/Git/wiki.",
)
@click.option(
    "--agents-dir",
    type=click.Path(path_type=Path),
    default=Path("~/.agents"),
    help="Shared-agent canonical directory. Skills and commands are "
    "installed here so any agent framework that discovers ~/.agents/ "
    "can pick them up. Defaults to ~/.agents.",
)
@click.option(
    "--claude-dir",
    type=click.Path(path_type=Path),
    default=Path("~/.claude"),
    help="Claude Code config directory. wiki init creates symlinks here "
    "pointing back at the canonical files under --agents-dir. Defaults "
    "to ~/.claude.",
)
@click.pass_context
def init_cmd(
    ctx: click.Context,
    wiki_system_root: Path | None,
    wiki_data_root: Path,
    agents_dir: Path,
    claude_dir: Path,
) -> None:
    """Generate per-machine adapter artifacts with resolved local paths.

    Writes canonical rendered skill + slash commands under --agents-dir
    (shared across agent frameworks) and symlinks them into --claude-dir
    so Claude Code discovers them. Seeds a wiki.config.toml from the
    example if the wiki data repo is empty. Prints a permissions snippet
    for your Claude settings. Idempotent — re-run after template edits.
    """
    if wiki_system_root is None:
        wiki_system_root = Path(__file__).resolve().parent.parent.parent
    result = run_init(
        wiki_system_root=wiki_system_root,
        wiki_data_root=wiki_data_root,
        agents_dir=agents_dir,
        claude_dir=claude_dir,
    )
    payload = {
        "rendered": [str(p) for p in result.rendered],
        "symlinks": [
            {"link": str(link), "target": str(target)}
            for link, target in result.symlinks
        ],
        "seeded_config": (
            str(result.seeded_config) if result.seeded_config else None
        ),
        "permissions_snippet": result.permissions_snippet,
    }

    def _text(p):
        lines = [f"Rendered {len(p['rendered'])} canonical file(s):"]
        for path in p["rendered"]:
            lines.append(f"  - {path}")
        if p["symlinks"]:
            lines.append("")
            lines.append(
                f"Created {len(p['symlinks'])} Claude Code symlink(s):"
            )
            for link in p["symlinks"]:
                lines.append(f"  - {link['link']} -> {link['target']}")
        if p["seeded_config"]:
            lines.append("")
            lines.append(
                f"Seeded wiki.config.toml at: {p['seeded_config']}"
            )
            lines.append(
                "Edit it and add a [[projects]] block for each codebase "
                "you want wiki-enabled."
            )
        lines.append("")
        lines.append(
            "Add this to ~/.claude/settings.json (merge with any existing "
            "permissions.allow list):"
        )
        lines.append("")
        lines.append(p["permissions_snippet"])
        lines.append("")
        lines.append(
            "Then start a new Claude Code session and type `/wiki` to see "
            "the available slash commands."
        )
        return "\n".join(lines)

    _emit(ctx, payload, _text)


if __name__ == "__main__":
    main()
