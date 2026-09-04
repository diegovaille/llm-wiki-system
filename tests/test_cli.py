import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

from wiki_system.cli import main
from wiki_system.schema import (
    Confidence,
    PageFrontmatter,
    PageStatus,
    PageType,
    RawBodyMode,
    StagedFile,
    StagedFileOrigin,
    StagedState,
)
from wiki_system.storage import write_page, write_staged


def _setup_config(tmp_path: Path, wiki_root: Path, repo: Path) -> Path:
    repo.mkdir(parents=True, exist_ok=True)
    cfg = tmp_path / "wiki.config.toml"
    cfg.write_text(
        f"""
[wiki]
root = "{wiki_root}"

[execution]
mode = "agent"

[execution.agent]
runtime = "claude-code"
model_hint = "opus"

[[projects]]
name = "demo"
repo_path = "{repo}"
source_globs = ["docs/**/*.md"]
"""
    )
    return cfg


def _seed(wiki_root: Path) -> None:
    fm = PageFrontmatter(
        id="demo-foo",
        title="Story Pipeline",
        summary="End to end story pipeline.",
        type=PageType.SYSTEM,
        project="demo",
        domains=["pipeline"],
        status=PageStatus.ACTIVE,
        aliases=[],
        sources=["session:2026-04-12-x"],
        related=[],
        updated_at=date(2026, 4, 12),
        confidence=Confidence.HIGH,
    )
    write_page(wiki_root, "demo", fm, "# Story Pipeline\n\nThree stages.\n")


def _runner() -> CliRunner:
    # click 8.3 always separates stdout and stderr; no mix_stderr flag.
    return CliRunner()


def test_cli_index_and_query_round_trip(wiki_root: Path, tmp_path: Path):
    cfg_path = _setup_config(tmp_path, wiki_root, tmp_path / "repo")
    _seed(wiki_root)
    runner = _runner()
    r1 = runner.invoke(main, ["--config", str(cfg_path), "index", "demo"])
    assert r1.exit_code == 0, (r1.stdout, r1.stderr)
    r2 = runner.invoke(
        main,
        ["--config", str(cfg_path), "query", "demo", "story pipeline"],
    )
    assert r2.exit_code == 0, (r2.stdout, r2.stderr)
    payload = json.loads(r2.stdout)
    assert payload[0]["id"] == "demo-foo"


def test_cli_query_default_is_json_on_stdout(wiki_root: Path, tmp_path: Path):
    cfg_path = _setup_config(tmp_path, wiki_root, tmp_path / "repo")
    _seed(wiki_root)
    runner = _runner()
    runner.invoke(main, ["--config", str(cfg_path), "index", "demo"])
    r = runner.invoke(
        main,
        ["--config", str(cfg_path), "query", "demo", "story pipeline"],
    )
    assert r.exit_code == 0
    # stdout must be parseable JSON
    parsed = json.loads(r.stdout)
    assert isinstance(parsed, list)


def test_cli_query_text_mode_emits_human_output_on_stdout(
    wiki_root: Path, tmp_path: Path
):
    cfg_path = _setup_config(tmp_path, wiki_root, tmp_path / "repo")
    _seed(wiki_root)
    runner = _runner()
    runner.invoke(main, ["--config", str(cfg_path), "index", "demo"])
    r = runner.invoke(
        main,
        [
            "--config",
            str(cfg_path),
            "--no-json",
            "query",
            "demo",
            "story pipeline",
        ],
    )
    assert r.exit_code == 0
    # Text mode: stdout is NOT valid JSON, but contains human-readable content
    with pytest.raises(json.JSONDecodeError):
        json.loads(r.stdout)
    assert "demo-foo" in r.stdout or "Story Pipeline" in r.stdout


def test_cli_error_messages_go_to_stderr_not_stdout(
    wiki_root: Path, tmp_path: Path
):
    cfg_path = _setup_config(tmp_path, wiki_root, tmp_path / "repo")
    runner = _runner()
    r = runner.invoke(
        main, ["--config", str(cfg_path), "query", "nonexistent-project", "anything"]
    )
    assert r.exit_code != 0
    # stderr gets human error; stdout is either empty or valid JSON
    assert r.stderr
    if r.stdout.strip():
        json.loads(r.stdout)  # must still be valid JSON


