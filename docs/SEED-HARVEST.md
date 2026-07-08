# Seed harvest: turning graph-report highlights into seed questions

This is a manual procedure, deliberately not automated. `wiki-system` biases
hard toward under-capture — an empty wiki is honest, a wiki stuffed with
low-value auto-generated questions is not. Automating this step would trade
a curated, high-signal `seed-questions.md` for a bulk import nobody reads.

## When to run this

After each code-graph rebuild (e.g. `graphify` regenerating `GRAPH_REPORT.md`
for the project's codebase).

## Procedure

1. **Skim, don't read exhaustively.** Open the rebuilt `GRAPH_REPORT.md` and
   look at the **God Nodes** and **Surprising Connections** sections only.
   These are the two sections designed to surface things a human wouldn't
   have thought to ask about — everything else in the report is reference
   material, not harvest material.

2. **Pick one concept at a time.** For each god node or surprising connection
   that catches your attention, ask two questions:
   - **(a) Does it recur across communities?** A symbol or file that shows up
     as a hub across multiple clusters is more likely to represent a real
     cross-cutting concept than a symbol that's merely locally popular.
   - **(b) Does the wiki already have a page for it?** Check with
     `wiki query <project> "<concept>"` (or `/wiki-query`) before writing
     anything down. If an existing page already answers the "why does this
     matter" question, there is nothing to harvest — move on.

3. **If both (a) and (b) hold** (recurs across communities, no existing
   page), append **exactly one** candidate line to
   `<project>/queries/seed-questions.md`, phrased as a genuine question, not
   a topic label:

   ```
   - Why does `AuthContext` sit between the `auth` and `chat` communities?
   ```

   Good candidate questions read like something a new engineer would ask.
   Bad candidates restate the report ("AuthContext is a god node") instead of
   asking why it matters.

4. **Stop after one line per concept.** Do not batch-transcribe the entire
   God Nodes table. If several items seem worth capturing, add them as
   separate lines across separate review passes rather than in one sweep —
   this keeps the seed list a curated queue, not a dump.

5. **Resolve later, not now.** Harvesting only adds the question to the seed
   list. Resolving it — deciding whether it becomes a real page, a noop, or
   an ad-hoc follow-up — happens later via `wiki bootstrap prepare --question
   "..."` (or the `/wiki-bootstrap` slash command), not as part of this
   procedure.

## Hard rules

- **Never bulk-import.** Do not script "every god node becomes a seed
  question." The whole point of this procedure is a human judgment call per
  concept — that's what keeps the seed list worth reading.
- **Never add a question an existing page already answers.** Always run
  `wiki query` first. A duplicate question wastes a future `bootstrap`
  session re-deriving something already written down.
- **One line per harvest, not one line per report.** A single graph rebuild
  may surface several worthwhile candidates over several sessions; resist
  the urge to add all of them in one pass just because the report is open.
