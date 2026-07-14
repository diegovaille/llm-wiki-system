# Changelog

All notable changes to `wiki-system` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
