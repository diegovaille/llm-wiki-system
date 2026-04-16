# Installing the wiki plugin into Claude Code

`wiki-system` ships adapter templates, not rendered adapter files. The `wiki init` command renders the templates with paths specific to your machine and writes them into `~/.claude/` (or wherever your Claude Code config lives).

The result: `/wiki-query`, `/wiki-capture`, `/wiki-review`, `/wiki-promote`, `/wiki-sync`, and `/wiki-bootstrap` are available in every Claude Code session on this machine. The plugin works globally, but only does useful work inside repos that are registered as wiki projects in `wiki.config.toml`.

## One-time setup

### 1. Install wiki-system

```bash
git clone <this repo> ~/Git/wiki-system
cd ~/Git/wiki-system
uv venv && uv sync
```

This creates `.venv/bin/wiki`. Verify it runs:

```bash
~/Git/wiki-system/.venv/bin/wiki --help
```

You can put `wiki` on PATH (e.g. `ln -s ~/Git/wiki-system/.venv/bin/wiki ~/.local/bin/wiki`) but `wiki init` assumes the binary lives at `<wiki-system-root>/.venv/bin/wiki` and hard-codes the absolute path into the Claude adapter, so PATH inheritance does not matter for slash-command invocations.

### 2. Run `wiki init`

```bash
cd ~/Git/wiki-system && .venv/bin/wiki --no-json init
```

What this does:

1. Seeds a `~/Git/wiki/wiki.config.toml` from `wiki.config.example.toml` if none exists. Edit it after the run to add a `[[projects]]` block for each codebase you want wiki-enabled.
2. Renders every template under `adapters/claude/templates/` with your actual paths substituted for `{{WIKI_CMD}}`, `{{WIKI_CONFIG_PATH}}`, and `{{WIKI_DATA_ROOT}}`.
3. **Canonical install (shared across agent frameworks):** writes the rendered `wiki` and `wiki-bootstrap` skills to `~/.agents/skills/wiki/SKILL.md` and `~/.agents/skills/wiki-bootstrap/SKILL.md`, and slash commands to `~/.agents/commands/wiki-{query,capture,review,promote,sync,bootstrap}.md`. Any agent framework that discovers `~/.agents/` as its skill source can reuse these.
4. **Claude Code install:** creates symlinks under `~/.claude/skills/wiki`, `~/.claude/skills/wiki-bootstrap`, and `~/.claude/commands/wiki-*.md` pointing at the canonical files above. Claude Code reads its own config directory but follows the symlinks, so a single canonical copy serves every agent.
5. Writes a `claude-md-snippet.md` helper to `adapters/claude/_generated/` (gitignored). Paste its content into any project's `CLAUDE.md` you want to wiki-enable, if you want start-of-session orientation.
6. Prints a `permissions` JSON snippet for your global Claude settings (see next step).

Flags:

