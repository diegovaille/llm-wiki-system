from pathlib import Path

import pytest


@pytest.fixture
def wiki_root(tmp_path: Path) -> Path:
    root = tmp_path / "wiki"
    (root / "luminavine" / "pages").mkdir(parents=True)
    (root / "luminavine" / "staging").mkdir(parents=True)
    (root / "luminavine" / "sources").mkdir(parents=True)
    (root / "luminavine" / "queries").mkdir(parents=True)
    (root / "luminavine" / "views").mkdir(parents=True)
    (root / "luminavine" / "meta").mkdir(parents=True)
    return root
