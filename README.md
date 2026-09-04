# wiki-system

A question-led personal wiki compiler. Filesystem-native, agent-first, deterministic.

Turn your project's documentation, specs, and session learnings into a compact, interlinked, agent-readable knowledge base — and query it from any Claude Code session with `/wiki-query`, capture session learnings with `/wiki-capture`, and keep it all version-controlled as plain markdown.

## What problem this solves

If you work with Claude Code (or any agent) across multiple projects, you've probably noticed:

- Agents grep through `docs/` over and over for the same answers
- Hard-won session learnings don't survive `/clear`
- Documentation drifts from the code — the answer in `docs/` stops matching reality
- Adding "memory" to an agent means giving it a doc dump, not curated knowledge

**wiki-system** is the other direction: **compile** durable knowledge into a distilled, curated, interlinked graph, and let the agent retrieve from it deterministically. No embeddings, no vector store, no black box — just markdown pages with YAML frontmatter, a retrieval index, and a lexical + link-graph ranker that you can read and debug.

## Architecture in 30 seconds

Two repos, three layers:

```
┌──────────────────────────────────────────────────────────────┐
│ Claude Code / Codex / any agent                              │
│  /wiki-query, /wiki-capture, /wiki-review, /wiki-promote     │
└──────────────────────────┬───────────────────────────────────┘
                           │ slash commands
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ wiki-system (this repo) — Python CLI + core logic            │
│  query, index, capture prepare/submit, promote, review       │
└──────────────────────────┬───────────────────────────────────┘
                           │ reads + writes
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ ~/Git/wiki/ — your wiki data repo (separate, yours)          │
│  <project>/pages/   ← canonical, promote is the only writer  │
│  <project>/staging/ ← review queue (raw and proposed)        │
│  <project>/views/   ← regenerated map, by-type, by-domain    │
│  <project>/sources/ ← manifest.jsonl audit trail             │
└──────────────────────────────────────────────────────────────┘
```

