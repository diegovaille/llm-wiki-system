---
name: wiki-query
description: Search the project wiki for compiled knowledge on a topic.
---

**Binary (absolute path — NOT on PATH):**
`/Users/diegovaille/Git/wiki-system/.venv/bin/wiki --config /Users/diegovaille/Git/wiki/wiki.config.toml`

Below, `WIKI` refers to that absolute invocation.

Steps:
1. Detect the project name from the current repo path vs `[[projects]] repo_path` in `/Users/diegovaille/Git/wiki/wiki.config.toml`.
2. Run: `WIKI query <project> "$ARGUMENTS" --limit=5`
3. Parse the JSON on stdout. For each of the top 3 results, show: `title (id) — snippet — reasons`.
4. If a result looks relevant to the user's question, open it with `Read` and cite it.
5. If `WIKI query` exits with code 2 (no results), tell the user the wiki has nothing on this topic and fall back to raw project docs.

Do not ad-hoc grep into `/Users/diegovaille/Git/wiki/` — always go through `WIKI query`.
