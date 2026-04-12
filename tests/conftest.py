from pathlib import Path

import pytest


@pytest.fixture
def wiki_root(tmp_path: Path) -> Path:
    root = tmp_path / "wiki"
    (root / "demo" / "pages").mkdir(parents=True)
    (root / "demo" / "staging").mkdir(parents=True)
    (root / "demo" / "sources").mkdir(parents=True)
    (root / "demo" / "queries").mkdir(parents=True)
    (root / "demo" / "views").mkdir(parents=True)
    (root / "demo" / "meta").mkdir(parents=True)
    return root