def test_cli_query_no_results_exit_2(wiki_root: Path, tmp_path: Path):
    cfg_path = _setup_config(tmp_path, wiki_root, tmp_path / "repo")
    _seed(wiki_root)
    runner = _runner()
    runner.invoke(main, ["--config", str(cfg_path), "index", "demo"])
    r = runner.invoke(
        main,
        ["--config", str(cfg_path), "query", "demo", "unrelatedxyzqqq"],
    )
    assert r.exit_code == 2


def test_cli_query_missing_index_exits_4_with_actionable_error(
    wiki_root: Path, tmp_path: Path
):
    """On a fresh project with no .wiki-index.json, `wiki query` must NOT
    produce a Python traceback. Exit code 4 (index unavailable) —
    distinct from exit 2 (no results) so machine callers can tell
    'wiki has nothing on this topic' apart from 'wiki isn't queryable'.
    """
    cfg_path = _setup_config(tmp_path, wiki_root, tmp_path / "repo")
    _seed(wiki_root)
    # Deliberately skip `wiki index` — no .wiki-index.json exists
    runner = _runner()
    r = runner.invoke(
        main, ["--config", str(cfg_path), "query", "demo", "story pipeline"]
    )
    assert r.exit_code == 4, (r.stdout, r.stderr)
    assert "wiki index" in r.stderr
    assert "not found" in r.stderr
    # Traceback must not leak to stderr
    assert "Traceback" not in r.stderr
    assert "FileNotFoundError" not in r.stderr


def test_cli_query_stale_schema_version_exits_4_with_actionable_error(
    wiki_root: Path, tmp_path: Path
):
    """If .wiki-index.json exists but has a stale schema_version, query
    must exit 4 (index unavailable) with a clean rebuild instruction,
    not raise ValueError.
    """
    cfg_path = _setup_config(tmp_path, wiki_root, tmp_path / "repo")
    _seed(wiki_root)
    # Build the index, then hand-corrupt the schema version
    runner = _runner()
    runner.invoke(main, ["--config", str(cfg_path), "index", "demo"])
    index_path = wiki_root / "demo" / ".wiki-index.json"
    payload = json.loads(index_path.read_text())
    payload["schema_version"] = 99  # future version we don't know how to read
    index_path.write_text(json.dumps(payload))
    r = runner.invoke(
        main, ["--config", str(cfg_path), "query", "demo", "story pipeline"]
    )
    assert r.exit_code == 4, (r.stdout, r.stderr)
    assert "wiki index" in r.stderr
    assert "Traceback" not in r.stderr


def test_cli_query_no_results_stays_exit_2(wiki_root: Path, tmp_path: Path):
    """Regression guard: 'no results' remains exit 2. The exit-4 addition
    for index-unavailable must NOT disturb the no-results exit code that
    downstream callers may already rely on. Exit 2 and exit 4 are now
    semantically distinct for wiki query:
      - 2: query ran successfully, wiki returned zero hits
      - 4: wiki could not be queried (index missing/stale)
    """
    cfg_path = _setup_config(tmp_path, wiki_root, tmp_path / "repo")
    _seed(wiki_root)
    runner = _runner()
    runner.invoke(main, ["--config", str(cfg_path), "index", "demo"])
    r = runner.invoke(
        main,
        ["--config", str(cfg_path), "query", "demo", "unrelatedxyzqqq"],
    )
    assert r.exit_code == 2, (r.stdout, r.stderr)


def test_cli_capture_prepare_emits_json(wiki_root: Path, tmp_path: Path):
    cfg_path = _setup_config(tmp_path, wiki_root, tmp_path / "repo")
    runner = _runner()
    r = runner.invoke(
        main,
        [
            "--config",
            str(cfg_path),
            "capture",
            "prepare",
            "--project",
            "demo",
            "--session-notes",
            "-",
        ],
        input="session text",
    )
    assert r.exit_code == 0, (r.stdout, r.stderr)
    pkg = json.loads(r.stdout)
    assert "system" in pkg
    assert pkg["allowed_actions"] == ["noop", "update", "create"]


def test_cli_capture_submit_noop_exit_3(wiki_root: Path, tmp_path: Path):
    cfg_path = _setup_config(tmp_path, wiki_root, tmp_path / "repo")
    proposal = json.dumps({"action": "noop", "rationale": "nothing"})
    runner = _runner()
    r = runner.invoke(
        main,
        [
            "--config",
            str(cfg_path),
            "capture",
            "submit",
            "--project",
            "demo",
            "--proposal",
            "-",
        ],
        input=proposal,
    )
    assert r.exit_code == 3, (r.stdout, r.stderr)


