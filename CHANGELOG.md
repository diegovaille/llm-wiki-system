# Changelog

All notable changes to `wiki-system` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.5.4] - 2026-09-03

### Changed
- Graph expansion returns to the 0.5.1 rule: a neighbor scores
  `min(source * factor + edge_weight, source)` from the first edge that
  reaches it - curated before inferred, index order within, exactly as
  0.5.1. Taking the strongest source instead (0.5.2-0.5.3 did) measured one
  newcomer hit fewer and 56 graph rows in the title top fives against 30:
  the stronger sources are the alias-heavy attractors. The sibling caps of
  0.5.2 and 0.5.3 are withdrawn. A
  round-four review measured 0.5.3's "lowest two-term sibling" cap binding
  on 145 of 153 queries, usually on two stray body tokens, which switched
  graph expansion off (top-five graph rows over 117 title queries: 30 on
  0.5.1, 6 on 0.5.3) while the top-3 benchmark never moved. A related page
  of a strong hit therefore can outrank a weaker direct match, including a
  sibling that matched a few terms; that is the designed reach of the edge
  weights, now stated in DESIGN.md rather than fought.

## [0.5.3] - 2026-09-03

### Fixed
- Graph expansion, third and final cut of the sibling rule. 0.5.2 capped a
  zero-term neighbor at the *best* matched sibling of its source, which an
  alias-heavy sibling raised past the page that should have won, and a
  neighbor reached from a second source escaped the cap through the
  cross-source max. The cap is now the *lowest* score among the source's
  neighbors that matched at least two query terms, computed per source, and
  a neighbor keeps the best of its per-source capped scores. A sibling that
  matched a single stray body token neither caps nor competes. Top-3 hit
  rates unchanged; newcomer top-5 11 → 12 of 15; the gold page a round-three
  review found demoted from rank 5 to 7 sits at rank 4.
- `--config ~/path` is expanded; the wiki skills pass `"$WIKI_CONFIG"`
  verbatim and a literal `~` failed with `config not found`.
- Graph rows reached from several sources take the best score since 0.5.2;
  0.5.1 kept the first edge's. Now documented.

## [0.5.2] - 2026-09-03

### Fixed
- A graph neighbor that matched nothing could outrank a sibling neighbor of
  the same source that matched several query terms, because the sibling
  kept its own (smaller) direct score while the zero-term neighbor took
  `min(source * factor + weight, source)`. A zero-term neighbor is now also
  capped at the best direct score among that source's matched neighbors.
  Lifting the matched sibling instead was measured at -3 newcomer hits and
  rejected: it amplifies the top hit's neighborhood over the right answer at
  rank two or three. Hit rates unchanged; 27 graph rows across the 36
  benchmark questions.

## [0.5.1] - 2026-09-03

### Changed
- A page reached only through the link graph is scored at most as high as
  the direct match that led to it (`min(base * factor + edge_weight, base)`).
  0.4.0 had ranked every graph row after every direct match instead, which
  with body scoring meant a `related:` page almost never appeared in the top
  five (0 of 117 title queries on a 117-page corpus; 25 graph rows across 36
  benchmark questions after this change, hit rates unchanged). The edge
  weights in `[retrieval]` therefore lift a neighbor above weaker direct
  hits again, never above its source.

### Fixed
- `docs/DESIGN.md` listed `id` among the scored fields; it never was.
- `uv.lock` had not been refreshed at v0.4.0 and v0.5.0.

## [0.5.0] - 2026-09-03

### Added
- Config discovery without `--config`: `WIKI_CONFIG` names the file, else
  `WIKI_ROOT/wiki.config.toml`, else `~/Git/wiki/wiki.config.toml`. The
  plugin skills and the prompt hook read the same two variables.
- A relative `[wiki] root` (`"."` is the useful value) resolves against the
  directory holding the config file, so a tracked config works from any
  clone location. Before, `root = "~/Git/wiki"` was literal and `--config`
  on a clone elsewhere silently wrote the index into `~/Git/wiki`.

## [0.4.0] - 2026-09-03

### Changed
- `wiki query` scoring is now inverse-document-frequency weighted and strips
  stopwords from the question. Measured on a 115-page corpus: newcomer-phrased
  questions went from 1 of 15 to 10-11 of 15 in the top three, expert-phrased
  questions from 6 of 7 to 7 of 7, and the four alias-heavy pages that used to
  win every sentence-shaped question on "a", "how", "so", "they" fell from
  half of all top-three slots to a sixth. Field weights and the tokenizer are
  unchanged.
- `sources:` is now a scored field (default weight 1.0, configurable through
  `field_weights.sources`). A ticket id that appears only in `sources:` is
  retrievable for the first time.
- Pages with `status: superseded` are excluded from scoring and from graph
  expansion.

## [0.3.0] - 2026-07-14

### Added
- Per-project canonical domain allowlist: optional `domains = [...]` on a
  `[[projects]]` entry in `wiki.config.toml`. When set, `wiki index` reports
  a warning for every page tagged with a domain outside the list (payload
  gains `warnings`), and `wiki index --strict` exits 1. Empty/absent list
  preserves legacy free-form behavior.

## [0.2.3] - 2026-07-08

### Added
- `wiki doctor <project> --graph <graph.json>`: report code identifiers in
  canonical pages that no longer exist in an external AST code graph
  (e.g. graphify). Exit 0 clean / 2 findings / 4 input unavailable.
- `docs/SEED-HARVEST.md`: manual procedure for harvesting graph-report
  highlights into seed questions.

