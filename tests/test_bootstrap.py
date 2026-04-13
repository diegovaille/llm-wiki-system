"""Tests for `wiki_system.bootstrap` — prepare + submit for single-question mode."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from wiki_system.bootstrap import (
    BootstrapRejection,
    _collect_source_candidates,
    _load_seed_questions,
    _score_source_doc,
    _slugify_question,
    resolve_question,
    run_prepare_bootstrap,
    run_submit_bootstrap,
)
from wiki_system.config import ProjectConfig, RetrievalConfig
from wiki_system.schema import (
    BootstrapFrom,
    Confidence,
    PageFrontmatter,
    PageStatus,
    PageType,
    StagedFileOrigin,
    StagedState,
)
from wiki_system.storage import list_staged, read_staged, write_page


# ---------- Test fixtures / helpers ----------


def _make_project(
    tmp_path: Path,
    name: str = "demo",
    source_globs: list[str] | None = None,
    files: dict[str, str] | None = None,
) -> ProjectConfig:
    """Build a ProjectConfig with a real repo populated with `files`."""
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    for rel, content in (files or {}).items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return ProjectConfig(
        name=name,
        repo_path=str(repo),
        source_globs=source_globs or ["docs/**/*.md"],
    )


def _write_seed_questions(wiki_root: Path, project: str, questions: list[str]) -> None:
    p = wiki_root / project / "queries" / "seed-questions.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Seed questions", ""]
    for i, q in enumerate(questions, start=1):
        lines.append(f"{i}. {q}")
    p.write_text("\n".join(lines))


def _write_project_intent(wiki_root: Path, project: str, body: str) -> None:
    p = wiki_root / project / "meta" / "project.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\nproject: {project}\n---\n\n{body}\n")


def _write_existing_page(wiki_root: Path, project: str, id_: str, **overrides) -> None:
    fm = PageFrontmatter(
        id=id_,
        title=overrides.get("title", id_.replace("-", " ").title()),
        summary=overrides.get("summary", f"Summary for {id_}"),
        type=overrides.get("type", PageType.SYSTEM),
        project=project,
        domains=overrides.get("domains", ["pipeline"]),
        status=PageStatus.ACTIVE,
        aliases=overrides.get("aliases", []),
        sources=overrides.get("sources", ["session:2026-04-12-seed"]),
        related=overrides.get("related", []),
        updated_at=date(2026, 4, 12),
        confidence=Confidence.HIGH,
    )
    body = overrides.get("body", f"# {fm.title}\n\nBody for {id_}.\n")
    write_page(wiki_root, project, fm, body)


def _valid_bootstrap_proposal(**overrides) -> dict:
    """A well-formed bootstrap proposal the agent would produce."""
    base = {
        "action": "create",
        "target_page_id": None,
        "rationale": "distill the seed question",
        "bootstrap_question": {
            "question_text": "How does the story pipeline work?",
            "question_source": "seed",
            "question_key": "how-does-the-story-pipeline-work",
            "question_line": 1,
        },
        "canonical_page": {
            "frontmatter": {
                "id": "demo-pipeline",
                "title": "Demo Pipeline",
                "summary": "Pipeline overview.",
                "type": "system",
                "project": "demo",
                "domains": ["pipeline"],
                "status": "active",
                "aliases": [],
                "sources": ["docs/technical/pipeline.md"],
                "related": [],
                "updated_at": "2026-04-12",
                "confidence": "high",
            },
            "body": "# Demo Pipeline\n\nEnd-to-end overview.\n",
        },
    }
    base.update(overrides)
    return base


# ---------- Unit: slugify_question ----------


def test_slugify_question_produces_stable_slug():
    assert _slugify_question("How does the story pipeline work?") == "how-does-the-story-pipeline-work"


def test_slugify_question_collapses_punctuation_and_whitespace():
    assert (
        _slugify_question("   What's a Story?!  -- really?   ")
        == "what-s-a-story-really"
    )


def test_slugify_question_never_empty():
    assert _slugify_question("!!!") == "question"


# ---------- Unit: seed question loading + resolution ----------


def test_load_seed_questions_parses_numbered_list(wiki_root: Path):
    _write_seed_questions(
        wiki_root,
        "demo",
        [
            "How does the story pipeline work?",
            "What is the canonical story creation workflow?",
            "What defines character identity?",
        ],
    )
    qs = _load_seed_questions(wiki_root, "demo")
    assert len(qs) == 3
    assert qs[0].text == "How does the story pipeline work?"
    assert qs[0].line == 3  # line 1 is "# Seed questions", line 2 is blank
    assert qs[0].source == "seed"
    assert qs[0].key == "how-does-the-story-pipeline-work"


def test_load_seed_questions_returns_empty_when_file_missing(wiki_root: Path):
    assert _load_seed_questions(wiki_root, "demo") == []


def test_resolve_question_exact_match(wiki_root: Path):
    _write_seed_questions(
        wiki_root, "demo", ["How does the story pipeline work?", "Another question"]
    )
    qs = _load_seed_questions(wiki_root, "demo")
    result = resolve_question("How does the story pipeline work?", qs)
    assert result.source == "seed"
    assert result.text == "How does the story pipeline work?"


def test_resolve_question_unambiguous_substring(wiki_root: Path):
    _write_seed_questions(
        wiki_root,
        "demo",
        ["How does the story pipeline work?", "What is the editor workflow?"],
    )
    qs = _load_seed_questions(wiki_root, "demo")
    result = resolve_question("story pipeline", qs)
    assert result.source == "seed"
    assert "story pipeline" in result.text.lower()


def test_resolve_question_ambiguous_substring_rejected(wiki_root: Path):
    _write_seed_questions(
        wiki_root,
        "demo",
        ["How does the pipeline start?", "How does the pipeline end?"],
    )
    qs = _load_seed_questions(wiki_root, "demo")
    with pytest.raises(BootstrapRejection, match="matches multiple"):
        resolve_question("pipeline", qs)


def test_resolve_question_no_match_requires_ad_hoc(wiki_root: Path):
    _write_seed_questions(wiki_root, "demo", ["Something unrelated"])
    qs = _load_seed_questions(wiki_root, "demo")
    with pytest.raises(BootstrapRejection, match="--ad-hoc"):
        resolve_question("video rendering", qs)


def test_resolve_question_ad_hoc_fallback(wiki_root: Path):
    _write_seed_questions(wiki_root, "demo", ["Something unrelated"])
    qs = _load_seed_questions(wiki_root, "demo")
    result = resolve_question("video rendering", qs, ad_hoc=True)
    assert result.source == "ad-hoc"
    assert result.text == "video rendering"
    assert result.line is None
    assert result.key == "video-rendering"


def test_resolve_question_empty_rejected(wiki_root: Path):
    with pytest.raises(BootstrapRejection, match="empty"):
        resolve_question("  ", [], ad_hoc=True)


# ---------- Unit: source doc scoring ----------


def test_score_source_doc_counts_distinct_token_overlaps():
    question_tokens = set(["pipeline", "story", "render"])
    body = "The story pipeline. Also a story. Pipeline stuff."
    # pipeline, story both present; render absent → score = 2
    assert _score_source_doc(question_tokens, body) == 2.0


def test_score_source_doc_zero_when_no_overlap():
    question_tokens = set(["video", "audio"])
    body = "This is about story pipelines."
    assert _score_source_doc(question_tokens, body) == 0.0


def test_collect_source_candidates_ranks_and_limits(wiki_root: Path, tmp_path: Path):
    project_cfg = _make_project(
        tmp_path,
        files={
            "docs/a.md": "story pipeline generation pipeline review",  # 3 overlaps
            "docs/b.md": "story pipeline",  # 2 overlaps
            "docs/c.md": "generation review",  # 2 overlaps, lower path
            "docs/d.md": "unrelated content about nothing",  # 0
        },
    )
    candidates = _collect_source_candidates(
        project_cfg,
        question_tokens=set(["story", "pipeline", "generation", "review"]),
        path_filter=None,
        limit=5,
    )
    # d excluded (score 0). a hits all four tokens (score 4). b and c each
    # hit two tokens (score 2); tie broken alphabetically by path.
    assert [c.path for c in candidates] == ["docs/a.md", "docs/b.md", "docs/c.md"]
    assert candidates[0].score == 4.0
    assert candidates[1].score == 2.0
    assert candidates[2].score == 2.0


def test_collect_source_candidates_honors_path_filter(wiki_root: Path, tmp_path: Path):
    project_cfg = _make_project(
        tmp_path,
        files={
            "docs/technical/a.md": "story pipeline",
            "docs/other/b.md": "story pipeline",
        },
    )
    candidates = _collect_source_candidates(
        project_cfg,
        question_tokens=set(["story"]),
        path_filter="docs/technical/",
        limit=5,
    )
    assert [c.path for c in candidates] == ["docs/technical/a.md"]


def test_collect_source_candidates_limit(wiki_root: Path, tmp_path: Path):
    files = {f"docs/{letter}.md": "story pipeline" for letter in "abcdefg"}
    project_cfg = _make_project(tmp_path, files=files)
    candidates = _collect_source_candidates(
        project_cfg,
        question_tokens=set(["story"]),
        path_filter=None,
        limit=3,
    )
    assert len(candidates) == 3


# ---------- Integration: run_prepare_bootstrap ----------


def test_prepare_builds_prompt_package_with_all_sections(
    wiki_root: Path, tmp_path: Path
):
    from wiki_system.index import build_index, save_index

    _write_seed_questions(wiki_root, "demo", ["How does the story pipeline work?"])
    _write_project_intent(wiki_root, "demo", "This project distills story-pipeline knowledge.")
    _write_existing_page(
        wiki_root,
        "demo",
        "demo-pipeline",
        title="Story Pipeline",
        domains=["pipeline"],
    )
    # Real runs call `wiki index` after `wiki promote`; bootstrap reads
    # the persisted index via run_query.
    idx = build_index(wiki_root, "demo")
    save_index(wiki_root, "demo", idx)

    project_cfg = _make_project(
        tmp_path,
        files={"docs/pipeline.md": "Full documentation of the story pipeline work flow."},
    )
    result = run_prepare_bootstrap(
        wiki_root=wiki_root,
        project_cfg=project_cfg,
        retrieval_cfg=RetrievalConfig(),
        question_arg="story pipeline",
        limit_docs=5,
    )
    assert result.question.source == "seed"
    assert result.question.text == "How does the story pipeline work?"
    context = result.package.context
    assert "Project intent" in context
    assert "Seed question" in context
    assert "Question provenance" in context
    assert "Existing canonical pages" in context
    assert "demo-pipeline" in context
    assert "Source documentation candidates" in context
    assert "docs/pipeline.md" in context
    assert "story-pipeline" in result.question.key
    assert result.package.allowed_actions == ["noop", "update", "create"]


def test_prepare_refuses_when_pending_proposal_exists(
    wiki_root: Path, tmp_path: Path
):
    _write_seed_questions(wiki_root, "demo", ["How does the story pipeline work?"])
    project_cfg = _make_project(tmp_path, files={"docs/a.md": "story pipeline"})

    # First prepare + submit establishes a pending proposal
    first = run_prepare_bootstrap(
        wiki_root=wiki_root,
        project_cfg=project_cfg,
        retrieval_cfg=RetrievalConfig(),
        question_arg="story pipeline",
    )
    run_submit_bootstrap(
        wiki_root=wiki_root,
        project="demo",
        proposal=_valid_bootstrap_proposal(
            bootstrap_question={
                "question_text": first.question.text,
                "question_source": first.question.source,
                "question_key": first.question.key,
                "question_line": first.question.line,
            }
        ),
    )

    # Second prepare without --replace-pending refuses
    with pytest.raises(BootstrapRejection, match="pending bootstrap proposal"):
        run_prepare_bootstrap(
            wiki_root=wiki_root,
            project_cfg=project_cfg,
            retrieval_cfg=RetrievalConfig(),
            question_arg="story pipeline",
        )

    # With --replace-pending, prepare succeeds (does NOT delete yet —
    # the deletion happens at submit time)
    result = run_prepare_bootstrap(
        wiki_root=wiki_root,
        project_cfg=project_cfg,
        retrieval_cfg=RetrievalConfig(),
        question_arg="story pipeline",
        replace_pending=True,
    )
    assert result.existing_pending_path is not None


def test_prepare_ad_hoc_question(wiki_root: Path, tmp_path: Path):
    _write_seed_questions(wiki_root, "demo", ["Unrelated seed question"])
    project_cfg = _make_project(tmp_path, files={"docs/a.md": "video rendering details"})
    result = run_prepare_bootstrap(
        wiki_root=wiki_root,
        project_cfg=project_cfg,
        retrieval_cfg=RetrievalConfig(),
        question_arg="video rendering",
        ad_hoc=True,
    )
    assert result.question.source == "ad-hoc"
    assert result.question.text == "video rendering"
    assert "ad-hoc" in result.package.context


# ---------- Integration: run_submit_bootstrap ----------


def test_submit_writes_proposed_staged_file_with_bootstrap_from(
    wiki_root: Path, tmp_path: Path
):
    result = run_submit_bootstrap(
        wiki_root=wiki_root,
        project="demo",
        proposal=_valid_bootstrap_proposal(),
    )
    assert result.action == "create"
    assert result.proposed_page_id == "demo-pipeline"
    staged_paths = list_staged(wiki_root, "demo")
    assert len(staged_paths) == 1
    staged, _ = read_staged(staged_paths[0])
    assert staged.state == StagedState.PROPOSED.value
    assert staged.origin == StagedFileOrigin.BOOTSTRAP.value
    assert staged.bootstrap_from is not None
    assert staged.bootstrap_from.question_source == "seed"
    assert staged.bootstrap_from.question_key == "how-does-the-story-pipeline-work"


def test_submit_noop_writes_nothing(wiki_root: Path):
    result = run_submit_bootstrap(
        wiki_root=wiki_root,
        project="demo",
        proposal={
            "action": "noop",
            "rationale": "existing pages already answer this",
            "bootstrap_question": {
                "question_text": "How does X work?",
                "question_source": "seed",
                "question_key": "how-does-x-work",
                "question_line": 1,
            },
        },
    )
    assert result.action == "noop"
    assert result.staging_path == ""
    assert list_staged(wiki_root, "demo") == []


def test_submit_rejects_proposal_missing_bootstrap_question(wiki_root: Path):
    proposal = _valid_bootstrap_proposal()
    del proposal["bootstrap_question"]
    with pytest.raises(BootstrapRejection, match="bootstrap_question"):
        run_submit_bootstrap(
            wiki_root=wiki_root, project="demo", proposal=proposal
        )


def test_submit_rejects_invalid_bootstrap_question_source(wiki_root: Path):
    proposal = _valid_bootstrap_proposal(
        bootstrap_question={
            "question_text": "anything",
            "question_source": "hallucinated",
            "question_key": "anything",
        }
    )
    with pytest.raises(BootstrapRejection, match="bootstrap_question invalid"):
        run_submit_bootstrap(
            wiki_root=wiki_root, project="demo", proposal=proposal
        )


def test_submit_dedupe_rejects_duplicate_question(wiki_root: Path):
    run_submit_bootstrap(
        wiki_root=wiki_root, project="demo", proposal=_valid_bootstrap_proposal()
    )
    with pytest.raises(BootstrapRejection, match="pending bootstrap proposal"):
        run_submit_bootstrap(
            wiki_root=wiki_root,
            project="demo",
            proposal=_valid_bootstrap_proposal(
                canonical_page={
                    "frontmatter": {
                        "id": "demo-pipeline-v2",
                        "title": "Demo Pipeline V2",
                        "summary": "",
                        "type": "system",
                        "project": "demo",
                        "domains": [],
                        "status": "active",
                        "aliases": [],
                        "sources": ["session:2026-04-12-x"],
                        "related": [],
                        "updated_at": "2026-04-12",
                        "confidence": "high",
                    },
                    "body": "# V2\n",
                }
            ),
        )


def test_submit_replace_pending_deletes_old_and_writes_new(wiki_root: Path):
    first = run_submit_bootstrap(
        wiki_root=wiki_root, project="demo", proposal=_valid_bootstrap_proposal()
    )
    first_path = Path(first.staging_path)
    assert first_path.exists()

    replacement = _valid_bootstrap_proposal()
    replacement["canonical_page"]["frontmatter"]["id"] = "demo-pipeline-v2"
    replacement["canonical_page"]["frontmatter"]["title"] = "Pipeline V2"
    second = run_submit_bootstrap(
        wiki_root=wiki_root,
        project="demo",
        proposal=replacement,
        replace_pending=True,
    )
    assert not first_path.exists()
    assert second.proposed_page_id == "demo-pipeline-v2"
    all_staged = list_staged(wiki_root, "demo")
    assert len(all_staged) == 1


# ---------- CLI integration ----------


def _setup_cli_config(
    tmp_path: Path, wiki_root: Path, repo: Path, source_globs: list[str]
) -> Path:
    repo.mkdir(parents=True, exist_ok=True)
    cfg_path = tmp_path / "wiki.config.toml"
    globs_toml = ", ".join(f'"{g}"' for g in source_globs)
    cfg_path.write_text(
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
source_globs = [{globs_toml}]
"""
    )
    return cfg_path


