---
title: wiki-system — Design
status: draft
date: 2026-04-12
---

# wiki-system — Design

> **Status:** This is the authoritative v0.1 design. The project names used
> below (`project-alpha`, `project-beta`, `project-gamma`) and id prefixes
> (`pa-`, `pb-`) are illustrative. Absolute paths like `~/Git/wiki/` are the
> default layout but can be overridden via `wiki.config.toml`.

## 1. Purpose

`wiki-system` is a question-led personal wiki compiler that turns project documentation, specs, and session learnings into a compact, interlinked, agent-readable knowledge base. It is filesystem-native, agent-first, and deterministic at query time.

The goal is to serve three audiences from the same corpus:

1. **The human operator** — a single place to browse distilled, durable knowledge across projects.
2. **Agentic runtimes in-session** (Claude Code, Codex) — a stable retrieval surface that returns relevant pages on demand, so agents start with compiled knowledge instead of cold context.
3. **Future sharing on GitHub** — an agent-agnostic tool others can adopt without inheriting a specific provider, directory layout, or personal corpus.

The core invariant: the wiki is **compiled knowledge**, not a mirror of documentation. Pages answer recurring questions; raw specs, meeting notes, and transient plans stay in their project repos.

## 2. Non-goals

- No vector DB or embeddings-based retrieval in v0.1. Retrieval is deterministic lexical + link-graph ranking.
- No autonomous mid-session agent capture. Agents never decide to promote their own in-flight reasoning into the wiki.
- No automatic promotion of hook output to canonical pages. Hooks land in `staging/`; canonical writes are human-approved.
- No bulk doc mirroring during bootstrap. Bootstrap is question-led, page-budgeted, and may emit "no page generated."
- No multi-user or collaboration features.
- No GUI. The system is a filesystem and a set of operations.
- Not GPL-licensed. License will be MIT or Apache-2 to maximize adoption.

## 3. Architecture

Three layers, strictly separated:

```
┌────────────────────────────────────────────────┐
│  Adapters (Claude plugin, later Codex)         │  how agents invoke
├────────────────────────────────────────────────┤
│  Core engine (ops + schema + retrieval)        │  agent-agnostic
├────────────────────────────────────────────────┤
│  Data (~/Git/wiki/, plain MD + YAML)           │  portable, auditable
└────────────────────────────────────────────────┘
```

Two repositories, separated by lifecycle:

- `wiki-system/` — the tooling (shareable, agent-agnostic core + Claude adapter)
- `~/Git/wiki/` — the wiki data (private, per-user, separate git repo)

This separation is load-bearing. The tooling can be open-sourced and shared without exposing any user's corpus, and the corpus can evolve without touching the tool's release cadence.

## 4. Repository structure: `wiki-system/`

```
wiki-system/
├── README.md
├── LICENSE                           # MIT or Apache-2
├── pyproject.toml                    # Python core, uv-managed
├── wiki.config.example.toml          # portable config template
├── src/
│   └── wiki_system/
│       ├── __init__.py
│       ├── bootstrap.py              # question-led seeding
│       ├── capture.py                # capture prepare/submit backend
│       ├── query.py                  # lexical + link-graph retrieval
│       ├── sync.py                   # artifact-to-staging (register-only)
│       ├── promote.py                # staging → canonical page
│       ├── index.py                  # retrieval index + view regeneration
│       ├── schema.py                 # frontmatter validation, page types
│       ├── storage.py                # filesystem read/write, path resolution
│       └── cli.py                    # single `wiki` entrypoint
├── adapters/
│   ├── claude/
│   │   ├── .claude-plugin/
│   │   │   └── plugin.json
│   │   ├── skills/
│   │   │   └── wiki/
│   │   │       └── SKILL.md
│   │   ├── commands/
│   │   │   ├── wiki-query.md
│   │   │   ├── wiki-capture.md
│   │   │   ├── wiki-bootstrap.md     # v0.2
│   │   │   ├── wiki-promote.md
│   │   │   └── wiki-review.md
│   │   ├── hooks/
│   │   │   └── post-spec-sync.sh     # v0.2
│   │   └── install/
│   │       ├── install.md
│   │       └── claude-md-snippet.md
│   └── codex/                        # v0.3+
│       └── README.md
├── templates/
│   ├── project/
│   │   ├── meta/project.md.j2
│   │   ├── queries/seed-questions.md.j2
│   │   └── views/index.md.j2
│   └── cross-project/
│       └── views/index.md.j2
├── docs/
│   ├── architecture.md
│   ├── page-types.md
│   ├── ranking.md
│   └── adding-adapters.md
└── tests/
    ├── fixtures/                     # sample wikis for golden tests
    ├── test_query_ranking.py
    ├── test_schema.py
    ├── test_capture_submit.py
    ├── test_promote.py
    └── test_index.py
```

The core is Python, `src/`-layout, `uv`-managed. Python was chosen for filesystem-heavy workflows, ease of shell integration, and low-friction CLI packaging.

## 5. Data structure: `~/Git/wiki/`

```
~/Git/wiki/
├── wiki.config.toml                  # local config
├── .gitignore
├── project-alpha/
│   ├── meta/
│   │   └── project.md                # project intent + what belongs here
│   ├── pages/                        # canonical compiled knowledge
│   ├── sources/
│   │   └── manifest.jsonl            # audit trail, content hashes
│   ├── queries/
│   │   ├── seed-questions.md
│   │   └── <durable-research>.md
│   ├── staging/                      # hook-generated + bootstrap candidates
│   └── views/
│       ├── index.md                  # lightweight project map (session-start)
│       ├── by-type.md                # generated
│       └── by-domain.md              # generated
├── project-beta/
│   └── <same shape>
├── project-gamma/
│   └── <same shape>
└── cross-project/
    ├── meta/
    │   └── project.md
    ├── pages/                        # synthesis only, never duplicates
    ├── queries/
    ├── staging/                      # cross-project also has staging
    └── views/
        └── index.md
```

### Structural rules

- `pages/` is the only canonical source of truth. Everything else is input, staging, or generated view.
- `staging/` is never consumed by agents during normal `wiki query` calls. It is a review queue.
- `views/` is always regenerated from `pages/` + frontmatter + templates. Hand-edits are overwritten. Single-writer invariant.
- `meta/project.md` defines project intent, scope, and what kinds of knowledge belong in the wiki — used by bootstrap, capture, and human orientation.
- `queries/` is deliberately sparse. It holds seed questions and a small number of durable research outputs. It is not a transcript graveyard.
- `cross-project/pages/` holds synthesis pages only. Canonical per-project knowledge lives in the project subtree and is never duplicated.

### Page schema (frontmatter)

```yaml
---
id: pb-moderation-system            # slug, unique within project
title: Project Beta Moderation System
summary: End-to-end overview of moderation architecture, policy config, and routing.
type: system                        # see page types below
project: project-beta                 # kept even inside project subtree
domains: [moderation, policy, safety]
status: active                      # active|superseded|draft
superseded_by: pb-moderation-v2     # optional, when status == superseded
aliases: ["moderation engine", "content moderation"]
sources:                            # audit trail (future-proof naming)
  - docs/content-moderation-engine.md
  - docs/superpowers/specs/2026-04-01-moderation-rule-catalog-design.md
  - linear:CC-482                   # future: non-doc sources allowed
related:                            # CURATED edges
  - pb-dynamic-policy-prompt-builder
  - pb-incident-routing
updated_at: 2026-04-12
confidence: high                    # high|medium|low
---
```

