import json
from pathlib import Path

import pytest

from wiki_system.doctor import Identifier, GraphSymbols, extract_identifiers, load_graph_symbols


def test_extracts_py_paths_functions_and_classes():
    body = (
        "The factory lives in `app/core/db.py` and is returned by\n"
        "`get_session_factory()`. `RedisCacheBackend` wraps it.\n"
    )
    ids = extract_identifiers(body)
    assert Identifier("app/core/db.py", "path") in ids
    assert Identifier("get_session_factory()", "function") in ids
    assert Identifier("RedisCacheBackend", "class") in ids


def test_ignores_non_code_spans():
    body = (
        "Run `make test` with `DISABLE_BOOT_CHECKS=1`; see `docs/DESIGN.md`,\n"
        "`https://example.com`, `wiki query demo`, and `pool_timeout=10`.\n"
    )
    assert extract_identifiers(body) == []


def test_method_spans_and_dedup():
    body = "`.stream_message()` then `stream_message()` and again `stream_message()`."
    ids = extract_identifiers(body)
    # leading-dot method form normalizes to the bare function form; dedup keeps one
    assert ids == [Identifier("stream_message()", "function")]


def test_fenced_code_blocks_are_skipped():
    body = "```bash\nrm -rf app/core/db.py\n```\nBut `app/core/db.py` counts."
    ids = extract_identifiers(body)
    assert ids == [Identifier("app/core/db.py", "path")]


def test_acronym_and_single_hump_class_names():
    # Real graph labels the narrow two-hump regex missed: LLMProvider,
    # AIService, SESEmailService, UUIDObfuscator, Settings, Chat.
    body = (
        "`LLMProvider` and `AIService` and `SESEmailService` and\n"
        "`UUIDObfuscator` and `Settings` and `Chat`; but not `True`,\n"
        "`False`, or `None`.\n"
    )
    ids = extract_identifiers(body)
    names = {i.text for i in ids}
    assert names == {
        "LLMProvider", "AIService", "SESEmailService",
        "UUIDObfuscator", "Settings", "Chat",
    }
    assert all(i.kind == "class" for i in ids)


def _write_graph(tmp_path: Path, nodes: list[dict]) -> Path:
    p = tmp_path / "graph.json"
    p.write_text(json.dumps({"nodes": nodes, "links": []}))
    return p


def test_loads_files_and_normalized_symbols(tmp_path):
    p = _write_graph(tmp_path, [
        {"label": "db.py", "norm_label": "db.py", "source_file": "app/core/db.py"},
        {"label": "get_session_factory()", "norm_label": "get_session_factory()",
         "source_file": "app/core/db.py"},
        {"label": "RedisCacheBackend", "norm_label": "rediscachebackend",
         "source_file": "app/core/cache/backends.py"},
    ])
    g = load_graph_symbols(p)
    assert g.node_count == 3
    assert "app/core/db.py" in g.files
    assert "get_session_factory" in g.symbols
    assert "rediscachebackend" in g.symbols


def test_missing_graph_raises_filenotfound(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_graph_symbols(tmp_path / "absent.json")


def test_graph_without_nodes_key_raises_valueerror(tmp_path):
    p = tmp_path / "graph.json"
    p.write_text(json.dumps({"foo": []}))
    with pytest.raises(ValueError):
        load_graph_symbols(p)


def test_raw_extraction_graph_with_edges_key(tmp_path):
    # `graphify extract --no-cluster` writes {"nodes": [...], "edges": [...]};
    # clustered graphs use "links". The loader only reads nodes, so both
    # shapes must load — this pins that contract.
    p = tmp_path / "graph.json"
    p.write_text(json.dumps({
        "nodes": [{"label": "db.py", "source_file": "app/core/db.py"}],
        "edges": [{"source": "a", "target": "b", "relation": "imports_from"}],
    }))
    g = load_graph_symbols(p)
    assert g.node_count == 1
    assert "app/core/db.py" in g.files
