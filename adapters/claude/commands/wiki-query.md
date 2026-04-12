---
name: wiki-query
description: Search the project wiki for compiled knowledge on a topic.
---

Run `wiki query <project> "$ARGUMENTS" --limit=5` where `<project>` is inferred from the current working directory against `wiki.config.toml`.

Steps:
1. Detect the project name from the current repo path vs `[[projects]] repo_path` in `~/Git/wiki/wiki.config.toml`.
2. Run: `wiki query <project> "$ARGUMENTS"`
3. Parse the JSON on stdout. For each of the top 3 results, show: `title (id) — snippet — reasons`.
4. If a result looks relevant to the user's question, open it with `Read` and cite it.
5. If `wiki query` exits with code 2 (no results), tell the user the wiki has nothing on this topic and fall back to raw project docs.

Do not ad-hoc grep into `~/Git/wiki/` — always go through `wiki query`.
