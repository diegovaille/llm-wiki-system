# Contributing to wiki-system

Thanks for your interest. `wiki-system` is still small and iterating — PRs, issues, and design feedback are all welcome.

## Setup

```bash
git clone https://github.com/diegovaille/llm-wiki-system ~/Git/wiki-system
cd ~/Git/wiki-system
uv venv
uv sync --all-extras
.venv/bin/pytest
```

Requirements:
- Python 3.11 or 3.12 (3.11+ enforced by `pyproject.toml`)
- [`uv`](https://docs.astral.sh/uv/) for environment management
- `git` in PATH (`wiki init` runs `git init` on the wiki data repo)
- macOS or Linux (Windows works under WSL; see platform notes in `README.md`)

## Development loop

```bash
# Run the portable test suite (224 tests, ~0.6s)
.venv/bin/pytest

# Run with coverage
.venv/bin/pytest --cov=wiki_system

# Run a single test file
.venv/bin/pytest tests/test_bootstrap.py -v

# Run the live retrieval benchmark (requires a hand-seeded wiki; skipped by default)
.venv/bin/pytest -m integration
```

The `integration` marker is deselected by default because it requires a seeded wiki outside the repo. See `tests/test_retrieval_bar.py` for details.

## Coding conventions

- **Python 3.11+ only.** Use `from __future__ import annotations` for forward refs, `|` union syntax, walrus operator etc.
- **Pydantic v2.** All schema models use `ConfigDict(use_enum_values=True, extra="forbid")` unless there's a documented reason.
- **Deterministic.** No wall-clock comparisons without a reason, no dict-order assumptions, no embeddings or model calls in the core. Retrieval is lexical + link-graph by design — that's a hard constraint, not an implementation detail.
- **Exit code contract:** 0 success / 1 generic / 2 domain rejection / 3 noop / 4 infra unavailable. See `docs/DESIGN.md` §10 for the full table.
- **Single-writer to `pages/`.** Only `wiki promote` writes canonical pages. If you're tempted to bypass that, stop and open a discussion.
- **Tests for every code change.** We use TDD: write the failing test first, watch it fail, then implement. `tests/` mirrors `src/` file-by-file.

## Commit messages

We use [Conventional Commits](https://www.conventionalcommits.org/). Examples:

```
feat(bootstrap): --all loop mode; stateless next-question iteration
fix(cli): exit code 4 for index unavailable
docs(design): add v0.2.2 addendum for noop markers
refactor(staging): extract write_proposed_staged_file
test(bootstrap): add regression test for --all + noop advance
```

Scopes roughly correspond to subsystems: `cli`, `bootstrap`, `sync`, `capture`, `promote`, `query`, `index`, `schema`, `storage`, `init`, `adapter/claude`, `docs`, `repo`.

## Pull requests

- Keep PRs focused. One feature, one fix, one refactor — bundle rather than stacking.
- Include tests for new behavior AND for regression fixes.
- Run `.venv/bin/pytest` locally before pushing. CI will run it on both 3.11 and 3.12.
- Update `docs/DESIGN.md` if you change a design invariant or add a new CLI command. Add a new addendum section rather than rewriting the main spec.
- Update `CHANGELOG.md` under `[Unreleased]`.
- Update `README.md` "Current surface" if you add or remove a shipped command.
- Re-run `.venv/bin/wiki --no-json init` locally if you change adapter templates, so your local symlinks reflect the new content.

## Releases

- Bump `version` in `pyproject.toml`, refresh `uv.lock` (`uv lock`), move the
  `[Unreleased]` CHANGELOG entries under a dated `[x.y.z]` heading, and update
  the README "Current surface" version.
- Tag the release commit on `main` with an annotated tag and push it:
  `git tag -a vx.y.z -m "vx.y.z — one-line summary" && git push origin vx.y.z`.
  Tags exist from v0.2.2 onward.

## Design decisions that are firm

These aren't up for re-litigation without a very good reason:

- **No embeddings / vector retrieval.** Inspectable lexical + link-graph scoring is the design commitment. Retrieval quality tuning means adjusting weights, adding edges, or improving the schema — not reaching for semantic search.
- **Prepare/submit protocol for generative ops.** The CLI never calls an LLM. Prepare emits a prompt package, the agent reasons, submit validates and writes. This is what makes the tool agent-agnostic.
- **Single-writer to `pages/`.** Canonical pages are only touched by `wiki promote`. Hand-edits survive until the next promote of that page, but review tools treat `pages/` as read-only by convention.
- **Filesystem is the storage.** Markdown + YAML frontmatter + a JSON index. No database, no vector store, no server component. `~/Git/wiki/` is meant to be committed to git and viewed in Obsidian or any markdown viewer.

## Questions

Open a GitHub issue with the `question` label, or start a discussion if your thread is longer-form.