def test_cli_capture_submit_stdin_invalid_json_exit_2_with_heredoc_hint(
    wiki_root: Path, tmp_path: Path
):
    """Invalid JSON on stdin should exit 2 (schema-invalid) with a hint
    pointing the caller at the file-path workaround.
    """
    cfg_path = _setup_config(tmp_path, wiki_root, tmp_path / "repo")
    runner = _runner()
    # Corrupt the JSON exactly the way a broken heredoc would — extra
    # trailing } after a well-formed object.
    corrupt = '{"action":"noop","rationale":"nothing"}}'
    r = runner.invoke(
        main,
        [
            "--config",
            str(cfg_path),
            "capture",
            "submit",
            "--project",
            "demo",
            "--proposal",
            "-",
        ],
        input=corrupt,
    )
    assert r.exit_code == 2, (r.stdout, r.stderr)
    assert "proposal JSON invalid" in r.stderr
    assert "heredoc" in r.stderr
    assert "--proposal=<file-path>" in r.stderr


def test_cli_capture_submit_file_invalid_json_exit_2_without_heredoc_hint(
    wiki_root: Path, tmp_path: Path
):
    """File-path mode also wraps JSONDecodeError as exit 2, but without
    the heredoc hint (the user already took the file-path path).
    """
    cfg_path = _setup_config(tmp_path, wiki_root, tmp_path / "repo")
    bad_proposal = tmp_path / "bad.json"
    bad_proposal.write_text('{"action": not_a_thing')
    runner = _runner()
    r = runner.invoke(
        main,
        [
            "--config",
            str(cfg_path),
            "capture",
            "submit",
            "--project",
            "demo",
            "--proposal",
            str(bad_proposal),
        ],
    )
    assert r.exit_code == 2, (r.stdout, r.stderr)
    assert "proposal JSON invalid" in r.stderr
    assert "heredoc" not in r.stderr


def test_cli_capture_submit_missing_proposal_file_exit_1(
    wiki_root: Path, tmp_path: Path
):
    """Pointing --proposal at a nonexistent file should exit 1 with a
    clear 'proposal file not found' message, not a raw traceback.
    """
    cfg_path = _setup_config(tmp_path, wiki_root, tmp_path / "repo")
    runner = _runner()
    r = runner.invoke(
        main,
        [
            "--config",
            str(cfg_path),
            "capture",
            "submit",
            "--project",
            "demo",
            "--proposal",
            str(tmp_path / "does-not-exist.json"),
        ],
    )
    assert r.exit_code == 1, (r.stdout, r.stderr)
    assert "proposal file not found" in r.stderr


def test_cli_capture_submit_file_path_works_for_noop(
    wiki_root: Path, tmp_path: Path
):
    """Sanity check: --proposal=<file> is a valid path for a noop proposal.

    The primary motivation for documenting file-path mode is large
    canonical_page bodies, but the flag works for any proposal shape.
    """
    cfg_path = _setup_config(tmp_path, wiki_root, tmp_path / "repo")
    proposal_file = tmp_path / "proposal.json"
    proposal_file.write_text(
        json.dumps({"action": "noop", "rationale": "nothing captured"})
    )
    runner = _runner()
    r = runner.invoke(
        main,
        [
            "--config",
            str(cfg_path),
            "capture",
            "submit",
            "--project",
            "demo",
            "--proposal",
            str(proposal_file),
        ],
    )
    assert r.exit_code == 3, (r.stdout, r.stderr)


def test_cli_promote_raw_rejected_exit_2(wiki_root: Path, tmp_path: Path):
    cfg_path = _setup_config(tmp_path, wiki_root, tmp_path / "repo")
    raw = StagedFile(
        state=StagedState.RAW,
        origin=StagedFileOrigin.SYNC,
        created_at=datetime(2026, 4, 12, tzinfo=timezone.utc),
        created_by="hook",
        source_artifact="docs/foo.md",
        trigger="post-spec",
        raw_body_mode=RawBodyMode.INLINE,
    )
    staged_path = write_staged(wiki_root, "demo", raw, "body", slug="raw-x")
    runner = _runner()
    r = runner.invoke(
        main,
        [
            "--config",
            str(cfg_path),
            "promote",
            "demo",
            str(staged_path),
            "--apply",
        ],
    )
    assert r.exit_code == 2, (r.stdout, r.stderr)
    # Error message lives on stderr
    assert "raw" in r.stderr.lower()