**Page types** (`type:` field): `decision`, `concept`, `pattern`, `system`, `workflow`, `prd`, `research`, `runbook`, `glossary`.

**`sources:` field — what counts as a source:**

The `sources:` list is an audit trail, not strictly a list of documents. Valid source forms:

- **Doc paths** (project-relative): `docs/content-moderation-engine.md`
- **Spec paths**: `docs/superpowers/specs/2026-04-01-foo-design.md`
- **External IDs** (future): `linear:CC-482`, `notion:abc123`, `figma:file/xyz`
- **Session origins**: `session:2026-04-12-<slug>` — for pages that came from in-session capture, where the origin is a conversation rather than a document

A capture-originated page MUST include at least one `session:<date>-<slug>` entry so its origin is auditable. A bootstrap-originated page MUST list the doc paths that informed it. A sync-registered artifact MUST include its `source_path` as a source. The list may never be empty for pages with `confidence: high`.

**Edge classes** (important for ranking):
- **Curated edges** — explicit `related:` links. Heavy weight in ranking.
- **Inferred edges** — backlinks and shared `sources:`. Lighter weight, distinct signal class. Computed by `wiki index`, not stored in frontmatter.

### Staged file schema

Everything in `<project>/staging/` is a staged file. Every staged file is a Markdown file with YAML frontmatter. The frontmatter alone is the structured payload; the body of the file is used only in the `raw` case. **Staged files never contain nested frontmatter blocks.** The canonical page (for `state: proposed`) is embedded as a typed object inside the staged file's frontmatter.

#### Shape of a `state: raw` staged file

```yaml
---
state: raw
origin: sync                        # sync | manual
created_at: 2026-04-12T14:30:00Z
created_by: post-spec-hook          # operation or hook name
source_artifact: docs/superpowers/specs/2026-04-12-foo-design.md  # required
source_commit: abc123               # optional
trigger: post-spec                  # required for sync, matches sync_event
raw_body_mode: inline               # inline | pointer
raw_body_bytes: 14823                # optional, for diagnostics
---

<raw artifact content goes here when raw_body_mode == inline>
<empty when raw_body_mode == pointer — capture must dereference source_artifact>
```

- **`raw_body_mode: inline`** — the artifact content is embedded in the file body. Cheap to read, self-contained.
- **`raw_body_mode: pointer`** — the body is empty (or a short abstract) and the authoritative content must be re-read from `source_artifact` at the project repo path.

The `sync` command chooses `inline` when the artifact is under a configurable size threshold (default 64 KiB) and `pointer` otherwise. This keeps staging lightweight for large artifacts without losing the ability to synthesize later.

#### Shape of a `state: proposed` staged file

```yaml
---
state: proposed
origin: capture                     # capture | bootstrap
created_at: 2026-04-12T14:35:00Z
created_by: capture                 # operation name
proposed_action: create             # create | update
target_page_id: null                # required when proposed_action == update
upgraded_from:                      # present when capture upgraded a raw file
  raw_file: staging/2026-04-12-post-spec-foo.md
  origin: sync
  trigger: post-spec
  source_artifact: docs/superpowers/specs/2026-04-12-foo-design.md
canonical_page:
  frontmatter:
    id: pa-story-pipeline
    title: Project Alpha Story Pipeline
    summary: End-to-end view of story creation, review, and publication.
    type: system
    project: project-alpha
    domains: [pipeline, generation, review]
    status: active
    aliases: ["story pipeline", "story flow"]
    sources:
      - session:2026-04-12-story-flow
    related: []
    updated_at: 2026-04-12
    confidence: high
  body: |
    # Project Alpha Story Pipeline

    The pipeline consists of three stages: authoring, illustration,
    and review. Each stage is operated by a distinct service...
    (full markdown body of the canonical page)
---

(file body is empty for state: proposed — or may contain human review notes
 that are NOT used by promote)
```

**Parsing contract:**

- `promote` reads **only the frontmatter** of a proposed staged file. Specifically, it reads `canonical_page.frontmatter` and `canonical_page.body`, writes them as a standard `pages/<id>.md` file (body becomes the file body, frontmatter becomes the file frontmatter).
- The staged file's own body (outside the YAML frontmatter) is never read by `promote`. It is available for optional human review notes.
- `canonical_page.body` is a YAML block scalar (`|`), which handles arbitrary markdown content including `---` separators without escaping.
- `capture submit` and `bootstrap submit` are responsible for serializing a valid staged file in this exact shape. The core provides a single serializer used by both.

**Page identity invariant (for `proposed_action: update`):**

When `proposed_action: update`, the following MUST hold:

1. `target_page_id` is non-null and refers to an existing page in `<project>/pages/`
2. `canonical_page.frontmatter.id` MUST equal `target_page_id` — **exact string match**
3. The referenced page must exist at write time (checked by `promote`)

**Why:**

This prevents three classes of ambiguity that would otherwise force `promote` to guess:

- **Identity drift** — an update silently changing a page's `id` and breaking every `related:` edge and backlink that points at the old id
- **Wrong-page update** — a proposal intended for page A being applied to page B because the fields disagree
- **Implicit rename** — `update` being used as a backdoor for renaming, which should never happen through this path

**Enforcement:**

- `capture submit` and `bootstrap submit` validate the invariant **before** writing a proposed staged file. A violation returns exit code 2 (schema-invalid).
- `promote` re-validates the invariant **before** applying. A violation returns exit code 2 and leaves the staged file and canonical page untouched.
- For `proposed_action: create`, `target_page_id` MUST be null, and `canonical_page.frontmatter.id` MUST NOT collide with any existing page id (promote checks at write time).

**No rename path in v0.1 or v0.2.** Renaming a canonical page is explicitly out of scope — it would require coordinated updates to curated `related:` edges and recomputation of inferred edges across the project subtree. If this is ever needed, it becomes its own operation (`wiki rename`) with its own schema and tests, not a flavor of `update`.

**Why this shape:**

- Single parseable YAML document — no nested frontmatter, no ambiguous delimiters
- Round-trippable: `submit` serializes, `promote` parses, both without custom logic
- Testable: golden fixtures for the YAML envelope are trivial to author
- Human-readable enough for `/wiki-review` to display `canonical_page.frontmatter.title` and a snippet of `canonical_page.body`

#### State semantics

- **`state: raw`** — a registered artifact. Cannot be promoted. Must be upgraded to `state: proposed` via `capture --from-staged`.
- **`state: proposed`** — a fully-formed canonical page draft, embedded in frontmatter. Can be promoted directly.

#### Who writes which state

- `wiki sync` writes only `state: raw` staged files.
- `wiki capture submit` with `--from-staged=<raw-file>` writes `state: proposed` staged files. The raw file is archived (moved to `staging/.archive/`) or replaced in place — configurable. In both cases, the `upgraded_from` block on the proposed file records the raw origin.
- `wiki capture submit` without `--from-staged` (session-origin capture) also writes `state: proposed` staged files with `origin: capture` and no `upgraded_from` block.
- `wiki bootstrap submit` writes `state: proposed` staged files with `origin: bootstrap`, one per seed question.
- `wiki promote` accepts ONLY `state: proposed` files. A `state: raw` file is rejected with exit code 2 and a message pointing at `/wiki-capture`.

This staged-file schema is the shared contract between `sync`, `capture`, `promote`, and `/wiki-review`. All four operations read and write these fields through the same core serializer.

