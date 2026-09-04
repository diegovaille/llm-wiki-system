"""TOML config loading for wiki-system."""
from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

# All config models forbid unknown fields so that typos in wiki.config.toml
# surface as ValidationError rather than silently reverting to defaults.
_STRICT = ConfigDict(extra="forbid")


class WikiSection(BaseModel):
    model_config = _STRICT
    root: str


class AgentBackend(BaseModel):
    model_config = _STRICT
    runtime: str
    model_hint: str = "opus"


class DirectBackend(BaseModel):
    model_config = _STRICT
    provider: str = "anthropic"
    model: str = "claude-opus-4-6"
    api_key_env: str = "ANTHROPIC_API_KEY"


class ExecutionSection(BaseModel):
    model_config = _STRICT
    mode: str = "agent"
    agent: AgentBackend
    direct: DirectBackend | None = None


class ProjectConfig(BaseModel):
    model_config = _STRICT
    name: str
    repo_path: str
    source_globs: list[str] = Field(default_factory=list)
    # Canonical domain allowlist. Empty = any domain accepted (legacy mode).
    # When set, `wiki index` warns on pages tagged outside the list and
    # `wiki index --strict` fails, so captures can't invent new domains.
    domains: list[str] = Field(default_factory=list)


class RetrievalConfig(BaseModel):
    model_config = _STRICT
    field_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "title": 5.0,
            "aliases": 4.0,
            "domains": 3.0,
            "type": 2.0,
            "headings": 2.0,
            "body": 1.0,
            "sources": 1.0,
        }
    )
    curated_edge_weight: float = 3.0
    inferred_edge_weight: float = 1.0
    recency_tiebreaker_days: int = 30


class CaptureConfig(BaseModel):
    model_config = _STRICT
    bias_toward_noop: bool = True
    bias_toward_update: bool = True


class SyncConfig(BaseModel):
    model_config = _STRICT
    inline_threshold_bytes: int = 65536


class IndexConfig(BaseModel):
    model_config = _STRICT
    schema_warnings: str = "non-fatal"


class WikiConfig(BaseModel):
    model_config = _STRICT
    wiki: WikiSection
    execution: ExecutionSection
    projects: list[ProjectConfig] = Field(default_factory=list)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    capture: CaptureConfig = Field(default_factory=CaptureConfig)
    sync: SyncConfig = Field(default_factory=SyncConfig)
    index: IndexConfig = Field(default_factory=IndexConfig)

    def get_project(self, name: str) -> ProjectConfig:
        for p in self.projects:
            if p.name == name:
                return p
        raise KeyError(f"Project '{name}' not found in config")

    def wiki_root_path(self) -> Path:
        return Path(self.wiki.root).expanduser().resolve()

    def project_subtree(self, name: str) -> Path:
        return self.wiki_root_path() / name


def resolve_wiki_root(root: str, config_dir: Path) -> Path:
    """`[wiki] root` as an absolute path.

    A relative value — `"."` is the useful one — is taken from the directory
    that holds the config file, so a tracked config can travel with a clone
    instead of hardcoding one machine's checkout path. `~` and absolute paths
    are unchanged.
    """
    expanded = Path(root).expanduser()
    if expanded.is_absolute():
        return expanded.resolve()
    return (config_dir / expanded).resolve()


def load_config(path: Path) -> WikiConfig:
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    cfg = WikiConfig.model_validate(data)
    cfg.wiki.root = str(resolve_wiki_root(cfg.wiki.root, Path(path).resolve().parent))
    return cfg