- **wiki-system** is the tooling repo. Clone it, `uv sync`, run `wiki init` — it's standalone.
- **~/Git/wiki/** is your data repo. A separate git repo that holds pages, staging, and views for every project you wiki-enable. `wiki init` is what creates it on first run: it makes the directory if missing, runs `git init` to turn it into a repo, and seeds `wiki.config.toml` from `wiki.config.example.toml`. **Heads up:** this means `wiki init` mutates `~/Git/wiki/` (or whatever `--wiki-data-root` points at) into a git repo. If that directory already exists and is already a git repo, `wiki init` leaves it alone; it only initializes when there's no `.git` yet. Subsequent `wiki init` runs are idempotent and never re-initialize the repo or overwrite an existing `wiki.config.toml`.
- **Canonical pages** never get edited directly. Every change goes through staging and `wiki promote` — which gives you a diff, a dry-run, an audit trail in `sources/manifest.jsonl`, and a single-writer invariant that prevents hand-edits from silently corrupting the index.

## Platform support

- **macOS and Linux** are first-class. CI runs on Ubuntu with Python 3.11 and 3.12.
- **Windows**: use [WSL](https://learn.microsoft.com/en-us/windows/wsl/). `wiki init` uses `os.symlink` to wire `~/.claude/skills/wiki` → `~/.agents/skills/wiki`, which requires Developer Mode or admin on native Windows. WSL avoids that entirely.
- **Prerequisites**: Python 3.11+, [`uv`](https://docs.astral.sh/uv/) for environment management, and `git` on PATH (`wiki init` runs `git init --quiet` on the wiki data root on first setup).

## Quickstart

```bash
# 1. Install
git clone <this repo> ~/Git/wiki-system
cd ~/Git/wiki-system
uv venv && uv sync

# 2. Preview what `wiki init` will do (optional but recommended)
.venv/bin/wiki --no-json init --dry-run

# 3. Initialize:
#    - creates ~/Git/wiki/ (your wiki data repo) and runs `git init` in it
#    - seeds wiki.config.toml from wiki.config.example.toml
#    - renders adapter templates into ~/.agents/ and symlinks them from ~/.claude/
#    - prints a permissions JSON snippet for ~/.claude/settings.json
.venv/bin/wiki --no-json init

# 4. Edit the seeded config to register your projects
$EDITOR ~/Git/wiki/wiki.config.toml

# 5. Add the printed permissions snippet to ~/.claude/settings.json
$EDITOR ~/.claude/settings.json

# 6. Restart Claude Code. /wiki-query, /wiki-capture, etc. now work.
```

See [`adapters/claude/install/install.md`](adapters/claude/install/install.md) for the full install guide including troubleshooting and uninstall.

## Core operations

| Command | What it does | When to use |
|---|---|---|
| `wiki query <project> "<q>"` | Lexical + link-graph ranked retrieval. No embeddings, no guesses. | Answer a question before falling back to `docs/`. |
| `wiki index <project>` | Rebuild the JSON retrieval index + regenerate `views/index.md`, `views/by-type.md`, `views/by-domain.md`. | After hand-editing config or pulling new pages. |
| `wiki capture prepare` / `submit` | Two-step protocol: prepare emits a prompt package, submit validates a structured proposal and writes a `state: proposed` staged file. | Session-origin captures (via `/wiki-capture`) and upgrading raw staged files. |
| `wiki doctor <project> --graph <graph.json>` | Report code identifiers in canonical pages that no longer exist in an external code graph (stale references). Exit 0 clean / 2 findings / 4 input unavailable. | Detect and flag obsolete identifier references before or after code refactoring. |
| `wiki sync <project>` | Register project docs matching `source_globs` as `state: raw` staged files for later distillation through the capture loop. Scoped by `--path` subtree; `--force` re-stages. | Doc-led wiki growth: "compile these existing markdown files into pages." |
| `wiki bootstrap prepare` / `submit` / `resolve` | Question-led wiki growth from `queries/seed-questions.md`. `prepare` builds a prompt package (single-question or `--all` loop); `submit` validates a proposal and writes either a staged file or a durable noop marker; `resolve --as noop` is a shortcut for known-noop questions. | Distill answers for specific questions; grow a wiki from a seed-question list. |
| `wiki promote <project> <path>` | The ONLY path from staging to `pages/`. Dry-run first (diff on stderr), `--apply` to write. | After `/wiki-capture` or reviewing staging by hand. |
| `wiki review <project>` | Deterministic JSON listing of the staging queue (raw first, then proposed, sorted by `created_at`). Excludes noop markers. | `/wiki-review` in Claude Code. |
| `wiki init` | Generate per-machine adapter artifacts (skill + slash commands + permissions snippet). | First install, and after `git pull` on this repo. |

## Page schema, briefly

Every canonical page is a markdown file at `<wiki-root>/<project>/pages/<id>.md` with YAML frontmatter:

```yaml
---
id: demo-story-pipeline
title: Story Pipeline
summary: End-to-end overview of how a story moves from concept to publication.
type: system                      # system | concept | pattern | decision | workflow | prd | research | runbook | glossary
project: demo
domains: [pipeline, generation]
status: active                    # active | superseded | draft
aliases: [story flow]
sources: [session:2026-04-12-seed]
related: [demo-story-creation-workflow]
updated_at: 2026-04-12
confidence: high                  # high | medium | low
---

# Story Pipeline

…the canonical body…
```

- `id` must be a slug (`^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$`) and unique within the project.
- `confidence: high` requires a non-empty `sources:` list.
- Changes to `pages/` ONLY happen via `wiki promote`. This is enforced by convention, not filesystem permissions, but every promote is atomic, diff'd, audited in `sources/manifest.jsonl`, and auto-reindexes views afterward.
- See [`docs/DESIGN.md`](docs/DESIGN.md) for the full schema, staging envelope, page identity invariant, and ranking model.

## Finding the config

Every command takes `--config PATH`. Without it the CLI reads `WIKI_CONFIG`
(the file), then `WIKI_ROOT/wiki.config.toml`, then `~/Git/wiki/wiki.config.toml`.
Inside the file, a relative `[wiki] root` — `"."` — means the directory the
file is in, so a config committed at the root of a wiki repo works wherever
the repo is cloned. The index and the generated views are per clone: run
`wiki index <project>` after cloning.

## Retrieval model

Lexical scoring over `title`, `aliases`, `domains`, `type`, `headings`, `body`, and `sources`, weighted per `[retrieval] field_weights` in `wiki.config.toml`. Each matched token is discounted by inverse document frequency, so a term found on most pages counts for almost nothing and a rare one counts for a lot; function words are stripped from the question before scoring. Pages with `status: superseded` never score. After lexical hits settle, a 1-hop graph expansion pulls in:

- **Curated edges** from `related:` lists on the matched pages
- **Inferred backlinks** (reverse of curated)
- **Inferred source-overlap** edges (bidirectional when two pages share a source)

A neighbor is scored at most as high as the direct match it came from (the first edge that reaches it counts: curated before inferred), so the edge weights lift related pages above weaker direct hits and never above the page the question actually matched.

The result is a deterministic ranked list with reasons and snippets — the scorer is ~50 lines of Python, not a model, and every decision is inspectable. See `src/wiki_system/query.py`.

## Development

```bash
cd ~/Git/wiki-system
uv sync
.venv/bin/pytest              # 224 portable tests, runs in ~0.6s
.venv/bin/pytest -m integration   # 1 integration test against live wiki data (skipped if unset)
```

- `src/wiki_system/` — core Python package (schema, storage, index, query, promote, capture, review, init, cli).
- `tests/` — pytest suite. Fixtures use `demo` as a generic project name; nothing here references the author's private projects.
- `adapters/claude/templates/` — `{{PLACEHOLDER}}` templates rendered by `wiki init` into per-machine files under `~/.agents/` and symlinked into `~/.claude/`.
- `docs/DESIGN.md` — the authoritative v0.1 design.
- `wiki.config.example.toml` — the template seeded into new wiki data repos.

To develop against your own wiki:

```bash
cp .claude/settings.local.example.json .claude/settings.local.json
# Edit the file, replacing WIKI_SYSTEM_ROOT and WIKI_DATA_ROOT with absolute paths.
```

`.claude/settings.local.json` is gitignored.

## Current surface (v0.3.0)

**CLI commands shipped and tested:**

- `wiki init` — seed `wiki.config.toml` and `git init` the data repo; render the Claude adapter templates with your machine-specific paths and symlink them into `~/.agents/` (canonical) + `~/.claude/` (symlinks). Idempotent.
- `wiki query <project> "<q>"` — lexical + link-graph retrieval. Exit 4 if the index is unavailable (distinct from exit 2 "no results"), so machine callers can tell "wiki has nothing on this topic" apart from "wiki isn't queryable."
- `wiki index <project>` — rebuild the retrieval index + regenerate views
- `wiki capture prepare|submit` — session-origin and staged-upgrade capture
- `wiki doctor <project> --graph <graph.json>` — stale-refs report against an external AST code graph, exit 0 clean / 2 findings / 4 input unavailable
- `wiki promote <project> <staging-path>` — dry-run or `--apply` a proposed staged file
- `wiki review <project>` — deterministic listing of the staging queue
- `wiki sync <project> [--path <subtree>] [--force]` — register project docs matching `source_globs` as `state: raw` staged files. Manual / operator-driven; hook-driven triggers remain deferred. Dedupes against both raw staged files and proposed files upgraded from them (so `sync → capture → sync` cannot produce duplicates).
- `wiki bootstrap prepare|submit <project>` — seed-question-driven page synthesis. Supports both single-question mode (`--question "..."`) and a stateless `--all` loop (`--all --max-proposals=N`) that walks `queries/seed-questions.md` and emits one unprocessed question per invocation. The prompt package includes a skim-friendly `summary` field so agents can decide noop upfront without parsing the full context. Noop decisions persist as markers under `staging/.bootstrap-noops/` so `--all` advances past them correctly (fix for the pre-v0.2.2 infinite-loop bug on well-seeded wikis).
- `wiki bootstrap resolve <project> --question "..." --as noop [--reason "..."]` — shortcut to durably record a noop decision without running the full prepare/synthesize/submit cycle. Useful when the user already knows a seed question doesn't need bootstrapping.

**Claude adapter surface:**

- One main `wiki` skill + one pluggable `wiki-bootstrap` sub-skill (installed as separate files under `~/.agents/skills/`, symlinked into `~/.claude/skills/`)
- Six slash commands: `/wiki-query`, `/wiki-capture`, `/wiki-review`, `/wiki-promote`, `/wiki-sync`, `/wiki-bootstrap` (the last covers `bootstrap prepare`, `submit`, and `resolve`)
- All templates render the binary as an absolute path — no PATH inheritance required
- Execution is agent-mode only (prepare/submit protocol drives Claude Code; direct-API mode is v0.2+)

**Still deferred:**

- Manifest-aware "already promoted" dedupe for `--all` (questions whose pages were promoted and archived still re-emit unless the user deletes the seed line or runs `bootstrap resolve --as noop`) (v0.2.4)
- Hook-driven `wiki sync` (post-spec, post-commit triggers) (v0.2)
- `wiki blame`, `wiki export-site` (v0.2.x)
- Direct-API execution mode (no Claude Code session required) (v0.2)
- Codex adapter (v0.3, architecture already set up for it)
- Embeddings / vector retrieval (explicitly rejected — inspectability wins)
- Multi-user or shared-wiki workflows (v0.3)
- A browser UI (markdown views are the UI for now; Obsidian is the recommended reader)

## License

MIT — see [`LICENSE`](LICENSE).