**Staging state flow:**

```
┌──────────┐   wiki sync         ┌─────────────┐
│ artifact │ ───────────────────▶│ state: raw  │
└──────────┘                     └──────┬──────┘
                                        │
                                        │ wiki capture submit --from-staged
                                        ▼
┌──────────┐   wiki capture      ┌──────────────────┐   wiki promote    ┌───────┐
│ session  │ ───────────────────▶│ state: proposed  │ ────────────────▶ │ pages │
└──────────┘                     └──────────────────┘                   └───────┘
                                        ▲
                                        │
                                 wiki bootstrap
                                        │
                                 ┌──────┴──────┐
                                 │ seed Q + docs│
                                 └──────────────┘
```

Every path to `pages/` goes through `state: proposed` staging. Nothing writes to `pages/` except `promote`. `capture` without `--from-staged` still produces a staged file first — the staging layer is universal, even for session-origin captures.

## 6. Core operations

Six operations, each backed by a core module and exposed as a CLI subcommand. Adapters wrap these; they do not reimplement logic.

Operations split into two categories:

- **Deterministic** (no execution backend needed): `query`, `index`, `promote`, `sync`
- **Generative** (needs backend): `bootstrap`, `capture`

### 6.1 `wiki query <project> "<question>" [--limit=N]`

Deterministic retrieval. The stable contract that all adapters consume.

**Ranking signals:**
1. Exact matches on `title` and `aliases` (highest weight; `id` is not scored)
2. `domains:` and `type:` matches from frontmatter (mid weight)
3. Heading-level matches within page bodies
4. Body token matches (lowest lexical weight)
4a. `sources:` token matches (same weight as body) — the only field where a ticket id such as `CLA-1810` lives when the body does not name it
5. 1-hop expansion through curated `related:` edges: `min(source * 0.6 + curated_edge_weight, source)`
6. Inferred edges: backlinks and `sources:` overlap: `min(source * 0.3 + inferred_edge_weight, source)`, distinct class. A graph row never outranks the direct match it came from, nor a sibling neighbor of the same source that matched the question directly; on a tie the direct match wins. Direct matches keep their own scores.
7. Recency as **weak tiebreaker only** — never outranks a more canonical page

Every lexical match is weighted by inverse document frequency over the union of the scored fields, and stopwords are stripped from the question (never from pages). Both were added in 0.4.0 after measuring that sentence-shaped aliases scored per token at weight 4.0 made alias-heavy pages win any sentence-shaped question on function words alone. Superseded pages are excluded before scoring and from graph expansion. Draft pages are retrievable.

There is no `tags:` field. Ranking signals reference only fields that exist in the schema (`domains:`, `type:`, `aliases:`, etc.).

**Output (JSON on stdout):**

```json
[
  {
    "id": "pb-moderation-system",
    "title": "Project Beta Moderation System",
    "summary": "End-to-end overview…",
    "path": "project-beta/pages/cc-moderation-system.md",
    "score": 0.87,
    "matched_fields": ["title", "domains"],
    "match_source": "lexical",
    "reasons": ["title match: 'moderation'", "domain match: 'moderation'"],
    "snippet": "The moderation pipeline consists of three stages…"
  }
]
```

`matched_fields` is separate from human-readable `reasons` to support ranking debugging. `match_source` is one of `lexical` or `graph` so callers can see whether a hit came from direct text matching or 1-hop graph expansion.

The command never calls an LLM. Retrieval is fully testable with golden fixtures.

### 6.2 `wiki index <project> [--strict] [--normalize]`

Deterministic. Maintains the retrieval index and regenerates views.

- Walks `pages/`, parses frontmatter
- Builds `.wiki-index.json` — tokens, curated edges, inferred edges (backlinks + `sources:` overlap), field weights
- Regenerates `views/index.md`, `views/by-type.md`, `views/by-domain.md` from templates + live data (not purely mechanical — templates add curated structure)
- Validates frontmatter against schema
- `--strict`: schema warnings exit nonzero (validation-only, not rewrite)
- `--normalize`: opt-in frontmatter normalization (distinct from strict)
- Auto-invoked after any operation that writes to `pages/`

**Single-writer invariant:** only `wiki index` writes to `views/`.

### 6.3 `wiki capture [--project=<name>] [--session-notes=-] [--from-staged=<path>]`

Generative. Backend for `/wiki-capture`. Uses the prepare/submit protocol.

**Two input modes:**

1. **Session-origin capture** — `--session-notes=-`. Input is session context. Sources recorded as `session:<date>-<slug>`.
2. **Staged-upgrade capture** — `--from-staged=<raw-file>`. Input is a `state: raw` staged file (typically hook-generated via `sync`). Sources recorded as the original `source_artifact`. Upgrades raw → proposed.

**Protocol:**

```
wiki capture prepare --project=<name> [--session-notes=- | --from-staged=<path>]
  → reads input + existing pages/views
  → builds prompt package
  → emits JSON to stdout: { system, context, schema, instructions, allowed_actions }

wiki capture submit --project=<name> --proposal=- [--from-staged=<path>]
  → reads structured proposal from stdin
  → validates against page schema + staged-file schema
  → writes a state: proposed staged file to <project>/staging/
      - session-origin mode: new file with origin: capture, sources include session:<date>-<slug>
      - staged-upgrade mode: replaces the raw file in place, upgrading its state to proposed
  → emits JSON: { action, staging_path, proposed_page_id }
```

**Hard rules enforced by the core:**
- At most ONE canonical change per capture (noop, one update, or one create — never multiple)
- Proposal must include `action: noop|update|create` and `target_page_id` when `action == update`
- `noop` result writes nothing to staging. For `--from-staged` mode, a noop leaves the raw staged file in place so it can be revisited or rejected.
- When `action != noop`, a capture-originated proposed page MUST include a `session:<date>-<slug>` entry in `sources:` (session-origin mode) or carry the original `source_artifact` in `sources:` (staged-upgrade mode). This is how the audit trail is satisfied.
- Bias toward noop and update, configured in `[capture]` section of config
- Schema validation is non-negotiable — malformed proposals exit with code 2

**Capture never writes to `pages/` directly.** It writes `state: proposed` staged files. Canonicalization happens via `promote`, which is the single writer to `pages/`. This keeps the audit surface uniform across capture-, sync-, and bootstrap-originated content.

The core owns schema validation and write paths even when a host agent produces the proposal. This prevents adapter drift.

### 6.4 `wiki promote <project> <staging-file> [--apply]`

Deterministic. The only writer to `pages/`. Promotes a single staged file into canonical content.

- **Requires `state: proposed`.** A `state: raw` staged file is rejected with exit code 2 and a message pointing the user at `/wiki-capture --from-staged=<path>`.
- Reads the staged file's `proposed_action`, `target_page_id`, and page frontmatter/body
- Shows the proposed change (diff for `update`, full page for `create`) on stderr
- Emits JSON on stdout: `{ action, page_id, path }`
- Without `--apply`: dry-run, exit code 3
- With `--apply`:
  - Writes to `pages/<id>.md` (create) or applies the update (update)
  - Moves the staging file to `<project>/staging/.archive/` (rotating log of what was promoted) or deletes it — configurable
  - Updates `sources/manifest.jsonl` with the new canonical entry
  - Triggers `wiki index`
