"""`wiki bootstrap prepare` / `wiki bootstrap submit` — seed-question-driven
page synthesis.

Bootstrap is question-led, not doc-led. The `sync → capture --from-staged`
loop answers "I have this doc, compile it into a page." Bootstrap answers
"I have this question, find the best evidence in the repo and the wiki
and produce one canonical page that answers it."

v0.2.0 scope:
- Single-question mode only (`--question`). The `--all` loop over
  `seed-questions.md` is deferred to v0.2.1.
- Prepare emits a prompt package with project intent, the seed question,
  top existing pages (from run_query), and top source docs (from a simple
  body-token overlap scorer). The agent reads this, synthesizes one
  proposal, and calls `wiki bootstrap submit`.
- Submit validates the proposal (including a required `bootstrap_question`
  block echoing the question provenance) and writes a `state: proposed`
  staged file with `origin: bootstrap` via the shared staging_write helper.
- Dedupe by `bootstrap_question.question_key`: if a pending proposed file
  already exists for this question, prepare refuses unless
  `--replace-pending`.

Everything downstream of submit (review, promote, index) is unchanged —
bootstrap just produces the same envelope shape as capture, with different
origin and provenance metadata.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from wiki_system.capture import (
    ALLOWED_ACTIONS,
    PromptPackage,
    SYSTEM_PROMPT,
    _schema_description,
)
from wiki_system.config import ProjectConfig, RetrievalConfig
from wiki_system.query import _tokenize, run_query
from wiki_system.schema import (
    BootstrapFrom,
    StagedFileOrigin,
    StagedState,
)
from wiki_system.staging_write import (
    StagingWriteError,
    write_proposed_staged_file,
)
from wiki_system.storage import list_staged, read_staged


DEFAULT_LIMIT_DOCS = 5
DEFAULT_LIMIT_PAGES = 5


_SLUG_SAFE_RE = re.compile(r"[^a-z0-9]+")


class BootstrapRejection(Exception):
    """Raised when a bootstrap proposal cannot be prepared or submitted."""


@dataclass
class BootstrapQuestion:
    """Resolved seed question or ad-hoc question being bootstrapped."""

    text: str
    source: str  # "seed" | "ad-hoc"
    key: str  # slugified text, used for dedupe
    line: int | None = None  # 1-based line in seed-questions.md, None for ad-hoc

    def to_bootstrap_from(self) -> BootstrapFrom:
        return BootstrapFrom(
            question_text=self.text,
            question_source=self.source,
            question_key=self.key,
            question_line=self.line,
        )


@dataclass
class SourceDocCandidate:
    """A scored repo-relative source doc considered for inclusion in the prompt."""

    path: str  # repo-relative
    score: float
    body: str


@dataclass
class BootstrapPrepareResult:
    """Everything the CLI emits on `wiki bootstrap prepare`.

    In single-question mode (--question), exactly one result is
    produced, `remaining_questions` is None, and `max_proposals_hint`
    is None.

    In --all mode, the caller receives the prompt package for the next
    unprocessed seed question, `remaining_questions` is the count of
    seed questions left (including the current one, so callers know
    "this is question 3 of 5") and `max_proposals_hint` carries the
    --max-proposals value so the slash command template can bound its
    own loop.
    """

    question: BootstrapQuestion
    package: PromptPackage
    existing_page_ids: list[str] = field(default_factory=list)
    source_doc_paths: list[str] = field(default_factory=list)
    existing_pending_path: Path | None = None
    remaining_questions: int | None = None
    max_proposals_hint: int | None = None


class BootstrapAllExhausted(BootstrapRejection):
    """Raised by run_prepare_bootstrap(all_mode=True) when every seed
    question in `seed-questions.md` already has a pending proposed
    staged file — i.e. there's nothing left for --all to do.

    The CLI catches this and exits 3 (noop/nothing-to-do) rather than
    treating it as an error. Distinct from BootstrapRejection so the
    CLI can tell "no work to do" apart from "something was invalid."
    """


@dataclass
class BootstrapSubmitResult:
    """Everything `wiki bootstrap submit` returns on success."""

    action: str  # "noop" | "create" | "update"
    staging_path: str
    proposed_page_id: str | None
    question_key: str


# ---------- Seed question loading + resolution ----------


def _slugify_question(text: str) -> str:
    """Normalize question text to a deterministic slug for dedupe.

    Lowercase, strip punctuation, collapse whitespace to single hyphens.
    Used as `bootstrap_from.question_key`.
    """
    s = _SLUG_SAFE_RE.sub("-", text.lower()).strip("-")
    return s or "question"


def _load_seed_questions(wiki_root: Path, project: str) -> list[BootstrapQuestion]:
    """Parse `<project>/queries/seed-questions.md` into BootstrapQuestion list.

    Format: numbered list (one question per line starting with `N.`).
    Lines not matching the pattern are ignored. The file may be empty
    or missing; in both cases returns an empty list.
    """
    path = wiki_root / project / "queries" / "seed-questions.md"
    if not path.exists():
        return []
    questions: list[BootstrapQuestion] = []
    for lineno, line in enumerate(path.read_text().splitlines(), start=1):
        stripped = line.strip()
        # Accept "1. text", "1) text", "- text"
        m = re.match(r"^(?:\d+[.)]\s+|-\s+)(.+)$", stripped)
        if not m:
            continue
        text = m.group(1).strip()
        if not text:
            continue
        questions.append(
            BootstrapQuestion(
                text=text,
                source="seed",
                key=_slugify_question(text),
                line=lineno,
            )
        )
    return questions


def resolve_question(
    cli_arg: str,
    seed_questions: list[BootstrapQuestion],
    *,
    ad_hoc: bool = False,
) -> BootstrapQuestion:
    """Match `cli_arg` against seed questions, or return an ad-hoc question.

    Matching order:
    1. Exact text match → return the seed question
    2. Case-insensitive substring match against exactly ONE seed → return it
    3. Ambiguous substring match (multiple seeds) → reject with a clear error
    4. No substring match + `ad_hoc=False` → reject; tell user to pass --ad-hoc
    5. No substring match + `ad_hoc=True` → return an ad-hoc question with
       `source="ad-hoc"`, `line=None`, key slugified from `cli_arg`
    """
    needle_lower = cli_arg.lower().strip()
    if not needle_lower:
        raise BootstrapRejection("--question must not be empty")

    # Exact match first
    for q in seed_questions:
        if q.text == cli_arg:
            return q

    # Substring match (unambiguous only)
    substring_matches = [
        q for q in seed_questions if needle_lower in q.text.lower()
    ]
    if len(substring_matches) == 1:
        return substring_matches[0]
    if len(substring_matches) > 1:
        match_preview = "\n".join(f"  - [{q.line}] {q.text}" for q in substring_matches)
        raise BootstrapRejection(
            f"--question {cli_arg!r} matches multiple seed questions. "
            f"Narrow the substring or use the exact text:\n{match_preview}"
        )

    # No seed match — require --ad-hoc
    if not ad_hoc:
        raise BootstrapRejection(
            f"--question {cli_arg!r} does not match any seed question in "
            "queries/seed-questions.md. Either pick a substring that matches "
            "an existing seed, or pass --ad-hoc to run an ad-hoc bootstrap "
            "with this free-text question."
        )
    return BootstrapQuestion(
        text=cli_arg,
        source="ad-hoc",
        key=_slugify_question(cli_arg),
        line=None,
    )


# ---------- Source doc scoring ----------


def _score_source_doc(question_tokens: set[str], body: str) -> float:
    """Simple token-overlap score. Deterministic, no embeddings.

    Matches the wiki-system ethos of inspectable retrieval. The count
    of distinct question tokens that appear in the body. Ties are broken
    upstream by repo-relative path order.
    """
    body_tokens = set(_tokenize(body))
    return float(len(question_tokens & body_tokens))


def _collect_source_candidates(
    project_cfg: ProjectConfig,
    *,
    question_tokens: set[str],
    path_filter: str | None,
    limit: int,
) -> list[SourceDocCandidate]:
    """Walk project source_globs, score each match against the question.

    `path_filter` narrows the candidate pool to a repo-relative prefix
    (same semantics as `wiki sync --path`). Returns top `limit` candidates
    by score, sorted score-desc then path-asc for determinism. Binary
    files (UTF-8 decode errors) are silently skipped.
    """
    from wiki_system.sync import _matches_path_filter, _normalize_path_filter

    repo_path = Path(project_cfg.repo_path).expanduser().resolve()
    normalized = _normalize_path_filter(path_filter)
    seen: set[str] = set()
    scored: list[SourceDocCandidate] = []
    for glob in project_cfg.source_globs:
        for abs_path in repo_path.glob(glob):
            if not abs_path.is_file():
                continue
            rel = abs_path.relative_to(repo_path)
            rel_str = str(rel)
            if rel_str in seen:
                continue
            if not _matches_path_filter(rel_str, normalized):
                continue
            try:
                body = abs_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            seen.add(rel_str)
            score = _score_source_doc(question_tokens, body)
            if score <= 0:
                continue
            scored.append(SourceDocCandidate(path=rel_str, score=score, body=body))
    scored.sort(key=lambda c: (-c.score, c.path))
    return scored[:limit]


# ---------- Prepare ----------


def _load_project_intent(wiki_root: Path, project: str) -> str:
    """Read meta/project.md if present. Strip the YAML frontmatter block.

    Returns an empty string if the file doesn't exist. The body is
    included in the prompt context so the agent knows the project's
    wiki-scope rules (what belongs / doesn't belong).
    """
    path = wiki_root / project / "meta" / "project.md"
    if not path.exists():
        return ""
    text = path.read_text()
    # Strip leading YAML frontmatter (`---\n...\n---\n`)
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            text = text[end + len("\n---\n") :]
    return text.strip()


def _existing_pending_for_question(
    wiki_root: Path, project: str, question_key: str
) -> Path | None:
    """Find an existing proposed staged file bootstrapped from this question.

    Returns the path if a proposed file with matching `bootstrap_from.question_key`
    exists, else None. Used by prepare to refuse duplicates without --replace-pending.
    """
    for staged_path in list_staged(wiki_root, project):
        try:
            staged, _body = read_staged(staged_path)
        except Exception:
            continue
        if staged.state != StagedState.PROPOSED.value:
            continue
        if staged.origin != StagedFileOrigin.BOOTSTRAP.value:
            continue
        if staged.bootstrap_from is None:
            continue
        if staged.bootstrap_from.question_key == question_key:
            return staged_path
    return None


def _build_prepare_context(
    *,
    project: str,
    project_intent: str,
    question: BootstrapQuestion,
    existing_pages: list[tuple[str, str, str, str]],  # (id, title, summary, body)
    source_docs: list[SourceDocCandidate],
    all_mode: bool = False,
    remaining_count: int | None = None,
    max_proposals: int | None = None,
) -> str:
    """Assemble the prompt package's context string.

    The agent reads this verbatim. Order matters: project intent first
    (what belongs in the wiki), then the question, then existing pages
    (so the agent biases toward update), then raw source docs.

    In --all mode, an "All-mode status" section is prepended so the
    agent sees how many questions remain and what the session
    submission cap is.
    """
    parts: list[str] = []

    if all_mode:
        parts.append("## All-mode status")
        if remaining_count is not None:
            parts.append(
                f"- This is question 1 of {remaining_count} remaining "
                f"unprocessed seed questions."
            )
        if max_proposals is not None:
            parts.append(
                f"- Session cap (`--max-proposals`): {max_proposals}. "
                f"After {max_proposals} successful submits in this session, "
                f"stop calling `wiki bootstrap prepare --all` and wait for "
                f"the user to continue."
            )
        parts.append(
            "- Each `prepare --all` invocation returns exactly ONE question. "
            "Process this one fully (prepare → submit → promote) before "
            "re-invoking `prepare --all` for the next question."
        )
        parts.append("")

    if project_intent:
        parts.append("## Project intent")
        parts.append(project_intent)
        parts.append("")

    parts.append("## Seed question")
    parts.append(question.text)
    parts.append("")
    parts.append("## Question provenance")
    parts.append(
        f"- source: {question.source}"
        + (f" (line {question.line} of queries/seed-questions.md)" if question.line else "")
    )
    parts.append(f"- question_key: {question.key}")
    parts.append("")
    parts.append(
        "**You MUST echo this provenance in your proposal under a top-level "
        "`bootstrap_question` block** with these exact fields:"
    )
    parts.append("```json")
    parts.append(
        json.dumps(
            {
                "question_text": question.text,
                "question_source": question.source,
                "question_key": question.key,
                "question_line": question.line,
            },
            indent=2,
        )
    )
    parts.append("```")
    parts.append("")

    parts.append("## Existing canonical pages (most relevant first)")
    if existing_pages:
        for pid, title, summary, body in existing_pages:
            parts.append(f"### {pid} — {title}")
            if summary:
                parts.append(f"_{summary}_")
            parts.append("")
            parts.append(body)
            parts.append("")
    else:
        parts.append("(no existing pages match the question — consider `action: create`)")
        parts.append("")

    parts.append("## Source documentation candidates (ranked by token overlap)")
    if source_docs:
        for doc in source_docs:
            parts.append(f"### {doc.path} (score: {doc.score:.1f})")
            parts.append("```markdown")
            # Truncate very large bodies so the prompt stays bounded
            body_preview = doc.body if len(doc.body) < 8000 else doc.body[:8000] + "\n…(truncated)"
            parts.append(body_preview)
            parts.append("```")
            parts.append("")
    else:
        parts.append(
            "(no source docs matched the question's tokens — the answer "
            "must come from your own understanding plus the existing pages above)"
        )
        parts.append("")

    return "\n".join(parts)


def _build_prepare_instructions(
    question: BootstrapQuestion,
    *,
    all_mode: bool = False,
    remaining_count: int | None = None,
    max_proposals: int | None = None,
) -> str:
    """Bootstrap-specific agent instructions. Parallel to capture's.

    In --all mode the instructions add a tail paragraph about the loop
    protocol: the agent processes one question per invocation, resumes
    by re-calling `prepare --all` after each submit, and stops at the
    session cap.
    """
    base = (
        f"bootstrap mode. Answer the seed question above with AT MOST ONE "
        f"canonical wiki change: noop, update, or create.\n\n"
        f"- Bias hard toward `update` if an existing page above is a reasonable "
        f"home for this answer. Creating a new page when an existing one could "
        f"have been extended is the most common bootstrap mistake.\n"
        f"- Bias toward `noop` if the existing pages already answer the question "
        f"adequately, or if the source docs don't contain enough evidence to "
        f"produce a confident page.\n"
        f"- If you choose `update`, `target_page_id` MUST equal "
        f"`canonical_page.frontmatter.id` (page identity invariant).\n"
        f"- Your proposal MUST include a top-level `bootstrap_question` block "
        f"echoing the provenance from the context above, verbatim.\n"
        f"- `canonical_page.frontmatter.sources` SHOULD include each source doc "
        f"you actually used (e.g. `docs/technical/pipeline-architecture.md`). "
        f"Do not fabricate sources you didn't reference.\n"
        f"- Produce exactly ONE result. Do not batch multiple questions into "
        f"one proposal."
    )
    if not all_mode:
        return base
    tail_lines = [
        "",
        "",
        "**--all loop protocol:** This is a single question out of several.",
        "After you submit this proposal (or decide noop), re-invoke",
        "`wiki bootstrap prepare <project> --all` to get the next question's",
        "prompt package. Each call returns exactly ONE question. Do not batch.",
    ]
    if max_proposals is not None:
        tail_lines.append(
            f"Stop after {max_proposals} successful `submit` calls in this "
            f"session even if the --all queue is not yet empty."
        )
    if remaining_count is not None:
        tail_lines.append(
            f"Questions remaining including this one: {remaining_count}."
        )
    return base + "\n".join(tail_lines)


def _pick_next_all_mode_question(
    wiki_root: Path, project: str, seed_questions: list[BootstrapQuestion]
) -> tuple[BootstrapQuestion, int]:
    """Find the first seed question without a pending proposal.

    Iterates seed_questions in file order. Returns the first question
    whose question_key has NO pending proposed staged file, plus the
    count of remaining unprocessed questions *including the returned
    one* (so the caller can report "this is X of Y").

    Raises `BootstrapAllExhausted` when every seed question already has
    a pending proposal. The caller (CLI) catches this and exits 3.

    A seed question is "processed" for the purposes of this scan when
    a pending proposed staged file exists with matching `question_key`.
    Questions that were promoted to `pages/` and archived are NOT
    considered processed by this function — if the user wants --all to
    skip already-promoted topics, they should delete the seed question
    from `seed-questions.md` or pair --all with a follow-up pass that
    deletes stale seed entries. (v0.2.2 may add a manifest-based check.)
    """
    if not seed_questions:
        raise BootstrapAllExhausted(
            "queries/seed-questions.md has no seed questions; "
            "nothing for --all to process"
        )
    unprocessed: list[BootstrapQuestion] = []
    for q in seed_questions:
        pending = _existing_pending_for_question(wiki_root, project, q.key)
        if pending is None:
            unprocessed.append(q)
    if not unprocessed:
        raise BootstrapAllExhausted(
            "every seed question in queries/seed-questions.md already has "
            "a pending bootstrap proposal. Review or promote them first "
            "(wiki review <project>), or use --replace-pending on a "
            "specific --question to regenerate."
        )
    return unprocessed[0], len(unprocessed)


def run_prepare_bootstrap(
    *,
    wiki_root: Path,
    project_cfg: ProjectConfig,
    retrieval_cfg: RetrievalConfig,
    question_arg: str | None = None,
    all_mode: bool = False,
    ad_hoc: bool = False,
    limit_docs: int = DEFAULT_LIMIT_DOCS,
    path_filter: str | None = None,
    replace_pending: bool = False,
    max_proposals: int | None = None,
) -> BootstrapPrepareResult:
    """Build a PromptPackage for a seed question.

    Two modes:

    **Single-question mode** (`all_mode=False`, `question_arg` required):
    Resolve the given question against seed-questions.md (exact or
    unambiguous substring match; ad_hoc required for free text). If a
    pending proposal already exists and `replace_pending` is False,
    raise. Build the prompt package.

    **--all mode** (`all_mode=True`, `question_arg=None`): Walk the seed
    questions in file order, pick the first one without a pending
    proposal, and build a prompt package for it. `remaining_questions`
    on the result tells the caller "X questions left to process
    including this one". `max_proposals` is passed through as a hint
    the slash command template uses to bound its own loop.

    Does not write anything. The caller emits the package to the
    agent, which synthesizes a proposal and calls
    `run_submit_bootstrap` next.

    Raises `BootstrapRejection` for invalid input (missing --question
    in single mode, unresolvable question without --ad-hoc, pending
    duplicate without --replace-pending).

    Raises `BootstrapAllExhausted` (a BootstrapRejection subclass) when
    all_mode=True and every seed question is already processed.
    """
    seed_questions = _load_seed_questions(wiki_root, project_cfg.name)

    remaining_count: int | None = None
    if all_mode:
        if question_arg is not None:
            raise BootstrapRejection(
                "--all and --question are mutually exclusive"
            )
        question, remaining_count = _pick_next_all_mode_question(
            wiki_root, project_cfg.name, seed_questions
        )
    else:
        if question_arg is None:
            raise BootstrapRejection(
                "--question is required in single-question mode "
                "(or pass --all to iterate seed-questions.md)"
            )
        question = resolve_question(question_arg, seed_questions, ad_hoc=ad_hoc)

    pending = _existing_pending_for_question(
        wiki_root, project_cfg.name, question.key
    )
    if pending is not None and not replace_pending:
        raise BootstrapRejection(
            f"a pending bootstrap proposal already exists for this question "
            f"at {pending}. Promote or delete it first, or pass "
            f"--replace-pending to regenerate."
        )

    project_intent = _load_project_intent(wiki_root, project_cfg.name)

    # Pull top-ranked existing pages via the full retrieval stack, but
    # tolerate a missing `.wiki-index.json` (fresh project with no pages
    # yet — bootstrap should still work and the agent should assume
    # "no existing pages match, consider create").
    try:
        query_results = run_query(
            wiki_root,
            project_cfg.name,
            question.text,
            retrieval_cfg,
            limit=DEFAULT_LIMIT_PAGES,
        )
    except (FileNotFoundError, ValueError):
        # FileNotFoundError: no index saved yet
        # ValueError: stale schema_version from load_index's version guard
        query_results = []
    existing_pages = [
        (r.id, r.title, r.summary, _read_page_body(wiki_root, project_cfg.name, r.id))
        for r in query_results
    ]

    # Score and pick top source docs from the repo
    question_tokens = set(_tokenize(question.text))
    source_docs = _collect_source_candidates(
        project_cfg,
        question_tokens=question_tokens,
        path_filter=path_filter,
        limit=limit_docs,
    )

    context = _build_prepare_context(
        project=project_cfg.name,
        project_intent=project_intent,
        question=question,
        existing_pages=existing_pages,
        source_docs=source_docs,
        all_mode=all_mode,
        remaining_count=remaining_count,
        max_proposals=max_proposals,
    )
    instructions = _build_prepare_instructions(
        question,
        all_mode=all_mode,
        remaining_count=remaining_count,
        max_proposals=max_proposals,
    )

    package = PromptPackage(
        system=SYSTEM_PROMPT,
        context=context,
        schema=_schema_description(),
        instructions=instructions,
        allowed_actions=list(ALLOWED_ACTIONS),
    )

    return BootstrapPrepareResult(
        question=question,
        package=package,
        existing_page_ids=[r.id for r in query_results],
        source_doc_paths=[d.path for d in source_docs],
        existing_pending_path=pending,
        remaining_questions=remaining_count,
        max_proposals_hint=max_proposals,
    )


def _read_page_body(wiki_root: Path, project: str, page_id: str) -> str:
    """Read the full body of a canonical page. Returns empty string on error."""
    from wiki_system.storage import read_page

    path = wiki_root / project / "pages" / f"{page_id}.md"
    if not path.exists():
        return ""
    try:
        _fm, body = read_page(path)
        return body
    except Exception:
        return ""


# ---------- Submit ----------


def run_submit_bootstrap(
    *,
    wiki_root: Path,
    project: str,
    proposal: dict[str, Any],
    replace_pending: bool = False,
) -> BootstrapSubmitResult:
    """Validate a bootstrap proposal and write a state: proposed staged file.

    The proposal MUST contain a top-level `bootstrap_question` block with
    `question_text`, `question_source`, and `question_key`. The question
    provenance is translated into a `BootstrapFrom` and attached to the
    staged file.

    `noop` short-circuits without writing (same pattern as capture submit).
    For `create`/`update`, delegates to the shared staging_write helper.

    Dedupe: if a pending bootstrap proposal already exists for this
    question_key and `replace_pending` is False, reject. If True, delete
    the existing pending file first.
    """
    action = proposal.get("action")
    if action not in ALLOWED_ACTIONS:
        raise BootstrapRejection(
            f"proposal.action must be one of {ALLOWED_ACTIONS}, got {action!r}"
        )

    # Extract and validate the bootstrap_question block before any write
    raw_bq = proposal.get("bootstrap_question")
    if not isinstance(raw_bq, dict):
        raise BootstrapRejection(
            "bootstrap proposal must include a top-level `bootstrap_question` "
            "block echoing the provenance from the prompt package"
        )
    try:
        bootstrap_from = BootstrapFrom.model_validate(raw_bq)
    except Exception as e:
        raise BootstrapRejection(f"bootstrap_question invalid: {e}") from e

    if action == "noop":
        return BootstrapSubmitResult(
            action="noop",
            staging_path="",
            proposed_page_id=None,
            question_key=bootstrap_from.question_key,
        )

    # Dedupe check at submit time too — prepare already enforced it but
    # the agent may have submitted against a stale prepare-package.
    pending = _existing_pending_for_question(
        wiki_root, project, bootstrap_from.question_key
    )
    if pending is not None:
        if not replace_pending:
            raise BootstrapRejection(
                f"a pending bootstrap proposal already exists for question "
                f"{bootstrap_from.question_key!r} at {pending}. Promote or "
                f"delete it first, or re-run with --replace-pending."
            )
        pending.unlink()

    try:
        result = write_proposed_staged_file(
            wiki_root=wiki_root,
            project=project,
            proposal=proposal,
            origin=StagedFileOrigin.BOOTSTRAP,
            created_by="wiki bootstrap",
            bootstrap_from=bootstrap_from,
        )
    except StagingWriteError as e:
        raise BootstrapRejection(str(e)) from e

    return BootstrapSubmitResult(
        action=result.action,
        staging_path=str(result.path),
        proposed_page_id=result.proposed_page_id,
        question_key=bootstrap_from.question_key,
    )
