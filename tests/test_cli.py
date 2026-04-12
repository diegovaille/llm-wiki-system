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
name = "luminavine"
repo_path = "{repo}"
source_globs = ["docs/**/*.md"]
"""
    )
    return cfg


def _seed(wiki_root: Path) -> None:
    fm = PageFrontmatter(
        id="lv-foo",
        title="Story Pipeline",
        summary="End to end story pipeline.",
        type=PageType.SYSTEM,
        project="luminavine",
        domains=["pipeline"],
        status=PageStatus.ACTIVE,
        aliases=[],
        sources=["session:2026-04-12-x"],
        related=[],
        updated_at=date(2026, 4, 12),
        confidence=Confidence.HIGH,
    )
    write_page(wiki_root, "luminavine", fm, "# Story Pipeline\n\nThree stages.\n")


def _runner() -> CliRunner:
    # click 8.3 always separates stdout and stderr; no mix_stderr flag.
    return CliRunner()


def test_cli_index_and_query_round_trip(wiki_root: Path, tmp_path: Path):
    cfg_path = _setup_config(tmp_path, wiki_root, tmp_path / "repo")
    _seed(wiki_root)
    runner = _runner()
    r1 = runner.invoke(main, ["--config", str(cfg_path), "index", "luminavine"])
    assert r1.exit_code == 0, (r1.stdout, r1.stderr)
    r2 = runner.invoke(
        main,
        ["--config", str(cfg_path), "query", "luminavine", "story pipeline"],
    )
    assert r2.exit_code == 0, (r2.stdout, r2.stderr)
    payload = json.loads(r2.stdout)
    assert payload[0]["id"] == "lv-foo"


def test_cli_query_default_is_json_on_stdout(wiki_root: Path, tmp_path: Path):
    cfg_path = _setup_config(tmp_path, wiki_root, tmp_path / "repo")
    _seed(wiki_root)
    runner = _runner()
    runner.invoke(main, ["--config", str(cfg_path), "index", "luminavine"])
    r = runner.invoke(
        main,
        ["--config", str(cfg_path), "query", "luminavine", "story pipeline"],
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
    runner.invoke(main, ["--config", str(cfg_path), "index", "luminavine"])
    r = runner.invoke(
        main,
        [
            "--config",
            str(cfg_path),
            "--no-json",
            "query",
            "luminavine",
            "story pipeline",
        ],
    )
    assert r.exit_code == 0
    # Text mode: stdout is NOT valid JSON, but contains human-readable content
    with pytest.raises(json.JSONDecodeError):
        json.loads(r.stdout)
    assert "lv-foo" in r.stdout or "Story Pipeline" in r.stdout


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
    runner.invoke(main, ["--config", str(cfg_path), "index", "luminavine"])
    r = runner.invoke(
        main,
        ["--config", str(cfg_path), "query", "luminavine", "unrelatedxyzqqq"],
    )
    assert r.exit_code == 2


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
            "luminavine",
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
            "luminavine",
            "--proposal",
            "-",
        ],
        input=proposal,
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
    staged_path = write_staged(wiki_root, "luminavine", raw, "body", slug="raw-x")
    runner = _runner()
    r = runner.invoke(
        main,
        [
            "--config",
            str(cfg_path),
            "promote",
            "luminavine",
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
    write_staged(wiki_root, "luminavine", raw, "body", slug="raw-x")
    runner = _runner()
    r = runner.invoke(main, ["--config", str(cfg_path), "review", "luminavine"])
    assert r.exit_code == 0, (r.stdout, r.stderr)
    payload = json.loads(r.stdout)
    assert isinstance(payload, list)
    assert len(payload) == 1
    assert payload[0]["state"] == "raw"
    assert payload[0]["source_artifact"] == "docs/foo.md"


def test_cli_review_empty_exit_3(wiki_root: Path, tmp_path: Path):
    cfg_path = _setup_config(tmp_path, wiki_root, tmp_path / "repo")
    runner = _runner()
    r = runner.invoke(main, ["--config", str(cfg_path), "review", "luminavine"])
    # Empty queue is not an error, but a signal: exit 3 ("nothing to do")
    assert r.exit_code == 3
    # stdout still valid JSON (empty list)
    payload = json.loads(r.stdout)
    assert payload == []
