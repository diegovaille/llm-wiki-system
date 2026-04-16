from pathlib import Path

import pytest

from wiki_system.config import WikiConfig, load_config


def test_load_minimal_config(tmp_path: Path):
    cfg_path = tmp_path / "wiki.config.toml"
    cfg_path.write_text(
        """
[wiki]
root = "~/Git/wiki"

[execution]
mode = "agent"

[execution.agent]
runtime = "claude-code"
model_hint = "opus"

[[projects]]
name = "demo"
repo_path = "~/Git/demo"
source_globs = ["docs/**/*.md"]
"""
    )
    cfg = load_config(cfg_path)
    assert isinstance(cfg, WikiConfig)
    assert cfg.wiki.root == "~/Git/wiki"
    assert cfg.execution.mode == "agent"
    assert cfg.execution.agent.runtime == "claude-code"
    assert len(cfg.projects) == 1
    assert cfg.projects[0].name == "demo"


def test_get_project_by_name(tmp_path: Path):
    cfg_path = tmp_path / "wiki.config.toml"
    cfg_path.write_text(
        """
[wiki]
root = "~/Git/wiki"
[execution]
mode = "agent"
[execution.agent]
runtime = "claude-code"
model_hint = "opus"
[[projects]]
name = "demo"
repo_path = "~/Git/demo"
source_globs = ["docs/**/*.md"]
[[projects]]
name = "other-project"
repo_path = "~/Git/other-project"
source_globs = ["docs/**/*.md"]
"""
    )
    cfg = load_config(cfg_path)
    p = cfg.get_project("other-project")
    assert p.name == "other-project"
    with pytest.raises(KeyError):
        cfg.get_project("nonexistent")


def test_default_retrieval_weights(tmp_path: Path):
    cfg_path = tmp_path / "wiki.config.toml"
    cfg_path.write_text(
        """
[wiki]
root = "~/Git/wiki"
[execution]
mode = "agent"
[execution.agent]
runtime = "claude-code"
model_hint = "opus"
[[projects]]
name = "demo"
repo_path = "/tmp/x"
source_globs = []
"""
    )
    cfg = load_config(cfg_path)
    assert cfg.retrieval.field_weights["title"] == 5.0
    assert cfg.retrieval.curated_edge_weight == 3.0
    assert cfg.retrieval.inferred_edge_weight == 1.0
    assert cfg.sync.inline_threshold_bytes == 65536


def test_unknown_field_rejected(tmp_path: Path):
    cfg_path = tmp_path / "wiki.config.toml"
    cfg_path.write_text(
        """
[wiki]
root = "~/Git/wiki"
unknown_field = "should be rejected"

[execution]
mode = "agent"
[execution.agent]
runtime = "claude-code"
model_hint = "opus"

[[projects]]
name = "demo"
repo_path = "/tmp/x"
source_globs = []
"""
    )
    from pydantic import ValidationError
    with pytest.raises(ValidationError, match="unknown_field"):
        load_config(cfg_path)