- Enforces **one canonical change per staged item** — a staged file that would create or update more than one page is rejected
- Adapters never skip `promote` for automation-sourced content. `promote` is the only path to `pages/`, full stop.

### 6.5 `wiki sync <project> --event=<type> --artifact=<path>`

Deterministic. Narrow by design. Conceptually: "register artifact," not "understand artifact."

- Reads the artifact (e.g., a spec file), extracts minimal metadata
- Writes a staged file to `<project>/staging/<timestamp>-<slug>.md` with **`state: raw`**
- The staged file conforms to the `state: raw` shape defined in Section 5 (frontmatter includes `state`, `origin`, `source_artifact`, `trigger`, `raw_body_mode`, etc.)
- Chooses `raw_body_mode` based on a configurable size threshold:
  - `inline` when the artifact is under `[sync].inline_threshold_bytes` (default 65536)
  - `pointer` otherwise — file body is empty; `source_artifact` is the authoritative location
- Does **not** compare, synthesize, or call an LLM

**Dereference rule for `--from-staged` consumers:**

`wiki capture prepare --from-staged=<raw-file>` MUST apply the following rule when building its prompt package:

1. Parse the staged file's frontmatter
2. If `raw_body_mode == inline`, use the staged file's body as the artifact content
3. If `raw_body_mode == pointer`, **re-read the artifact from `source_artifact`** (resolved against the project's `repo_path` in `wiki.config.toml`) and use that content
4. If `source_commit` is present and differs from the current HEAD of the project repo, emit a warning — the artifact may have changed since it was registered, and the prompt package should note this so the synthesis step can flag drift

This dereference rule is the core's responsibility, not the adapter's. It lives in `capture.py` so the same logic works regardless of execution backend.

**What happens next:** a `state: raw` staged file is not promotable. It must be upgraded to `state: proposed` via `wiki capture --from-staged=<path>`. This keeps synthesis in the generative layer (capture) and keeps sync as pure artifact registration.

Staging-always is the rule. `wiki sync` never writes to `pages/`.

### 6.6 `wiki bootstrap <project> [--pass=<name>] [--max-pages=6]`

Generative. Question-led seeding for a tracked project. Uses prepare/submit like `capture`.

- Reads `<project>/queries/seed-questions.md` and `<project>/meta/project.md`
- For each question, pulls relevant source docs from the project repo via `source_globs` in config
- Produces one candidate per question, written as a **`state: proposed`** staged file with `origin: bootstrap`
- The proposed page's `sources:` list contains the project-relative paths of the source docs that informed it — satisfying the audit trail requirement
- May emit "no page generated" when evidence is weak or redundant — not every question must produce a staged file
- Can update an existing canonical concept in a later pass (proposed with `action: update` and `target_page_id`), not only create new pages
- Hard `--max-pages` budget; default 6
- Phased passes: `--pass=system-maps` → `--pass=decisions` → `--pass=synthesis`
- Every bootstrap-produced staged file still goes through `wiki promote` for canonical write. Bootstrap never writes to `pages/` directly.

Bootstrap runs via the adapter's host agent by default (agent mode) or through direct LLM mode for batch use.

## 7. Execution backend abstraction

Generative operations (`bootstrap`, `capture`) need a model to produce proposals. The core defines the task shape and expected structured output; the backend provides the model execution.

```
┌────────────────────────────────────┐
│  Generative operation              │  bootstrap / capture
│  (defines prompt + schema)         │
└────────────────┬───────────────────┘
                 │ request
                 ▼
┌────────────────────────────────────┐
│  Execution backend                 │
│  ├─ agent mode (default)           │  adapter hands context to host agent
│  │  ├─ claude-code                 │  (Claude reasons in-session)
│  │  └─ codex (v0.3+)               │
│  └─ direct mode (opt-in, v0.3)     │  core calls provider API directly
│     └─ anthropic, openai, …        │  for batch/background/standalone
└────────────────────────────────────┘
```

The prepare/submit protocol is what makes this abstraction work:

1. `<op> prepare` emits a JSON prompt package — agent-runtime-agnostic
2. Host agent (or direct LLM) produces a structured proposal
3. `<op> submit` validates the proposal against the core's schema and writes

**Deterministic ops never need a backend.** A user can adopt the system with zero provider keys by using only `query`, `index`, and `promote` plus hand-written pages and hand-written staging items. This is the default adoption path for anyone who wants the filesystem layer without agent-mode capture. For v0.1, this path exists alongside the agent-mode `capture` loop; `sync` and hooks are deferred to v0.2.

## 8. Configuration (`~/Git/wiki/wiki.config.toml`)

```toml
[wiki]
root = "~/Git/wiki"

[execution]
mode = "agent"                       # default: agent mode

[execution.agent]
runtime = "claude-code"              # or "codex"
model_hint = "opus"                  # guidance only

[execution.direct]                   # optional, v0.3
provider = "anthropic"
model = "claude-opus-4-6"
api_key_env = "ANTHROPIC_API_KEY"

[[projects]]
name = "project-alpha"
repo_path = "~/Git/project-alpha"
source_globs = [
  "docs/**/*.md",
  "prompts/**/*.md",
]

[[projects]]
name = "project-beta"
repo_path = "~/Git/project-beta"
source_globs = [
  "docs/**/*.md",
  "docs/superpowers/specs/**/*.md",
]

[retrieval]
field_weights = { title = 5.0, aliases = 4.0, domains = 3.0, type = 2.0, headings = 2.0, body = 1.0 }
curated_edge_weight = 3.0
inferred_edge_weight = 1.0
recency_tiebreaker_days = 30

[capture]
bias_toward_noop = true
bias_toward_update = true

[sync]
inline_threshold_bytes = 65536       # below this, raw staged files inline content
                                     # above this, raw_body_mode = pointer

[index]
schema_warnings = "non-fatal"

# Hooks config is path-class based, not extension based (v0.2+)
[[hooks]]
event = "post-write"
match = "docs/superpowers/specs/**/*.md"
sync_event = "post-spec"
```

Provider API keys are not required for v0.1 deterministic ops. Keys are only relevant for direct mode (v0.3).

## 9. Claude adapter

The adapter must stay thin. The prepare/submit protocol enforces this: the adapter has no domain logic, no schema knowledge, no write paths — only orchestration.

### 9.1 Plugin contents

```
adapters/claude/
├── .claude-plugin/
│   └── plugin.json
├── skills/
│   └── wiki/
│       └── SKILL.md                  # how to use the wiki, retrieval contract
├── commands/
│   ├── wiki-query.md
│   ├── wiki-capture.md
│   ├── wiki-bootstrap.md             # v0.2
│   ├── wiki-promote.md
│   └── wiki-review.md
├── hooks/
│   └── post-spec-sync.sh             # v0.2
└── install/
    ├── install.md
    └── claude-md-snippet.md
```

### 9.2 The `wiki` skill

A single skill that loads on-demand. Teaches Claude:

- Where the wiki lives and how it is structured
- The retrieval contract: always use `wiki query`, never ad-hoc grep into wiki pages
- The capture threshold and under-capture bias
- The six operations and when to use each
- The prepare/submit protocol and how to respond when handed a prompt package
- **Explicitly: do not autonomously invoke capture mid-session**

The skill's description triggers on tasks involving "wiki", "`/wiki-*`", "search project knowledge", "capture a decision", or when the session-start map references `wiki query`.

### 9.3 Slash command behavior

**`/wiki-query`** (deterministic passthrough):
1. Detect project from working directory via `wiki.config.toml`
2. Run `wiki query <project> "$ARGUMENTS" --limit=5`
3. Format JSON results with snippets and match reasons
4. Claude then uses `Read` on the top 1-3 matching page files as needed
5. Falls back to raw project docs only if the wiki does not answer

**`/wiki-capture`** (prepare/submit via agent mode, auto-chains through promote):
1. Detect project from working directory
2. Collect session notes (recent assistant turns + any user `$ARGUMENTS`)
3. Run `wiki capture prepare --project=<name> --session-notes=-` with notes piped in
4. Load the `wiki` skill if not already loaded
5. Hand Claude the prompt package; Claude produces a structured proposal matching `allowed_actions`
6. Show the user a 3-line summary: diff for update, abstract for create, or "no capture needed"
7. On confirmation, run `wiki capture submit --project=<name> --proposal=-` (writes a `state: proposed` staged file)
8. Immediately auto-chain: run `wiki promote <project> <staging-path> --apply` using the `staging_path` returned by submit
9. Report the canonical page path and action taken

The staging step is still there (for audit and consistency), but the slash command makes it invisible for session-origin captures: one user confirmation, one canonical write. For staged-upgrade captures (via `/wiki-review` → `/wiki-capture --from-staged`), the user explicitly sees the upgrade-then-promote steps as distinct.

**Auto-chain failure semantics (intentional, recoverable):**

The `submit → promote` auto-chain is two operations, not one atomic transaction. If `submit` succeeds and `promote --apply` fails (for example: schema warning in strict mode, index write conflict, disk error), the state is:

- `submit` wrote a valid `state: proposed` staged file to `staging/`
- `promote` did not write to `pages/`
- The proposed staged file is still present and promotable

This is an **intentional recoverable state**, not a bug. The slash command reports it clearly:

```
✓ Proposal staged: staging/2026-04-12-141523-story-pipeline.md
✗ Promote failed: <error message>

The proposal is preserved. You can retry with:
  /wiki-promote <staging-path>

Or review with /wiki-review.
```

**Test expectations:**
- `test_auto_chain_failure.py` — verify that a simulated promote failure leaves a valid staged file in `staging/` that can be independently promoted on retry
- The staged file must round-trip through parse → serialize → parse without changes, so retries are deterministic

**What `/wiki-capture` never does:**
- It does not delete or corrupt a staged file on promote failure
- It does not retry `promote` silently — the user is informed and chooses
- It does not fall back to writing directly to `pages/` under any circumstance

**`/wiki-promote`** (deterministic):
1. `wiki promote <project> <staging-file>` for dry-run; show diff
2. On confirmation, re-run with `--apply`
3. Report the final page path

**`/wiki-review`** (deterministic):
1. List `<project>/staging/*.md` grouped by `state` — raw items first, then proposed
2. For each item, show origin, trigger/source, and (for proposed items) the `proposed_action` and `target_page_id`
3. User picks one:
   - For a `state: raw` item: offer `/wiki-capture --from-staged=<path>` to upgrade it to a proposal
   - For a `state: proposed` item: offer `/wiki-promote` to canonicalize it

**`/wiki-bootstrap`** (v0.2, treated as operator/admin command):
- Runs the question-led seeding loop project-wide
- Not part of daily workflow

### 9.4 Hooks (v0.2+)

Hooks are intentionally minimal and opt-in per project. v0.2 ships one hook class:

**`post-spec-sync.sh`** — fires on `PostToolUse` for Write/Edit when path matches `docs/superpowers/specs/**/*.md`. The hook:
1. Reads `wiki.config.toml` to confirm the project is tracked
2. Runs `wiki sync <project> --event=post-spec --artifact=<path>`
3. Exits silently; the staged candidate appears in `/wiki-review` next time

**Hook rules:**
- Hook only files already intended to be durable decision/architecture artifacts
- Never broadly hook `docs/**/*.md`, notes, brainstorm files, scratch plans, or meeting transcripts
- Additional hook classes (v0.3+): `post-adr`, `post-runbook` — configured via path-class in `wiki.config.toml`

### 9.5 Per-project installation

Three steps, documented in `install/install.md`:

1. **Add a snippet to the project's `CLAUDE.md`:**
   ```markdown
   ## Wiki

   Project knowledge lives at `~/Git/wiki/<project>/`.
   Use `/wiki-query` to search; `/wiki-capture` to distill session learnings.
   Start-of-session map: `~/Git/wiki/<project>/views/index.md` (read when relevant).
   ```

2. **Pre-grant wiki access** in `.claude/settings.local.json`:
   ```json
   {
     "permissions": {
       "allow": [
         "Bash(wiki *)",
         "Read(~/Git/wiki/<project>/**)",
         "Read(~/Git/wiki/cross-project/**)"
       ]
     }
   }
   ```

3. **(v0.2+) Optionally add hooks** in the same settings file.

No daemon, no background process, no MCP server. The plugin supplies the skill and slash commands; the core CLI is invoked on demand.

## 10. Command contracts

Every core command honors this contract. Adapters can rely on it.

| Command | stdout | stderr | exit codes |
|---|---|---|---|
| `wiki query` | JSON array of results | diagnostics | 0 ok, 2 no results, 4 index unavailable (missing/stale), 1 error |
| `wiki capture prepare` | JSON prompt package | diagnostics | 0 ok, 1 error |
| `wiki capture submit` | JSON `{action, staging_path, proposed_page_id}` | diagnostics | 0 staged, 3 noop (nothing staged), 2 schema-invalid proposal, 1 error |
| `wiki bootstrap prepare` | JSON prompt package (per question) | diagnostics | 0 ok, 2 invalid question / pending duplicate, 3 --all queue empty, 1 error |
| `wiki bootstrap submit` | JSON `{action, staging_path, proposed_page_id}` or `{action: noop}` | diagnostics | 0 staged, 3 noop, 2 invalid, 1 error |
| `wiki sync` | JSON `{created, removed, skipped, warnings}` | diagnostics | 0 ok, 1 error |
| `wiki promote` | JSON `{action, page_id, path}` | diff (human-readable) | 0 applied, 3 dry-run, 2 staged file is not `state: proposed`, 1 error |
| `wiki index` | JSON `{pages_indexed, warnings_count}` | warnings list | 0 ok, 2 schema warnings (strict), 1 error |
| `wiki review` | JSON list of `ReviewItem` | diagnostics | 0 non-empty queue, 3 empty queue, 1 error |
| `wiki init` | JSON `{rendered, symlinks, seeded_config, permissions_snippet}` | diagnostics + instructions | 0 ok, 1 error |

**Invariants:**
- All commands accept `--json` (default for machine callers)
- Human-readable output goes to stderr for commands that also emit JSON on stdout
- Commands are pipeable: `wiki capture prepare | <agent-produces-proposal> | wiki capture submit`
- **Exit code `0`** always means "state changed on disk as expected" or "query succeeded."
- **Exit code `1`** is reserved for generic/config errors (missing config, project not found, I/O failure not captured by a more specific code).
- **Exit code `2`** is for domain-level rejection: the input was malformed or the state machine refused the operation (e.g. `promote` on a `state: raw` file, `capture submit` on a schema-invalid proposal, `query` returned zero results for a legitimate question).
- **Exit code `3`** means either explicit dry-run or a generative op decided nothing should be written (`noop`, empty review queue, bootstrap `--all` queue drained).
- **Exit code `4`** means infrastructure unavailable for a read-side op — specifically `wiki query` when the index is missing or at a stale schema version. This is distinct from exit `2` so machine callers can distinguish "wiki has nothing on this topic" (exit 2, user should fall back to docs) from "wiki isn't in a queryable state" (exit 4, user should run `wiki index`).

## 11. Scope phasing

### v0.1 — Minimal viable loop

**Ships:**
- Core deterministic ops: `query`, `index`, `promote`, schema/storage
- Core generative op: `capture` (prepare/submit, agent mode only)
- Claude adapter: `wiki` skill, `/wiki-query`, `/wiki-capture`, `/wiki-review`, `/wiki-promote`
- Config: `wiki.config.toml` with agent mode; direct mode stubbed but not implemented
- Data: `~/Git/wiki/` as a real git repo, **one project tracked: Project Alpha**
- Seed content: hand-written canonical pages **and** hand-written staging items, so `/wiki-review` and `/wiki-promote` can be exercised realistically before hooks exist

**Explicitly out of v0.1:**
- `wiki bootstrap` (v0.2)
- `wiki sync` hook-driven triggers (v0.2) — **manual `wiki sync` landed early in v0.1.1**, see below
- `cross-project/` subtree beyond an empty scaffold
- Direct LLM mode (v0.3)
- Codex adapter (v0.3+)

**v0.1.1 addendum — manual `wiki sync`:**

The core of Section 6.5's `wiki sync` shipped in v0.1.1 as a manually-invoked command (no hooks, no event argument). It walks `[[projects]] source_globs`, creates `state: raw` staged files per matched artifact (inline under `inline_threshold_bytes`, pointer otherwise), dedupes by `source_artifact` path, and supports `--path <subtree>` scoping plus `--force` to re-stage. This is the operational bridge between existing repo docs and the capture loop; full hook-driven automation remains v0.2. The `/wiki-capture --from-staged=<path>` branch on the Claude adapter handles the downstream upgrade-to-proposed step.

**v0.2.0 addendum — single-question `wiki bootstrap`:**

`wiki bootstrap` landed as a single-question-mode slice in v0.2.0. It is the question-led complement to `wiki sync` (which is doc-led). Commands:

- `wiki bootstrap prepare <project> --question "<text>" [--ad-hoc] [--paths <subtree>] [--limit-docs=5] [--replace-pending]` — resolves the question against `queries/seed-questions.md` (exact or unambiguous substring match; typos require explicit `--ad-hoc`), pulls top existing pages via `run_query`, scores source docs by token overlap, and emits a `PromptPackage` on stdout with the same shape as `capture prepare`.
- `wiki bootstrap submit <project> --proposal=<path-or-->` — validates a proposal that MUST include a top-level `bootstrap_question` block echoing the question provenance, and writes a `state: proposed + origin: bootstrap` staged file via the shared `staging_write.write_proposed_staged_file` helper (extracted from `capture submit` in the same release).

**New schema field:** `StagedFile.bootstrap_from: BootstrapFrom | None`. `BootstrapFrom` carries `question_text`, `question_source` (seed | ad-hoc), `question_key` (normalized slug used for dedupe), and optional `question_line` (1-based line in `seed-questions.md` for seed sources). Validator rule: `bootstrap_from` is forbidden on `raw` files and on `proposed + origin != bootstrap`; permitted (and populated by the writer) on `proposed + origin == bootstrap`. Soft-required via writer convention so any pre-v0.2.0 hand-written bootstrap files without the provenance field still parse.

**New shared helper:** `src/wiki_system/staging_write.py` extracts the proposal-validation + staged-file-write path so both `capture submit` and `bootstrap submit` delegate to the same helper. Command-specific rejection types (`SubmitRejection` vs `BootstrapRejection`) wrap the shared `StagingWriteError` to keep external contracts distinct.

**Dedupe:** path-based via `bootstrap_from.question_key`. If a pending bootstrap proposal exists for the same question, prepare and submit both refuse unless `--replace-pending`, which deletes the existing pending file on submit.

**Pluggable skill:** the bootstrap adapter ships as a SEPARATE skill file at `~/.agents/skills/wiki-bootstrap/SKILL.md` (symlinked into `~/.claude/skills/wiki-bootstrap`) rather than inlining bootstrap guidance into the main `wiki` skill. The main `wiki` skill keeps a one-line reference pointing to the sub-skill. Adding future sub-skills (e.g. wiki-review-ui) requires zero `init.py` changes — the renderer and symlink installer auto-discover every `templates/skills/<name>/` directory.

**Explicit v0.2.0 scope:**

- In: single-question prepare/submit, `--ad-hoc` fallback, `--paths` narrowing, `--replace-pending`, `--limit-docs`
- Out (deferred to v0.2.1): `--all` loop mode, `--max-proposals` cross-question cap, multi-question slash command branch
- Out (explicitly rejected for v0.2): embeddings-based source scoring, automatic page merging, cross-project bootstrap

**v0.2.1 addendum — `wiki bootstrap --all` loop mode:**

`wiki bootstrap prepare --all` landed in v0.2.1. The CLI is stateless: each `prepare --all` invocation picks the first seed question in `queries/seed-questions.md` that has no pending bootstrap proposal, builds one PromptPackage for it, and returns. The agent processes that one question (prepare → submit → promote), then re-invokes `prepare --all` for the next. Exit code 3 (noop/nothing-to-do) when every seed question already has a pending proposal.

The `--max-proposals` flag is passed through as a hint in the prompt package's `All-mode status` context section. The CLI does not track state or enforce the cap — the slash command template coaches the agent to count successful submits and stop at N. This keeps the CLI stateless and avoids session files.

Mutual exclusion: `--all` and `--question` cannot both be set. Exactly one is required.

Dedupe for `--all` originally looked only at pending proposed files (via `bootstrap_from.question_key`). Questions that were promoted to `pages/` and archived are NOT considered processed — if the user wants `--all` to skip already-promoted topics, they delete the corresponding line from `seed-questions.md` or run `--replace-pending` on a specific `--question` to regenerate. Manifest-aware "already promoted" tracking remains a v0.2.3 consideration.

**Exit codes for `wiki bootstrap prepare`** (now):
- 0: prompt package emitted on stdout
- 2: invalid question (unresolved without `--ad-hoc`, ambiguous substring, pending duplicate without `--replace-pending`, prior noop without `--replace-pending`, or `--all`+`--question` both passed)
- 3: `--all` queue drained (no more unprocessed seed questions)
- 1: other CLI/config error

**v0.2.2 addendum — durable noop decisions, prompt-package summary, and `bootstrap resolve`:**

v0.2.2 fixes four related bootstrap issues that surfaced from real use.

**Issue 1 — `--all` + noop was an infinite loop.** The v0.2.1 picker (`_pick_next_all_mode_question`) considered a seed question "processed" only when a pending proposed staged file existed with matching `bootstrap_from.question_key`. But `submit` with `action: noop` wrote nothing — it short-circuited before `write_proposed_staged_file`. On a well-seeded wiki where most questions resolve to noop, `prepare --all` got stuck re-emitting the same question forever: noop → no staged file → picker re-emits → noop → …

**Fix:** every noop decision now persists as a marker file at `<wiki_root>/<project>/staging/.bootstrap-noops/<question_key>.json`. The marker mirrors the `bootstrap_from` provenance plus an ISO-8601 timestamp and optional `reason` (the proposal's `rationale` field for submit-originated noops, the `--reason` flag for resolve-originated noops). `_pick_next_all_mode_question` now treats a question as "processed" if EITHER a pending proposal OR a noop marker exists. `--replace-pending` on prepare/submit clears both kinds of prior decisions.

The marker directory lives inside `staging/` so it travels with the project. The dot-prefix keeps markers out of `list_staged` (which globs `*.md` at the top level only) and out of the `wiki review` queue — markers are skip signals, not reviewable artifacts. Delete the marker file to retry bootstrapping a noop'd question.

**Issue 2 — prompt package was 85+ KB of JSON-escaped context on a single JSON-string line.** `wiki bootstrap prepare` output was hard to skim: the `context` field held one giant multi-line string, and agents had no way to decide "do I need the full evidence?" without parsing the whole package first.

**Fix:** `PromptPackage` grew a `summary: dict[str, Any] | None` field, emitted FIRST in `to_json()`. Bootstrap prepare populates it with:

```
{
  "question_key":            "...",
  "question_text":           "...",
  "question_source":         "seed" | "ad-hoc",
  "canonical_page_ids":      [top-ranked existing pages],
  "source_doc_paths":        [top-ranked repo source docs],
  "existing_pending_path":   null | "<path>",
  "remaining_questions":     null | int,
  "max_proposals_hint":      null | int
}
```

Agents read `summary` first to decide whether noop is obvious (e.g. `canonical_page_ids` contains an obvious match; `source_doc_paths` is empty so evidence is weak), and only drill into `context` when real synthesis is required. The field is optional and free-form so capture-side packages can populate it independently as needed.

**Issue 3 — the `--all` loop doc tension.** v0.2.1 said "bias hard toward noop" but `--all` structurally penalized noops: a noop didn't advance the loop. Guidance and behavior contradicted. The v0.2.2 marker fix aligns them — noop is a first-class decision that progresses the loop, not a stall. Bootstrap skill and slash command templates updated to reflect this.

**Issue 4 — seed questions never got removed from `seed-questions.md` and noop decisions didn't persist.** Even after a full session where the agent decided noop on Q1/Q2/Q3, re-running `bootstrap --all` tomorrow would redo the same analysis. Beyond the `--all` loop bug, the user wanted a way to durably record "this question doesn't need bootstrapping" without going through the full prepare → synthesize → submit cycle.

**Fix:** new command `wiki bootstrap resolve <project> --question "..." --as noop [--reason "..."] [--ad-hoc] [--replace-existing]`. Writes the same noop marker shape as submit-originated noops, except `resolved_by` records `wiki bootstrap resolve` vs `wiki bootstrap`. Rejects if a pending bootstrap proposal exists for the question (the user should review/promote/delete it first rather than resolving in parallel). `--as` currently accepts only `noop`; additional resolution types may be added in later releases.

**Non-goals for v0.2.2:**

- **No `--unresolve` flag.** To retry a noop'd question, delete the marker file manually or pass `--replace-pending` to prepare/submit — both work. A dedicated "un-noop" flag is adds more surface area than it earns.
- **No GC / housekeeping for stale markers.** Markers live forever by default. They're small (a few hundred bytes each) and serve as an audit trail.
- **No manifest-aware "already promoted" dedupe.** Still deferred (v0.2.3 shipped `wiki doctor` instead; see below). A question whose page was promoted and whose staged file was archived still re-emits from `--all` unless the user (a) deletes the seed line, (b) runs `bootstrap resolve --as noop`, or (c) lets prepare emit it and submits noop (which then persists).

**v0.2.3 addendum — `wiki doctor` (stale-reference detection against an external code graph):**

`wiki doctor <project> --graph <graph.json>` landed in v0.2.3. It is a read-only health check: it never writes to `pages/`, `views/`, or any other wiki file. It cross-checks code identifiers named in canonical page bodies (loaded via `load_index`, so `wiki index` must have run first) against an external AST-derived code graph and reports which ones no longer exist there.

**The graph is an external input, not a coupled dependency.** `--graph` accepts any JSON file matching a minimal node shape — `wiki-system` has no import-time or runtime coupling to `graphify` (or any other extraction tool) that produces one. `load_graph_symbols` reads only the top-level `"nodes"` array; it tolerates either graph shape graphify emits — clustered output (a `"links"` key) or raw extraction output (an `"edges"` key) — because it never looks at `links`/`edges` at all. Per node it reads `source_file` (populates the file set) and `label`/`norm_label` (populates the symbol set, `norm_label` preferred when present, lowercased and with a trailing `()` stripped for comparison).

**Identifier grammar.** `extract_identifiers` scans page bodies for backtick-delimited spans only — prose mentions outside backticks are ignored, and fenced code blocks are stripped before scanning so multi-line code samples never get treated as identifiers. Three shapes are recognized:
- **Python paths** — `[\w./-]+\.py` (e.g. `` `app/chat/service.py` ``)
- **Function calls** — `` `function()` `` or `` `.method()` ``, leading dot stripped for comparison
- **Class-like names** — `^[A-Z][A-Za-z0-9]+$`, minus a small stoplist (`True`, `False`, `None`). This is deliberately broad rather than a strict two-hump CamelCase pattern — a stricter regex missed 529/1825 class-like labels in a real graphify graph (e.g. `LLMProvider`, `AIService`, `Chat`) — at the cost of some capitalized-prose false positives, which the confidence split below absorbs.

**High vs advisory confidence.** `_path_in_graph` does suffix-tolerant matching (checking `endswith("/" + span)` in either direction) so a genuine miss survives prefix differences between the page's path and the graph's. But a path miss is only reported at `"high"` confidence when the path falls under one of the graph's covered roots — the top-level segment of any file in the graph's file set (e.g. `{"app"}` for a graph built from an `app/`-only extraction), matched against any path segment of the span (not just the leading one, so `api/backend/app/core/db.py` still counts as covered via its `app` segment). A path outside every covered root — an ungraphed tree such as `tests/`, `scripts/`, or `migrations/`, or a bare filename with no directory segment to match — is reported at `"advisory"` confidence instead: the graph simply never had a chance to observe it, so its absence is not evidence of staleness. Function/class misses are always `"advisory"`: a bare symbol name absent from the graph may simply live outside the graphed subtree (a different repo, a vendored dependency, a subtree graphify wasn't pointed at) rather than being genuinely stale. Callers should treat `high` findings as near-certain and `advisory` findings as prompts for a human to check, not as facts.

**Exit codes:** `0` clean (no findings), `2` findings present, `4` index or graph unavailable (missing/unreadable `.wiki-index.json` — i.e. `wiki index` hasn't run — or a missing/invalid graph JSON file).

**Non-goals for v0.2.3:**
- **No auto-fixing.** `doctor` only reports; it never edits, deletes, or rewrites pages. Reconciling a finding — editing the page, or accepting it as a known gap — is a human/agent decision made from the report, not a doctor side effect.
- **No `code_refs:` frontmatter yet.** Explicit page-to-symbol anchoring (a frontmatter field pages could declare instead of relying on backtick-span inference) is deferred to v0.3, and only if real `doctor` findings show that inference-based extraction isn't precise enough to justify the extra authoring burden.

**Why start with hand-written pages instead of `bootstrap`:**
- Forces a firsthand feel for the schema
- Surfaces frontmatter friction before an LLM amplifies it
- Guarantees `bootstrap` in v0.2 imitates a proven pattern rather than inventing one

**Why Project Alpha first (not Project Beta):**
- Richer existing docs and clearer domain boundaries
- Less risk of policy/process noise overwhelming the schema
- More forgiving if the first schema is slightly imperfect
- Project Beta is the better stress test for v0.2 once the core has earned trust

**Seed page composition (v0.1 must include at least one of each):**
- One `type: system` page
- One `type: workflow` page
- One `type: pattern` or `type: decision` page

This mix pressure-tests the schema across structurally different page shapes.

### v0.1 success criteria

All four must hold before the v0.1 milestone is closed:

1. **Query loop works end-to-end.** `/wiki-query "how does the story pipeline work"` in a Project Alpha session returns relevant pages with match reasons, and Claude reads the top result via `Read`.
2. **Capture loop works end-to-end.** `/wiki-capture` after making a session decision produces one proposal (noop/update/create). On approval, the page is written and `wiki index` regenerates views.
3. **Review and promote loop works end-to-end.** `/wiki-review` shows the staging queue; `/wiki-promote` moves a staged file into `pages/` with the diff shown before apply.
4. **Core CLI works standalone.** `wiki query <project> "..."` returns JSON on stdout with no adapter involved. This proves the agent-agnostic contract.

### v0.1 retrieval quality bar

Before declaring v0.1 complete, define and run a 10-question benchmark for Project Alpha:

- Pick 10 known questions with a known "right" canonical page
- Run `wiki query` for each
- **Bar: top 3 results contain the right page for at least 8 of 10 queries**

If the bar is missed, the fix is schema/ranking adjustment, not adding semantic retrieval.

### v0.2 — Automation and scale

- `wiki bootstrap` (agent mode) with phased passes
- `wiki sync` and the first hook class (`post-spec`)
- Track Project Beta as the second project
- Populate `cross-project/` with the first 1-2 synthesis pages
- Migrate some hand-written seed pages to `bootstrap`-generated versions to confirm comparable quality

### v0.3 — Expand and share

- Direct LLM mode for batch/standalone use
- Additional hook classes (`post-adr`, `post-runbook`) via path-class config
- Track project-gamma as the third project
- Public README, install docs, license choice (MIT or Apache-2)
- Stretch: Codex adapter — validates the agent-agnostic abstraction

## 12. Git handling for `~/Git/wiki/`

- `~/Git/wiki/` is a real git repo, committed by the operator
- The core CLI does **not** auto-commit. It only writes files. Commits are a user decision.
- `.gitignore` excludes `.wiki-index.json` and other generated state that doesn't need versioning
- `views/*.md` are committed — they are part of the observable knowledge workflow, not disposable build artifacts
- `staging/*.md` are committed — staged candidates should survive across machines if the wiki repo is synced
- Recommended workflow: commit `pages/` changes after `/wiki-promote`; commit `staging/` periodically
- No plugin-provided commit hooks

## 13. Testing strategy

- **`tests/test_query_ranking.py`** — golden tests on fixture wikis. Known questions → expected top result with expected `matched_fields` and `match_source`.
- **`tests/test_schema.py`** — valid and invalid frontmatter cases for both the page schema and the staged-file schema. Type enforcement, required fields, `superseded_by` only valid when `status: superseded`, `target_page_id` required when `proposed_action: update`.
- **`tests/test_staged_envelope.py`** — round-trip tests for the staged-file envelope. Serialize a proposed staged file, parse it, serialize again, assert byte-identical output. Golden fixtures for raw (inline), raw (pointer), proposed (create), proposed (update), and proposed-with-`upgraded_from`.
- **`tests/test_page_identity_invariant.py`** — covers the `proposed_action: update` invariant. Cases: `target_page_id` null on update (reject), `canonical_page.frontmatter.id` mismatching `target_page_id` (reject), target page not present at promote time (reject), `target_page_id` non-null on create (reject), `canonical_page.frontmatter.id` colliding with existing page on create (reject). Both `submit` and `promote` must reject each case with exit code 2.
- **`tests/test_capture_submit.py`** — pre-generated proposals fed to `capture submit`. Verifies noop/update/create routing, one-change-max rule, schema validation exit codes, `--from-staged` upgrade path.
- **`tests/test_capture_dereference.py`** — `capture prepare --from-staged` correctly inlines artifact content for `raw_body_mode: inline` and re-reads `source_artifact` for `raw_body_mode: pointer`. Warns when `source_commit` has drifted from HEAD.
- **`tests/test_promote.py`** — proposed staged files → dry-run diff output → `--apply` write path → index regeneration. Raw staged files are rejected with exit code 2.
- **`tests/test_auto_chain_failure.py`** — simulated `promote` failure after a successful `submit` leaves a valid staged file in `staging/`. Retry with `wiki promote` on the preserved file succeeds.
- **`tests/test_index.py`** — backlinks, inferred edges, view regeneration idempotency, single-writer invariant.
- **Adapter tests** — golden fixtures for `wiki capture prepare` output + hand-written proposals piped to `submit`.

No tests call the Anthropic API. Generative ops are tested by fixture proposals, not live model calls. This keeps the suite fast and deterministic, and it is what makes the prepare/submit protocol genuinely reliable.

## 14. Open questions and deferred decisions

1. **License selection** — MIT vs Apache-2 decided at v0.3 public release, not before.
2. **Direct mode design details** — deferred to v0.3. The config shape is sketched but the prompt adapter for direct mode is not designed.
3. **Codex adapter specifics** — deferred until Claude adapter is stable in v0.2.
4. **`cross-project/` synthesis authoring workflow** — deferred until v0.2. The subtree exists in v0.1 as an empty scaffold only.
5. **`/wiki-review` UI richness** — v0.1 ships a minimal list; improvements deferred based on real use.
6. **Seed question authoring process for new projects** — v0.2 should document a lightweight "how to write good seed questions" guide based on lessons from Project Alpha's v0.1 run.

## 15. Risks

- **Schema churn** — the v0.1 frontmatter may prove wrong in practice. Mitigation: hand-write pages first, adjust schema before `bootstrap` arrives in v0.2.
- **Under-capture feels empty** — the under-capture bias may leave the wiki feeling sparse early on. Mitigation: hand-written seed pages establish usefulness from day one; capture grows organically.
- **Adapter drift** — the temptation to put "just a little logic" in the slash commands is real. Mitigation: the prepare/submit protocol makes drift architecturally visible, and the command contracts table is the enforcement surface.
- **Retrieval quality** — deterministic lexical + graph ranking may not hit the 8/10 bar. Mitigation: if it misses, tune ranking weights and curated edges before reaching for embeddings. Embeddings are a v0.3+ conversation only if real use demands it.

**v0.3.0 addendum — per-project canonical domain allowlist:**

`domains = [...]` on a `[[projects]]` entry in `wiki.config.toml` declares the
project's canonical domain taxonomy. Enforcement happens at index time only:
`wiki index` compares every page's `domains:` frontmatter against the
allowlist, includes any violations in the payload (`warnings`,
`warnings_count`), and `--strict` exits 1 on the first non-empty warning set.
Capture/promote are deliberately NOT gated — staged pages may carry candidate
domains; the strict index run (CI or pre-promote hook) is the contract seam.
An absent or empty list disables the check entirely, preserving pre-0.3.0
free-form tagging. Domains remain a retrieval field (weight 3.0); the
allowlist changes vocabulary discipline, not scoring.