def test_cli_bootstrap_prepare_emits_prompt_package_json(
    wiki_root: Path, tmp_path: Path
):
    from click.testing import CliRunner

    from wiki_system.cli import main

    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "pipeline.md").write_text(
        "Story pipeline: how the editor advances a story."
    )
    _write_seed_questions(wiki_root, "demo", ["How does the story pipeline work?"])
    cfg_path = _setup_cli_config(tmp_path, wiki_root, repo, ["docs/**/*.md"])

    runner = CliRunner()
    r = runner.invoke(
        main,
        [
            "--config",
            str(cfg_path),
            "bootstrap",
            "prepare",
            "demo",
            "--question",
            "story pipeline",
        ],
    )
    assert r.exit_code == 0, (r.stdout, r.stderr)
    pkg = json.loads(r.stdout)
    assert pkg["allowed_actions"] == ["noop", "update", "create"]
    assert "bootstrap_question" in pkg["context"]
    assert "story pipeline" in pkg["context"].lower()


def test_cli_bootstrap_prepare_rejects_ambiguous_without_ad_hoc(
    wiki_root: Path, tmp_path: Path
):
    from click.testing import CliRunner

    from wiki_system.cli import main

    _write_seed_questions(
        wiki_root, "demo", ["How does the pipeline start?", "How does the pipeline end?"]
    )
    cfg_path = _setup_cli_config(tmp_path, wiki_root, tmp_path / "repo", ["docs/**/*.md"])
    runner = CliRunner()
    r = runner.invoke(
        main,
        [
            "--config",
            str(cfg_path),
            "bootstrap",
            "prepare",
            "demo",
            "--question",
            "pipeline",
        ],
    )
    assert r.exit_code == 2
    assert "matches multiple" in r.stderr