## [0.2.2] - 2026-04-12

### Added
- **`wiki init --dry-run`** — preview the full install plan (rendered files, symlinks, config to seed, permissions snippet) without touching disk. No `git init`, no directory creation, no file writes, no symlinks. Safe to run on any machine to inspect what a real `wiki init` would change.
- **`wiki bootstrap resolve`** — new subcommand that durably records a noop decision for a seed question without running the full prepare/synthesize/submit cycle. Useful when the user already knows a seed question is out of scope, covered elsewhere, or trivially answered. `--as noop` is the only supported resolution in v0.2.2. Optional `--reason` recorded in the marker for audit.
- **Durable noop markers.** `wiki bootstrap submit` with `action: noop` now persists the decision as `<wiki_root>/<project>/staging/.bootstrap-noops/<question_key>.json`. `_pick_next_all_mode_question` treats marker-bearing questions as "already processed," so `--all` mode advances past them instead of re-emitting them forever.
- **`PromptPackage.summary`** — new optional top-level field on the prompt package JSON, emitted first in `to_json()`. Bootstrap prepare populates it with `question_key`, `question_text`, `question_source`, `canonical_page_ids`, `source_doc_paths`, `existing_pending_path`, `remaining_questions`, `max_proposals_hint`. Agents skim `summary` first to decide noop upfront without parsing the (potentially 85+ KB) context string.
- **Tests.** 14 new bootstrap tests (54 total in `test_bootstrap.py`) plus one updated, and 5 new `init --dry-run` tests. Total test suite: 224 portable tests (was 206).
- **Documentation.** `docs/DESIGN.md` v0.2.2 addendum, wiki-bootstrap skill + slash command templates updated, README core operations table expanded to 8 rows, `install.md` updated for the 6-slash-command layout.

### Fixed
- **`wiki bootstrap --all` + noop infinite loop.** Before v0.2.2, noop submits left no trace, so `_pick_next_all_mode_question` re-emitted the same question on every `prepare --all` call. On a well-seeded wiki where most questions resolve to noop, `--all` got stuck on question 1 forever. Marker-based persistence (see above) fixes this.
- **Bootstrap skill doc tension.** Prior guidance said "bias hard toward noop" while `--all` structurally penalized noops. The marker fix aligns behavior and guidance: noop is a first-class decision that advances the loop.

### Changed
- `--replace-pending` flag on `bootstrap prepare`/`submit` now clears prior noop markers in addition to prior pending proposals. Extends the flag's semantics symmetrically.
- Exhaustion message from `_pick_next_all_mode_question` now references "prior bootstrap decision (pending proposal or persisted noop marker)" instead of "pending proposal."

## [0.2.1] - 2026-04-12

### Added
- **`wiki bootstrap prepare --all`** — stateless loop mode that iterates `queries/seed-questions.md` and emits the next unprocessed question. `--max-proposals=N` passes a session cap hint to the agent.
- **Exit code 4** for `wiki query` when the index is unavailable (distinct from exit 2 "no results") so machine callers can differentiate "wiki has nothing on this topic" from "wiki isn't queryable."

### Fixed
- `wiki query` no longer crashes with a Python traceback on a missing or stale index — it emits an actionable stderr message and exits 4.
- `wiki sync` dedupes against both raw staged files AND proposed files upgraded from them, preventing `sync → capture → sync` from producing duplicates.
- `wiki init` now runs `git init --quiet` in the wiki data root on first setup so the README's "creates the wiki data repo" promise holds.
- Several documentation lag fixes caught by external review.

## [0.2.0] - 2026-04-12

### Added
- **`wiki bootstrap prepare|submit`** — seed-question-driven page synthesis (single-question mode). Complements `wiki sync` (doc-led) by starting from questions in `queries/seed-questions.md`.
- **`wiki-bootstrap` sub-skill** — pluggable sub-skill installed as a separate file under `~/.agents/skills/wiki-bootstrap/`, auto-discovered by `wiki init` via the multi-skill symlink installer. Main `wiki` skill keeps a pointer to it.
- **`BootstrapFrom` schema** — tracks `question_text`, `question_source` (seed|ad-hoc), `question_key`, `question_line` on bootstrap-originated staged files.
- **Shared `staging_write.write_proposed_staged_file` helper** — extracted from `capture submit` so both capture and bootstrap submit delegate to the same validation + write path.

## [0.1.1] - 2026-04-12

### Added
- **`wiki sync`** — walk project `source_globs` and register each match as a `state: raw` staged file. Scoped by `--path <subtree>`, `--force` to re-stage. Inline body under `[sync] inline_threshold_bytes`, pointer mode otherwise.
- **Staged-upgrade capture branch** — `/wiki-capture --from-staged=<path>` upgrades a raw staged file into a `state: proposed` canonical page, preserving the `source_artifact` as a required source.

## [0.1.0] - 2026-04-12

Initial release. Seven commands: `query`, `index`, `capture prepare|submit`, `promote`, `review`, `init`. Claude Code adapter with four slash commands: `/wiki-query`, `/wiki-capture`, `/wiki-review`, `/wiki-promote`. Filesystem-native markdown pages with YAML frontmatter, pydantic v2 schema validation, deterministic lexical + link-graph retrieval, prepare/submit protocol for generative ops. 109 tests covering schema, staging envelope, page identity invariant, capture routing, promote pipeline, query ranking, auto-chain failure, index regeneration, yaml round-trip, and CLI exit code contract.
