## Wiki

Compiled project knowledge for this project lives at `/Users/diegovaille/Git/wiki/<project>/`.

- **Wiki binary (absolute path — NOT on PATH):**
  `/Users/diegovaille/Git/wiki-system/.venv/bin/wiki --config /Users/diegovaille/Git/wiki/wiki.config.toml`
- **Start-of-session orientation** (when a task is wiki-relevant): read `/Users/diegovaille/Git/wiki/<project>/views/index.md` — it's a regenerated map of all canonical pages by type.
- **`/wiki-query <question>`** — search compiled knowledge before falling back to `docs/`.
- **`/wiki-capture`** — distill a session learning into at most one canonical change. Default to noop; prefer update over create. Never invoke autonomously mid-session.
- **`/wiki-review`** — see pending staged items.
- **`/wiki-promote <path>`** — apply a proposed staged file after dry-run.

Never edit `/Users/diegovaille/Git/wiki/<project>/pages/*.md` or `views/*.md` directly. Never ad-hoc `grep`/`rg` into `~/Git/wiki/` — always go through `wiki query`.