def test_cli_bootstrap_prepare_ad_hoc_succeeds(wiki_root: Path, tmp_path: Path):
    from click.testing import CliRunner

    from wiki_system.cli import main

    _write_seed_questions(wiki_root, "demo", ["Unrelated seed"])
    cfg_path = _setup_cli_config(tmp_path, wiki_root, tmp_path / "repo", ["docs/**/*.md"])
    runner = CliRunner()
    r = runner.invoke(
        main,
        [
            "--config",
            str(cfg_path),
            "bootstrap",
            "prepare",
            "demo",
            "--question",
            "video rendering",
            "--ad-hoc",
        ],
    )
    assert r.exit_code == 0, (r.stdout, r.stderr)
    pkg = json.loads(r.stdout)
    assert "ad-hoc" in pkg["context"]


def test_cli_bootstrap_submit_writes_staged_file(wiki_root: Path, tmp_path: Path):
    from click.testing import CliRunner

    from wiki_system.cli import main

    cfg_path = _setup_cli_config(tmp_path, wiki_root, tmp_path / "repo", ["docs/**/*.md"])
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(json.dumps(_valid_bootstrap_proposal()))

    runner = CliRunner()
    r = runner.invoke(
        main,
        [
            "--config",
            str(cfg_path),
            "bootstrap",
            "submit",
            "demo",
            "--proposal",
            str(proposal_path),
        ],
    )
    assert r.exit_code == 0, (r.stdout, r.stderr)
    payload = json.loads(r.stdout)
    assert payload["action"] == "create"
    assert payload["proposed_page_id"] == "demo-pipeline"
    assert payload["question_key"] == "how-does-the-story-pipeline-work"


def test_cli_bootstrap_submit_noop_exit_3(wiki_root: Path, tmp_path: Path):
    from click.testing import CliRunner

    from wiki_system.cli import main

    cfg_path = _setup_cli_config(tmp_path, wiki_root, tmp_path / "repo", ["docs/**/*.md"])
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(
        json.dumps(
            {
                "action": "noop",
                "rationale": "already covered",
                "bootstrap_question": {
                    "question_text": "anything",
                    "question_source": "seed",
                    "question_key": "anything",
                    "question_line": 1,
                },
            }
        )
    )

    runner = CliRunner()
    r = runner.invoke(
        main,
        [
            "--config",
            str(cfg_path),
            "bootstrap",
            "submit",
            "demo",
            "--proposal",
            str(proposal_path),
        ],
    )
    assert r.exit_code == 3, (r.stdout, r.stderr)
