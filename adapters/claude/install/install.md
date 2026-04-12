# Installing the wiki plugin

## One-time setup

1. Install `wiki-system`:
   ```bash
   cd ~/Git/wiki-system && uv venv && source .venv/bin/activate && uv pip install -e .
   ```
   This puts a `wiki` binary on your PATH.

2. Create the wiki data repo:
   ```bash
   mkdir -p ~/Git/wiki && cd ~/Git/wiki && git init
   ```

3. Author `~/Git/wiki/wiki.config.toml`. See `wiki.config.example.toml` in `wiki-system/`.

4. Enable the Claude plugin: symlink or copy `wiki-system/adapters/claude/` into `~/.claude/plugins/wiki/` (or add it as a plugin source in your Claude Code settings).

## Per-project setup

For each project you want wiki-enabled, do these three things in the project's repo:

### 1. Add to `CLAUDE.md`

See `install/claude-md-snippet.md`. Paste it under a `## Wiki` heading.

### 2. Pre-grant wiki access

Edit `.claude/settings.local.json`:
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
Replace `<project>` with the project name in `wiki.config.toml`.

### 3. Add the project to `wiki.config.toml`

```toml
[[projects]]
name = "<project>"
repo_path = "<absolute path to the project repo>"
source_globs = ["docs/**/*.md"]
```

## Verification

From inside the project repo:
```bash
wiki query <project> "test"
```
Should return either results or exit 2 (no results). Either is success.
