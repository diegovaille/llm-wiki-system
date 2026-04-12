"""Tests for `wiki_system.init` — adapter template rendering and two-tier install."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from wiki_system.cli import main
from wiki_system.init import (
    PLACEHOLDER_WIKI_CMD,
    PLACEHOLDER_WIKI_CONFIG_PATH,
    PLACEHOLDER_WIKI_DATA_ROOT,
    build_permissions_snippet,
    install_claude_symlinks,
    render_adapter,
    render_template,
    resolve_config,
    run_init,
    seed_wiki_config_if_missing,
    write_adapter,
)


REPO_ROOT = Path(__file__).resolve().parent.parent


def _make_init_inputs(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    """Returns (wiki_system_root, wiki_data_root, agents_dir, claude_dir).

    Mirrors a minimal wiki-system checkout under tmp so tests don't depend
    on the real repo's `.venv` layout. The wiki data root starts empty so
    `seed_wiki_config_if_missing` fires.
    """
    fake_ws = tmp_path / "wiki-system"
    fake_ws.mkdir()
    # Symlink the real templates directory so tests exercise the actual
    # shipped templates.
    (fake_ws / "adapters" / "claude").mkdir(parents=True)
    (fake_ws / "adapters" / "claude" / "templates").symlink_to(
        REPO_ROOT / "adapters" / "claude" / "templates"
    )
    # Copy wiki.config.example.toml so seed_wiki_config_if_missing finds it.
    (fake_ws / "wiki.config.example.toml").write_text(
        (REPO_ROOT / "wiki.config.example.toml").read_text()
    )
    (fake_ws / ".venv" / "bin").mkdir(parents=True)
    (fake_ws / ".venv" / "bin" / "wiki").write_text("#!/bin/sh\n")

    wiki_data = tmp_path / "wiki"
    agents_dir = tmp_path / "agents"
    claude_dir = tmp_path / "claude"
    return fake_ws, wiki_data, agents_dir, claude_dir


def test_render_template_substitutes_every_placeholder():
    src = "cmd: {{WIKI_CMD}}\nroot: {{WIKI_DATA_ROOT}}\ncfg: {{WIKI_CONFIG_PATH}}"
    out = render_template(
        src,
        {
            PLACEHOLDER_WIKI_CMD: "/abs/wiki --config /data/wiki.config.toml",
            PLACEHOLDER_WIKI_DATA_ROOT: "/data",
            PLACEHOLDER_WIKI_CONFIG_PATH: "/data/wiki.config.toml",
        },
    )
    assert "{{" not in out
    assert "/abs/wiki --config /data/wiki.config.toml" in out
    assert "/data/wiki.config.toml" in out


def test_resolve_config_composes_wiki_cmd(tmp_path: Path):
    cfg = resolve_config(
        wiki_system_root=tmp_path / "ws",
        wiki_data_root=tmp_path / "wiki",
        agents_dir=tmp_path / "agents",
        claude_dir=tmp_path / "claude",
    )
    expected_bin = (tmp_path / "ws" / ".venv" / "bin" / "wiki").resolve()
    assert cfg.wiki_bin == expected_bin
    assert cfg.wiki_cmd == f"{expected_bin} --config {cfg.wiki_config_path}"


def test_seed_wiki_config_copies_example_when_missing(tmp_path: Path):
    fake_ws, wiki_data, agents_dir, claude_dir = _make_init_inputs(tmp_path)
    cfg = resolve_config(fake_ws, wiki_data, agents_dir, claude_dir)
    seeded = seed_wiki_config_if_missing(cfg)
    assert seeded is not None
    assert seeded == cfg.wiki_config_path
    assert cfg.wiki_config_path.exists()
    assert "[[projects]]" in cfg.wiki_config_path.read_text()


def test_seed_wiki_config_noop_when_present(tmp_path: Path):
    fake_ws, wiki_data, agents_dir, claude_dir = _make_init_inputs(tmp_path)
    cfg = resolve_config(fake_ws, wiki_data, agents_dir, claude_dir)
    wiki_data.mkdir()
    cfg.wiki_config_path.write_text("[wiki]\nroot = \"/tmp/existing\"\n")
    result = seed_wiki_config_if_missing(cfg)
    assert result is None
    assert "existing" in cfg.wiki_config_path.read_text()


def test_render_adapter_routes_skill_under_agents_dir(tmp_path: Path):
    fake_ws, wiki_data, agents_dir, claude_dir = _make_init_inputs(tmp_path)
    cfg = resolve_config(fake_ws, wiki_data, agents_dir, claude_dir)
    rendered = render_adapter(cfg)
    skill = next(p for p in rendered if p.name == "SKILL.md")
    assert agents_dir in skill.parents
    assert claude_dir not in skill.parents


def test_render_adapter_routes_commands_under_agents_dir(tmp_path: Path):
    fake_ws, wiki_data, agents_dir, claude_dir = _make_init_inputs(tmp_path)
    cfg = resolve_config(fake_ws, wiki_data, agents_dir, claude_dir)
    rendered = render_adapter(cfg)
    commands = [p for p in rendered if p.name.startswith("wiki-") and p.suffix == ".md"]
    assert len(commands) == 4
    for c in commands:
        assert agents_dir in c.parents
        assert c.parent.name == "commands"


def test_render_adapter_routes_snippet_to_generated_dir(tmp_path: Path):
    fake_ws, wiki_data, agents_dir, claude_dir = _make_init_inputs(tmp_path)
    cfg = resolve_config(fake_ws, wiki_data, agents_dir, claude_dir)
    rendered = render_adapter(cfg)
    snippet = next(p for p in rendered if p.name == "claude-md-snippet.md")
    assert "_generated" in snippet.parts
    assert agents_dir not in snippet.parents
    assert claude_dir not in snippet.parents


def test_render_adapter_substitutes_real_paths(tmp_path: Path):
    fake_ws, wiki_data, agents_dir, claude_dir = _make_init_inputs(tmp_path)
    cfg = resolve_config(fake_ws, wiki_data, agents_dir, claude_dir)
    rendered = render_adapter(cfg)
    for content in rendered.values():
        assert "{{" not in content
        assert "}}" not in content
    skill = next(p for p in rendered if p.name == "SKILL.md")
    assert str(cfg.wiki_bin) in rendered[skill]
    assert str(cfg.wiki_config_path) in rendered[skill]


def test_write_adapter_creates_real_files(tmp_path: Path):
    fake_ws, wiki_data, agents_dir, claude_dir = _make_init_inputs(tmp_path)
    cfg = resolve_config(fake_ws, wiki_data, agents_dir, claude_dir)
    rendered = render_adapter(cfg)
    written = write_adapter(rendered)
    assert len(written) == len(rendered)
    for path in written:
        assert path.exists()
        assert not path.is_symlink()


def test_install_claude_symlinks_creates_skill_directory_symlink(tmp_path: Path):
    fake_ws, wiki_data, agents_dir, claude_dir = _make_init_inputs(tmp_path)
    cfg = resolve_config(fake_ws, wiki_data, agents_dir, claude_dir)
    write_adapter(render_adapter(cfg))
    links = install_claude_symlinks(cfg)
    skill_link = claude_dir / "skills" / "wiki"
    assert skill_link.is_symlink()
    assert skill_link.resolve() == (agents_dir / "skills" / "wiki").resolve()
    assert (skill_link, agents_dir / "skills" / "wiki") in links


def test_install_claude_symlinks_creates_per_command_symlinks(tmp_path: Path):
    fake_ws, wiki_data, agents_dir, claude_dir = _make_init_inputs(tmp_path)
    cfg = resolve_config(fake_ws, wiki_data, agents_dir, claude_dir)
    write_adapter(render_adapter(cfg))
    install_claude_symlinks(cfg)
    commands_link = claude_dir / "commands"
    wiki_links = sorted(commands_link.glob("wiki-*.md"))
    assert len(wiki_links) == 4
    for link in wiki_links:
        assert link.is_symlink()
        assert link.resolve().parent == (agents_dir / "commands").resolve()


def test_install_claude_symlinks_overwrites_existing_symlinks(tmp_path: Path):
    fake_ws, wiki_data, agents_dir, claude_dir = _make_init_inputs(tmp_path)
    cfg = resolve_config(fake_ws, wiki_data, agents_dir, claude_dir)
    # Pre-create a stale symlink pointing somewhere else
    (claude_dir / "skills").mkdir(parents=True)
    stale_target = tmp_path / "stale"
    stale_target.mkdir()
    (claude_dir / "skills" / "wiki").symlink_to(stale_target)
    write_adapter(render_adapter(cfg))
    install_claude_symlinks(cfg)
    skill_link = claude_dir / "skills" / "wiki"
    assert skill_link.is_symlink()
    assert skill_link.resolve() == (agents_dir / "skills" / "wiki").resolve()


def test_install_claude_symlinks_replaces_existing_real_directory(tmp_path: Path):
    fake_ws, wiki_data, agents_dir, claude_dir = _make_init_inputs(tmp_path)
    cfg = resolve_config(fake_ws, wiki_data, agents_dir, claude_dir)
    # Pre-create a real directory where the skill should land
    skill_dest = claude_dir / "skills" / "wiki"
    skill_dest.mkdir(parents=True)
    (skill_dest / "stale.md").write_text("old")
    write_adapter(render_adapter(cfg))
    install_claude_symlinks(cfg)
    assert skill_dest.is_symlink()
    assert not (skill_dest / "stale.md").exists()


def test_build_permissions_snippet_uses_resolved_paths(tmp_path: Path):
    fake_ws, wiki_data, agents_dir, claude_dir = _make_init_inputs(tmp_path)
    cfg = resolve_config(fake_ws, wiki_data, agents_dir, claude_dir)
    snippet = build_permissions_snippet(cfg)
    assert "permissions" in snippet
    assert f"Bash({cfg.wiki_bin} *)" in snippet
    assert f"Read({cfg.wiki_data_root}/**)" in snippet


def test_run_init_end_to_end(tmp_path: Path):
    fake_ws, wiki_data, agents_dir, claude_dir = _make_init_inputs(tmp_path)
    result = run_init(
        wiki_system_root=fake_ws,
        wiki_data_root=wiki_data,
        agents_dir=agents_dir,
        claude_dir=claude_dir,
    )
    assert result.seeded_config is not None
    # SKILL + 4 commands + snippet = 6 canonical files
    assert len(result.rendered) == 6
    # 1 skill dir symlink + 4 command symlinks = 5
    assert len(result.symlinks) == 5
    # Skill in agents canonical, symlinked under claude
    canonical_skill = agents_dir.resolve() / "skills" / "wiki" / "SKILL.md"
    claude_skill = claude_dir.resolve() / "skills" / "wiki" / "SKILL.md"
    assert canonical_skill.exists()
    assert claude_skill.exists()
    assert "{{WIKI_CMD}}" not in canonical_skill.read_text()


def test_run_init_is_idempotent(tmp_path: Path):
    fake_ws, wiki_data, agents_dir, claude_dir = _make_init_inputs(tmp_path)
    run_init(
        wiki_system_root=fake_ws,
        wiki_data_root=wiki_data,
        agents_dir=agents_dir,
        claude_dir=claude_dir,
    )
    # Second run should not raise and should preserve structure.
    result = run_init(
        wiki_system_root=fake_ws,
        wiki_data_root=wiki_data,
        agents_dir=agents_dir,
        claude_dir=claude_dir,
    )
    # Second run leaves wiki.config.toml alone
    assert result.seeded_config is None
    canonical_skill = agents_dir.resolve() / "skills" / "wiki" / "SKILL.md"
    assert canonical_skill.exists()
    claude_skill = claude_dir.resolve() / "skills" / "wiki"
    assert claude_skill.is_symlink()


def test_cli_init_json_output_shape(tmp_path: Path):
    fake_ws, wiki_data, agents_dir, claude_dir = _make_init_inputs(tmp_path)
    runner = CliRunner()
    r = runner.invoke(
        main,
        [
            "init",
            "--wiki-system-root",
            str(fake_ws),
            "--wiki-data-root",
            str(wiki_data),
            "--agents-dir",
            str(agents_dir),
            "--claude-dir",
            str(claude_dir),
        ],
    )
    assert r.exit_code == 0, (r.stdout, r.stderr)
    payload = json.loads(r.stdout)
    assert "rendered" in payload
    assert "symlinks" in payload
    assert "permissions_snippet" in payload
    assert len(payload["rendered"]) == 6
    assert len(payload["symlinks"]) == 5


def test_cli_init_text_mode_shows_both_tiers(tmp_path: Path):
    fake_ws, wiki_data, agents_dir, claude_dir = _make_init_inputs(tmp_path)
    runner = CliRunner()
    r = runner.invoke(
        main,
        [
            "--no-json",
            "init",
            "--wiki-system-root",
            str(fake_ws),
            "--wiki-data-root",
            str(wiki_data),
            "--agents-dir",
            str(agents_dir),
            "--claude-dir",
            str(claude_dir),
        ],
    )
    assert r.exit_code == 0, (r.stdout, r.stderr)
    assert "Rendered" in r.stdout
    assert "canonical" in r.stdout
    assert "symlink" in r.stdout
    assert "permissions" in r.stdout
    assert "Read(" in r.stdout