def test_cli_review_lists_staging_queue_as_json(wiki_root: Path, tmp_path: Path):
    cfg_path = _setup_config(tmp_path, wiki_root, tmp_path / "repo")
    raw = StagedFile(
        state=StagedState.RAW,
        origin=StagedFileOrigin.SYNC,
        created_at=datetime(2026, 4, 12, tzinfo=timezone.utc),
        created_by="hook",
        source_artifact="docs/foo.md",
        trigger="post-spec",
        raw_body_mode=RawBodyMode.INLINE,
    )
    write_staged(wiki_root, "demo", raw, "body", slug="raw-x")
    runner = _runner()
    r = runner.invoke(main, ["--config", str(cfg_path), "review", "demo"])
    assert r.exit_code == 0, (r.stdout, r.stderr)
    payload = json.loads(r.stdout)
    assert isinstance(payload, list)
    assert len(payload) == 1
    assert payload[0]["state"] == "raw"
    assert payload[0]["source_artifact"] == "docs/foo.md"


def test_cli_review_empty_exit_3(wiki_root: Path, tmp_path: Path):
    cfg_path = _setup_config(tmp_path, wiki_root, tmp_path / "repo")
    runner = _runner()
    r = runner.invoke(main, ["--config", str(cfg_path), "review", "demo"])
    # Empty queue is not an error, but a signal: exit 3 ("nothing to do")
    assert r.exit_code == 3
    # stdout still valid JSON (empty list)
    payload = json.loads(r.stdout)
    assert payload == []


def _setup_config_with_domains(
    tmp_path: Path, wiki_root: Path, repo: Path, domains: list[str]
) -> Path:
    repo.mkdir(parents=True, exist_ok=True)
    cfg = tmp_path / "wiki.config.toml"
    cfg.write_text(
        f"""
[wiki]
root = "{wiki_root}"

[execution]
mode = "agent"

[execution.agent]
runtime = "claude-code"
model_hint = "opus"

[[projects]]
name = "demo"
repo_path = "{repo}"
source_globs = ["docs/**/*.md"]
domains = {domains!r}
"""
    )
    return cfg


def test_cli_index_warns_on_non_canonical_domain(wiki_root: Path, tmp_path: Path):
    cfg_path = _setup_config_with_domains(
        tmp_path, wiki_root, tmp_path / "repo", ["backend"]
    )
    _seed(wiki_root)  # seed page is tagged domains=["pipeline"]
    runner = _runner()
    r = runner.invoke(main, ["--config", str(cfg_path), "index", "demo"])
    assert r.exit_code == 0, (r.stdout, r.stderr)
    payload = json.loads(r.stdout)
    assert payload["warnings_count"] == 1
    assert "demo-foo" in payload["warnings"][0]
    assert "pipeline" in payload["warnings"][0]


def test_cli_index_strict_fails_on_non_canonical_domain(
    wiki_root: Path, tmp_path: Path
):
    cfg_path = _setup_config_with_domains(
        tmp_path, wiki_root, tmp_path / "repo", ["backend"]
    )
    _seed(wiki_root)
    runner = _runner()
    r = runner.invoke(
        main, ["--config", str(cfg_path), "index", "demo", "--strict"]
    )
    assert r.exit_code == 1, (r.stdout, r.stderr)


def test_cli_index_strict_passes_when_domains_canonical(
    wiki_root: Path, tmp_path: Path
):
    cfg_path = _setup_config_with_domains(
        tmp_path, wiki_root, tmp_path / "repo", ["pipeline", "backend"]
    )
    _seed(wiki_root)
    runner = _runner()
    r = runner.invoke(
        main, ["--config", str(cfg_path), "index", "demo", "--strict"]
    )
    assert r.exit_code == 0, (r.stdout, r.stderr)
    assert json.loads(r.stdout)["warnings_count"] == 0