- `--wiki-system-root PATH` — override the wiki-system checkout location (default: this repo's root).
- `--wiki-data-root PATH` — override where the wiki data repo lives (default: `~/Git/wiki`).
- `--agents-dir PATH` — override the shared-agent canonical location (default: `~/.agents`).
- `--claude-dir PATH` — override the Claude Code config directory (default: `~/.claude`).
- `--dry-run` — print the full plan (rendered files, symlinks, config to seed, permissions snippet) without touching disk. No files, directories, or symlinks are created; no `git init` is run. Safe to use on any machine to preview exactly what a real `wiki init` would change. Re-run without `--dry-run` to apply.

**Recommended first run:**

```bash
~/Git/wiki-system/.venv/bin/wiki --no-json init --dry-run
```

Review the plan, then repeat without `--dry-run`.

### 3. Add the permissions snippet

`wiki init` prints a JSON fragment like:

```json
  "permissions": {
    "allow": [
      "Bash(/Users/you/Git/wiki-system/.venv/bin/wiki *)",
      "Read(/Users/you/Git/wiki/**)"
    ]
  }
```

Open `~/.claude/settings.json`, merge this into the top-level object (next to `enabledPlugins`, `mcpServers`, etc.). If a `permissions` block already exists, merge the `allow` arrays rather than replacing.

These are user-level permissions that apply to every Claude Code session — no per-project wiring needed.

### 4. Configure projects

Edit `~/Git/wiki/wiki.config.toml`. For each codebase you want wiki-enabled, add a `[[projects]]` block:

```toml
[[projects]]
name = "my-project"
repo_path = "~/Git/my-project"
source_globs = ["docs/**/*.md"]
```

The `name` is the project identifier used everywhere (`wiki query my-project "..."`, page `project:` frontmatter, the wiki subtree at `<wiki.root>/<name>/`).

### 5. Restart Claude Code and verify

Open a new Claude Code session in any directory. Type `/wiki` — autocomplete should show `/wiki-query`, `/wiki-capture`, `/wiki-review`, `/wiki-promote`, `/wiki-sync`, `/wiki-bootstrap`. Run:

```
/wiki-query my-project "test"
```

from a repo whose path matches one of your `[[projects]] repo_path` entries. You should get ranked JSON results, exit code 2 (no results), or exit code 4 (index unavailable — run `wiki index my-project` first). Any of these are success signals.

## Per-project opt-in (optional)

If you want Claude to automatically orient on a project's wiki at session start, paste the rendered `claude-md-snippet.md` (at `adapters/claude/_generated/claude-md-snippet.md`) into that project's `CLAUDE.md` under a new `## Wiki` heading.

This is optional — the slash commands still work without it. The snippet just adds a nudge so Claude reads `views/index.md` for that project early.

## Updating after `git pull`

If you pull new wiki-system commits that touch adapter templates, re-run:

```bash
cd ~/Git/wiki-system && .venv/bin/wiki --no-json init
```

`wiki init` is idempotent — it overwrites the rendered files in `~/.claude/` with the new template output. Your `wiki.config.toml` is preserved (only seeded on the first run).

## Uninstall

```bash
# Remove the Claude Code symlinks
rm -rf ~/.claude/skills/wiki ~/.claude/skills/wiki-bootstrap \
       ~/.claude/commands/wiki-query.md \
       ~/.claude/commands/wiki-capture.md \
       ~/.claude/commands/wiki-review.md \
       ~/.claude/commands/wiki-promote.md \
       ~/.claude/commands/wiki-sync.md \
       ~/.claude/commands/wiki-bootstrap.md

# Remove the canonical files under ~/.agents/ (only if no other agent uses them)
rm -rf ~/.agents/skills/wiki ~/.agents/skills/wiki-bootstrap \
       ~/.agents/commands/wiki-query.md \
       ~/.agents/commands/wiki-capture.md \
       ~/.agents/commands/wiki-review.md \
       ~/.agents/commands/wiki-promote.md \
       ~/.agents/commands/wiki-sync.md \
       ~/.agents/commands/wiki-bootstrap.md
```

Then remove the `permissions.allow` entries from `~/.claude/settings.json`. Your wiki data at `~/Git/wiki/` is unaffected; delete it separately if you want to remove the content too.

## Troubleshooting

**`command not found: wiki`** — you're relying on PATH. The rendered adapter uses absolute paths by design, so Claude Code's bash tool will always find the binary. Your terminal is a separate issue; put `.venv/bin/wiki` on PATH or use the absolute path.

**Permission prompts on every wiki invocation** — your `~/.claude/settings.json` doesn't have the `permissions.allow` entries, or the pattern doesn't match. Re-run `wiki init` and copy the printed snippet verbatim.

**`/wiki-query` can't find the project** — the current working directory does not match any `[[projects]] repo_path` in `wiki.config.toml`. Either add the project, or pass the project name explicitly: `wiki query <project-name> "<question>"`.

**`wiki init` says `wiki.config.example.toml not found`** — you're running it from outside the wiki-system checkout, or you deleted the example file. Re-clone or pass `--wiki-system-root` pointing at the correct path.
