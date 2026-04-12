"""v0.1 retrieval quality bar: top 3 must contain the right page for >= 8/10 queries.

This is an INTEGRATION test against live, hand-seeded wiki data at
~/Git/wiki/demo. It is excluded from the default test suite and must be
run explicitly:

    pytest -m integration tests/test_retrieval_bar.py -v

It is also skipped when the live config does not exist, so shared CI will never
accidentally execute it.
"""
from pathlib import Path

import pytest

from wiki_system.config import load_config
from wiki_system.query import run_query


LIVE_CONFIG = Path("~/Git/wiki/wiki.config.toml").expanduser()


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not LIVE_CONFIG.exists(),
        reason="live wiki config not seeded at ~/Git/wiki/wiki.config.toml",
    ),
]


# 10 known questions with the right canonical page
BENCHMARK = [
    ("how does the story pipeline work", "demo-story-pipeline"),
    ("how do I create a new story", "demo-story-creation-workflow"),
    ("how is character identity maintained", "demo-character-identity-pattern"),
    ("what are the stages of the generation pipeline", "demo-story-pipeline"),
    ("editor workflow for a new story", "demo-story-creation-workflow"),
    ("character consistency across scenes", "demo-character-identity-pattern"),
    ("what are editorial guardrails", "demo-editorial-guardrails"),
    ("theology review vs editorial review", "demo-story-creation-workflow"),
    ("illustration generation quality", "demo-character-identity-pattern"),
    ("publication approval flow", "demo-story-pipeline"),
]


def test_retrieval_bar_8_of_10():
    cfg = load_config(LIVE_CONFIG)
    wiki_root = cfg.wiki_root_path()
    hits = 0
    misses: list[tuple[str, list[str]]] = []
    for question, expected_id in BENCHMARK:
        results = run_query(wiki_root, "demo", question, cfg.retrieval, limit=3)
        ids = [r.id for r in results]
        if expected_id in ids:
            hits += 1
        else:
            misses.append((question, ids))
    assert hits >= 8, f"retrieval bar failed: {hits}/10 — misses: {misses}"
