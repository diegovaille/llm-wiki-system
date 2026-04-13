"""Generate per-machine adapter artifacts with resolved local paths.

The adapter under adapters/claude/templates/ ships with {{PLACEHOLDER}}
variables. `wiki init` substitutes real paths for the current machine and
writes the rendered output in two tiers:

1. **Canonical** under `~/.agents/skills/wiki/` and `~/.agents/commands/`
   — the shared-agent location other frameworks (Codex, etc.) can also
   discover. This is the source of truth.
2. **Per-agent symlinks** under `~/.claude/skills/wiki` and
   `~/.claude/commands/wiki-*.md` — so Claude Code picks up the skill
   and slash commands from its own discovery directories.

Re-running `wiki init` is idempotent: it overwrites canonical files and
refreshes the symlinks, and leaves everything else alone.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path


TEMPLATE_SUFFIX = ".tmpl"

PLACEHOLDER_WIKI_CMD = "{{WIKI_CMD}}"
PLACEHOLDER_WIKI_CONFIG_PATH = "{{WIKI_CONFIG_PATH}}"
PLACEHOLDER_WIKI_DATA_ROOT = "{{WIKI_DATA_ROOT}}"
PLACEHOLDER_WIKI_BIN = "{{WIKI_BIN}}"


@dataclass
class InitConfig:
    """Inputs and resolved paths for a `wiki init` run.

    All paths are absolute. `wiki_system_root` is the checkout root of the
    wiki-system repo; `wiki_data_root` is where the user's wiki data lives
    (the `[wiki] root` value in wiki.config.toml); `agents_dir` is the
    canonical shared-agent directory (skills + commands live under it);
    `claude_dir` is where Claude Code reads its own copies (via symlinks
    into the canonical location).
    """

    wiki_system_root: Path
    wiki_data_root: Path
    wiki_config_path: Path
    wiki_bin: Path
    agents_dir: Path
    claude_dir: Path

    @property
    def wiki_cmd(self) -> str:
        """Canonical invocation: absolute binary plus --config flag."""
        return f"{self.wiki_bin} --config {self.wiki_config_path}"

    def substitutions(self) -> dict[str, str]:
        return {
            PLACEHOLDER_WIKI_CMD: self.wiki_cmd,
            PLACEHOLDER_WIKI_CONFIG_PATH: str(self.wiki_config_path),
            PLACEHOLDER_WIKI_DATA_ROOT: str(self.wiki_data_root),
            PLACEHOLDER_WIKI_BIN: str(self.wiki_bin),
        }


@dataclass
class InitResult:
    """What `wiki init` wrote. Used by the CLI to print a summary."""

    rendered: list[Path] = field(default_factory=list)
    symlinks: list[tuple[Path, Path]] = field(default_factory=list)
    seeded_config: Path | None = None
    permissions_snippet: str = ""


def render_template(template_text: str, substitutions: dict[str, str]) -> str:
    """Replace every placeholder occurrence in the template text."""
    out = template_text
    for placeholder, value in substitutions.items():
        out = out.replace(placeholder, value)
    return out


def resolve_config(
    wiki_system_root: Path,
    wiki_data_root: Path,
    agents_dir: Path,
    claude_dir: Path,
) -> InitConfig:
    wiki_system_root = wiki_system_root.expanduser().resolve()
    wiki_data_root = wiki_data_root.expanduser().resolve()
    agents_dir = agents_dir.expanduser().resolve()
    claude_dir = claude_dir.expanduser().resolve()
    return InitConfig(
        wiki_system_root=wiki_system_root,
        wiki_data_root=wiki_data_root,
        wiki_config_path=wiki_data_root / "wiki.config.toml",
        wiki_bin=wiki_system_root / ".venv" / "bin" / "wiki",
        agents_dir=agents_dir,
        claude_dir=claude_dir,
    )


def seed_wiki_config_if_missing(cfg: InitConfig) -> Path | None:
    """Copy wiki.config.example.toml into the wiki data repo if no config exists.

    Returns the path that was written, or None if a config already existed.
    Does NOT create the wiki data repo itself or run `git init` — that's the
    caller's responsibility (the CLI does it; tests pass an existing dir).
    """
    if cfg.wiki_config_path.exists():
        return None
    example = cfg.wiki_system_root / "wiki.config.example.toml"
    if not example.exists():
        raise FileNotFoundError(
            f"wiki.config.example.toml not found at {example}; "
            f"cannot seed a config for a fresh wiki data repo"
        )
    cfg.wiki_data_root.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(example, cfg.wiki_config_path)
    return cfg.wiki_config_path


def render_adapter(cfg: InitConfig) -> dict[Path, str]:
    """Render every template under adapters/claude/templates/.

    Returns a map of absolute destination paths to rendered content. Output
    paths strip the .tmpl suffix and route each template to its canonical
    location under `agents_dir`:

    - templates/skills/wiki/SKILL.md.tmpl        → agents_dir/skills/wiki/SKILL.md
    - templates/commands/wiki-query.md.tmpl      → agents_dir/commands/wiki-query.md
    - templates/claude-md-snippet.md.tmpl        → wiki-system/adapters/claude/_generated/claude-md-snippet.md

    The claude-md-snippet is NOT installed anywhere; it's a copy-paste
    helper the user drops into a project's CLAUDE.md manually.
    """
    templates_root = cfg.wiki_system_root / "adapters" / "claude" / "templates"
    if not templates_root.exists():
        raise FileNotFoundError(
            f"adapter templates not found at {templates_root}"
        )
    subs = cfg.substitutions()
    out: dict[Path, str] = {}
    for template in sorted(templates_root.rglob(f"*{TEMPLATE_SUFFIX}")):
        rel = template.relative_to(templates_root)
        rel_out = rel.with_name(rel.name.removesuffix(TEMPLATE_SUFFIX))
        rendered = render_template(template.read_text(), subs)
        if rel_out.name == "claude-md-snippet.md":
            dest = (
                cfg.wiki_system_root
                / "adapters"
                / "claude"
                / "_generated"
                / "claude-md-snippet.md"
            )
        else:
            dest = cfg.agents_dir / rel_out
        out[dest] = rendered
    return out


def write_adapter(rendered: dict[Path, str]) -> list[Path]:
    """Write rendered output to disk, overwriting existing files.

    Parent directories are created as needed. Existing destinations are
    overwritten unconditionally — `wiki init` is idempotent and the user
    can re-run after editing templates.

    If a destination is currently a symlink, the symlink is removed first
    so we write a real file.
    """
    written: list[Path] = []
    for dest, content in rendered.items():
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.is_symlink() or dest.exists():
            dest.unlink()
        dest.write_text(content)
        written.append(dest)
    return sorted(written)


def install_claude_symlinks(
    cfg: InitConfig, rendered: dict[Path, str] | None = None
) -> list[tuple[Path, Path]]:
    """Create Claude Code symlinks pointing at canonical agents_dir files.

    Writes:
    - claude_dir/skills/<name>     → agents_dir/skills/<name> (directory)
      for every skill directory we just rendered under agents_dir/skills/.
      Pluggable: any sub-skill under templates/skills/<name>/ is picked
      up automatically — no hardcoded "wiki" special case.
    - claude_dir/commands/wiki-*.md → agents_dir/commands/wiki-*.md (files)

    `rendered` is the output of `render_adapter`. Skill directories are
    derived from it (which avoids picking up unrelated skills under
    ~/.agents/skills/ that belong to other plugins). If `rendered` is
    omitted, falls back to scanning `agents_dir/skills/` — less precise
    but keeps the function usable in isolation for tests.

    Returns a list of `(symlink_path, target_path)` pairs that were
    created. Existing symlinks, real files, or real directories at the
    destinations are replaced.
    """
    links: list[tuple[Path, Path]] = []

    # Discover skill directories. Derive from the rendered set when we
    # have it, so we never accidentally symlink skills we didn't author.
    skill_dirs: set[Path] = set()
    if rendered is not None:
        for dest in rendered:
            try:
                rel = dest.relative_to(cfg.agents_dir)
            except ValueError:
                continue  # generated snippet, outside agents_dir
            parts = rel.parts
            if len(parts) >= 2 and parts[0] == "skills":
                skill_dirs.add(cfg.agents_dir / "skills" / parts[1])
    else:
        skills_root = cfg.agents_dir / "skills"
        if skills_root.exists():
            skill_dirs.update(
                p for p in skills_root.iterdir() if p.is_dir()
            )

    for skill_src in sorted(skill_dirs):
        skill_dest = cfg.claude_dir / "skills" / skill_src.name
        skill_dest.parent.mkdir(parents=True, exist_ok=True)
        if skill_dest.is_symlink() or skill_dest.exists():
            if skill_dest.is_dir() and not skill_dest.is_symlink():
                shutil.rmtree(skill_dest)
            else:
                skill_dest.unlink()
        os.symlink(skill_src, skill_dest)
        links.append((skill_dest, skill_src))

    # Commands (per-file symlinks; glob is broad enough to pick up new files)
    commands_src = cfg.agents_dir / "commands"
    commands_dest = cfg.claude_dir / "commands"
    if commands_src.exists():
        commands_dest.mkdir(parents=True, exist_ok=True)
        for cmd_file in sorted(commands_src.glob("wiki-*.md")):
            link = commands_dest / cmd_file.name
            if link.is_symlink() or link.exists():
                link.unlink()
            os.symlink(cmd_file, link)
            links.append((link, cmd_file))
    return links


def build_permissions_snippet(cfg: InitConfig) -> str:
    """The JSON fragment the user pastes into ~/.claude/settings.json."""
    return (
        '  "permissions": {\n'
        '    "allow": [\n'
        f'      "Bash({cfg.wiki_bin} *)",\n'
        f'      "Read({cfg.wiki_data_root}/**)"\n'
        '    ]\n'
        '  }'
    )


def run_init(
    *,
    wiki_system_root: Path,
    wiki_data_root: Path,
    agents_dir: Path,
    claude_dir: Path,
) -> InitResult:
    """End-to-end init: resolve, seed, render, write, symlink.

    Does NOT modify ~/.claude/settings.json — that's a user action. Instead
    we return a permissions snippet in the result so the caller can print
    it with instructions.
    """
    cfg = resolve_config(
        wiki_system_root=wiki_system_root,
        wiki_data_root=wiki_data_root,
        agents_dir=agents_dir,
        claude_dir=claude_dir,
    )
    seeded = seed_wiki_config_if_missing(cfg)
    rendered = render_adapter(cfg)
    written = write_adapter(rendered)
    symlinks = install_claude_symlinks(cfg, rendered)
    return InitResult(
        rendered=written,
        symlinks=symlinks,
        seeded_config=seeded,
        permissions_snippet=build_permissions_snippet(cfg),
    )
