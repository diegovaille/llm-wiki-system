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
- **~/Git/wiki/** is your data repo. A separate git repo that holds pages, staging, and views for every project you wiki-enable. `wiki init` seeds it from `wiki.config.example.toml` on first run.
- **Canonical pages** never get edited directly. Every change goes through staging and `wiki promote` — which gives you a diff, a dry-run, an audit trail in `sources/manifest.jsonl`, and a single-writer invariant that prevents hand-edits from silently corrupting the index.

## Quickstart

```bash
# 1. Install
git clone <this repo> ~/Git/wiki-system
cd ~/Git/wiki-system
uv venv && uv sync

# 2. Initialize (creates wiki data repo, installs adapter, prints permissions snippet)
.venv/bin/wiki --no-json init

# 3. Edit the seeded config to register your projects
$EDITOR ~/Git/wiki/wiki.config.toml

# 4. Add the printed permissions snippet to ~/.claude/settings.json
$EDITOR ~/.claude/settings.json

# 5. Restart Claude Code. /wiki-query, /wiki-capture, etc. now work.
```

See [`adapters/claude/install/install.md`](adapters/claude/install/install.md) for the full install guide including troubleshooting and uninstall.

## The six operations

| Command | What it does | When to use |
|---|---|---|
| `wiki query <project> "<q>"` | Lexical + link-graph ranked retrieval. No embeddings, no guesses. | Answer a question before falling back to `docs/`. |
| `wiki index <project>` | Rebuild the JSON retrieval index + regenerate `views/index.md`, `views/by-type.md`, `views/by-domain.md`. | After hand-editing config or pulling new pages. |
| `wiki capture prepare` / `submit` | Two-step protocol: prepare emits a prompt package, submit validates a structured proposal and writes a `state: proposed` staged file. | Session-origin captures (via `/wiki-capture`) and upgrading raw staged files. |
| `wiki promote <project> <path>` | The ONLY path from staging to `pages/`. Dry-run first (diff on stderr), `--apply` to write. | After `/wiki-capture` or reviewing staging by hand. |
| `wiki review <project>` | Deterministic JSON listing of the staging queue (raw first, then proposed, sorted by `created_at`). | `/wiki-review` in Claude Code. |
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

## Retrieval model

Lexical scoring over `title`, `aliases`, `domains`, `type`, `headings`, and `body`, weighted per `[retrieval] field_weights` in `wiki.config.toml`. After lexical hits settle, a 1-hop graph expansion pulls in:

- **Curated edges** from `related:` lists on the matched pages
- **Inferred backlinks** (reverse of curated)
- **Inferred source-overlap** edges (bidirectional when two pages share a source)

The result is a deterministic ranked list with reasons and snippets — the scorer is ~50 lines of Python, not a model, and every decision is inspectable. See `src/wiki_system/query.py`.

## Development

```bash
cd ~/Git/wiki-system
uv sync
.venv/bin/pytest              # 109 portable tests, runs in ~0.3s
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

## Scope (v0.1)

**In scope for v0.1:**

- Core CLI (`query`, `index`, `capture prepare/submit`, `promote`, `review`, `init`)
- Agent execution mode via prepare/submit (Claude Code tested; other agents untested but designed-for)
- Single-developer, local filesystem, manual commits to `~/Git/wiki/`
- Claude adapter with one skill and four slash commands

**Out of scope for v0.1, deliberate:**

- `wiki sync` — hook-driven artifact registration from live project repos (v0.2)
- `wiki bootstrap` — question-led scaffolding of initial pages (v0.2)
- Direct-API execution mode (calls Claude without a Claude Code session) (v0.2)
- Embeddings / vector retrieval (explicitly rejected — inspectability wins)
- Multi-user or shared-wiki workflows (v0.3)
- A browser UI (markdown views are the UI for now; `mkdocs` or Obsidian will work if you want prettier rendering)

## License

MIT — see [`LICENSE`](LICENSE).
