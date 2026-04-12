# Installing the wiki plugin

The wiki plugin supports two install scopes:

- **Global (user-wide)** — once installed, every Claude Code session on this machine can invoke `/wiki-query`, `/wiki-capture`, etc. This is the primary install path.
- **Per-project opt-in (optional)** — add a short snippet to a project's `CLAUDE.md` so Claude orients on `views/index.md` at session start. Without this, the plugin still works; you just lose the opening nudge.

The wiki binary is **NOT** on PATH. All slash commands and templates invoke it by absolute path:

```
/Users/diegovaille/Git/wiki-system/.venv/bin/wiki --config /Users/diegovaille/Git/wiki/wiki.config.toml
```

Using the absolute path avoids Claude Code's shell environment not inheriting your `$PATH`.

---

## 1. Global install (do this once per machine)

### 1a. Install the wiki-system package

```bash
cd /Users/diegovaille/Git/wiki-system
uv venv && uv sync
uv pip install -e .
```

This creates `.venv/bin/wiki`. Verify:

```bash
/Users/diegovaille/Git/wiki-system/.venv/bin/wiki --help
```

### 1b. Seed the wiki data repo (if not already)

```bash
mkdir -p /Users/diegovaille/Git/wiki && cd /Users/diegovaille/Git/wiki && git init
```

Create `/Users/diegovaille/Git/wiki/wiki.config.toml` (see `wiki.config.example.toml` in wiki-system). For each project you want wiki-enabled, add a `[[projects]]` block:

```toml
[[projects]]
name = "<project>"
repo_path = "<absolute path to the project repo>"
source_globs = ["docs/**/*.md"]
```

### 1c. Register the skill and slash commands with Claude Code

Claude Code does not have a "register local plugin directory" slash command. Two supported paths:

**Path A (recommended, persistent, zero ceremony) — symlink drop-in.**
Claude Code auto-discovers skills under `~/.claude/skills/<name>/SKILL.md` and slash commands under `~/.claude/commands/<name>.md`. Symlinks are followed, so you can point them at this repo and keep the source of truth here:

```bash
ln -s /Users/diegovaille/Git/wiki-system/adapters/claude/skills/wiki ~/.claude/skills/wiki
mkdir -p ~/.claude/commands
ln -s /Users/diegovaille/Git/wiki-system/adapters/claude/commands/wiki-query.md ~/.claude/commands/wiki-query.md
ln -s /Users/diegovaille/Git/wiki-system/adapters/claude/commands/wiki-capture.md ~/.claude/commands/wiki-capture.md
ln -s /Users/diegovaille/Git/wiki-system/adapters/claude/commands/wiki-review.md ~/.claude/commands/wiki-review.md
ln -s /Users/diegovaille/Git/wiki-system/adapters/claude/commands/wiki-promote.md ~/.claude/commands/wiki-promote.md
```

Start a new Claude Code session; `/wiki-query`, `/wiki-capture`, `/wiki-review`, `/wiki-promote` will be available user-wide. Future edits to the source files are picked up automatically because the entries are symlinks.

**Path B (session-scoped testing) — `--plugin-dir` flag.**
Launch Claude Code with:

```bash
claude --plugin-dir /Users/diegovaille/Git/wiki-system/adapters/claude
```

This loads the full plugin manifest (including `plugin.json`) but only for that process. Useful when iterating on plugin metadata; not the persistent install path.

**Path C (advanced) — local marketplace + `claude plugin install`.**
Create a marketplace descriptor pointing at `adapters/claude/`, register it in `~/.claude/settings.json` under `extraKnownMarketplaces`, then `claude plugin install wiki@<marketplace-name>`. Right way if you'll ever share this plugin with other users or want versioning. Overkill for a single-developer machine — prefer Path A.

### 1d. Grant global permissions

Add to `/Users/diegovaille/.claude/settings.json` under a top-level `permissions.allow` block (create it if it doesn't exist):

```json
"permissions": {
  "allow": [
    "Bash(/Users/diegovaille/Git/wiki-system/.venv/bin/wiki *)",
    "Read(/Users/diegovaille/Git/wiki/**)"
  ]
}
```

These apply to every Claude Code session on this machine. No per-project permission wiring needed.

### 1e. Verify

From any Claude session in any directory:

```
/wiki-query <project> "test"
```

(Use a project that's configured in `wiki.config.toml`.) Should return ranked JSON results or exit 2 (no results). Both are success.

---

## 2. Per-project opt-in (optional)

If you want Claude to orient on a project's wiki at session start without being asked, add a snippet to that project's `CLAUDE.md`.

### 2a. Append to `CLAUDE.md`

See `install/claude-md-snippet.md`. Paste it under a new `## Wiki` heading at the end of the project's `CLAUDE.md`. Change `<project>` to the project's name in `wiki.config.toml`.

### 2b. Project-specific permission overrides (usually NOT needed)

The global permissions from step 1d apply to every project. Only add project-specific permissions in `.claude/settings.local.json` if:

- you want to grant access narrower than global (e.g., a specific wiki subtree only), or
- global permissions have been explicitly denied for this project

In all other cases, rely on the global grant.

---

## Uninstall

- Remove the symlinks: `rm ~/.claude/skills/wiki ~/.claude/commands/wiki-*.md`
- Remove the `permissions.allow` entries from `~/.claude/settings.json`
- Optionally, remove the `## Wiki` section from any project's `CLAUDE.md`

---

## Troubleshooting

**`wiki: command not found`** — you're relying on PATH. Use the absolute path as shown above; the binary is not symlinked to `/usr/local/bin` or `~/.local/bin` by this install.

**Permission prompts on every wiki invocation** — your `permissions.allow` entry is missing or the pattern doesn't match. The exact pattern is `Bash(/Users/diegovaille/Git/wiki-system/.venv/bin/wiki *)`. Escape/literal matters — copy it verbatim.

**`/wiki-query` can't find the project** — the current working directory does not match any `[[projects]] repo_path` in `wiki.config.toml`. Either add the project, or pass the project name explicitly.