def test_cli_index_no_allowlist_keeps_free_form_domains(
    wiki_root: Path, tmp_path: Path
):
    """Legacy mode: projects without a domains allowlist never warn."""
    cfg_path = _setup_config(tmp_path, wiki_root, tmp_path / "repo")
    _seed(wiki_root)
    runner = _runner()
    r = runner.invoke(
        main, ["--config", str(cfg_path), "index", "demo", "--strict"]
    )
    assert r.exit_code == 0, (r.stdout, r.stderr)
    assert json.loads(r.stdout)["warnings_count"] == 0


# ---- 0.5.0: config discovery without --config ------------------------------


def _discovery_config(tmp_path: Path, name: str) -> Path:
    d = tmp_path / name
    d.mkdir()
    cfg = d / "wiki.config.toml"
    cfg.write_text(
        f"""
[wiki]
root = "."
[execution]
mode = "agent"
[execution.agent]
runtime = "claude-code"
[[projects]]
name = "{name}"
repo_path = "{d}"
"""
    )
    (d / name / "pages").mkdir(parents=True)
    return cfg


def test_wiki_root_env_selects_the_config(tmp_path: Path):
    cfg = _discovery_config(tmp_path, "rooted")
    r = _runner().invoke(main, ["index", "rooted"], env={"WIKI_ROOT": str(cfg.parent), "WIKI_CONFIG": None})
    assert r.exit_code == 0, r.output + (r.stderr if hasattr(r, "stderr") else "")
    assert (cfg.parent / "rooted" / ".wiki-index.json").exists()


def test_wiki_config_env_beats_wiki_root(tmp_path: Path):
    by_root = _discovery_config(tmp_path, "byroot")
    by_file = _discovery_config(tmp_path, "byfile")
    r = _runner().invoke(main, ["index", "byfile"], env={"WIKI_ROOT": str(by_root.parent), "WIKI_CONFIG": str(by_file)})
    assert r.exit_code == 0, r.output
    assert (by_file.parent / "byfile" / ".wiki-index.json").exists()
    assert not (by_root.parent / "byfile" / ".wiki-index.json").exists()


def test_config_flag_beats_both_env_vars(tmp_path: Path):
    env_cfg = _discovery_config(tmp_path, "fromenv")
    flag_cfg = _discovery_config(tmp_path, "fromflag")
    r = _runner().invoke(main, ["--config", str(flag_cfg), "index", "fromflag"], env={"WIKI_ROOT": str(env_cfg.parent), "WIKI_CONFIG": str(env_cfg)})
    assert r.exit_code == 0, r.output
    assert (flag_cfg.parent / "fromflag" / ".wiki-index.json").exists()


def test_config_flag_expands_a_literal_tilde(tmp_path: Path, monkeypatch):
    # The wiki skills pass "$WIKI_CONFIG" verbatim; a value typed as ~/x must work.
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = _discovery_config(tmp_path, "tilde")
    rel = "~/" + str(cfg.relative_to(tmp_path))
    r = _runner().invoke(main, ["--config", rel, "index", "tilde"])
    assert r.exit_code == 0, r.output
    assert (cfg.parent / "tilde" / ".wiki-index.json").exists()


def test_strict_index_reports_dangling_related_and_duplicate_ids(tmp_path: Path):
    cfg = _discovery_config(tmp_path, "links")
    root = cfg.parent
    from datetime import date
    from wiki_system.schema import Confidence, PageFrontmatter, PageStatus, PageType
    from wiki_system.storage import write_page

    def page(id_, related=(), path_id=None):
        fm = PageFrontmatter(id=id_, title=id_, summary="s", type=PageType.SYSTEM, project="links",
                             domains=[], status=PageStatus.ACTIVE, aliases=[], sources=["s:x"],
                             related=list(related), updated_at=date(2026, 9, 4), confidence=Confidence.HIGH)
        write_page(root, "links", fm, "# b\n\nbody\n")
        return fm

    page("links-alpha", related=["links-missing"])
    page("links-beta")
    # a second file claiming beta's id
    (root / "links" / "pages" / "links-beta-copy.md").write_text(
        (root / "links" / "pages" / "links-beta.md").read_text())
    r = _runner().invoke(main, ["--config", str(cfg), "index", "links", "--strict"])
    assert r.exit_code == 1, r.output
    assert "links-alpha: related: names unknown page 'links-missing'" in r.output
    assert "links-beta: id declared by 2 pages" in r.output
    r = _runner().invoke(main, ["--config", str(cfg), "index", "links"])
    assert r.exit_code == 0  # without --strict the warnings are reported, not fatal
