import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from tests.test_cli import _setup_config
from wiki_system.cli import main
from wiki_system.doctor import Identifier, GraphSymbols, extract_identifiers, load_graph_symbols, run_doctor
from wiki_system.index import build_index, save_index


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


PAGE = """---
id: session-factory
title: Session Factory
summary: How sessions are made.
type: pattern
project: demo
domains: [db]
status: active
aliases: []
sources: ["session:2026-07-08-x"]
related: []
updated_at: 2026-07-08
confidence: high
---
Factory in `app/core/db.py`, via `get_session_factory()`.
Gone: `app/core/removed.py` and `vanished_helper()` and `GhostClass`.
"""


def _prepare(wiki_root, tmp_path):
    (wiki_root / "demo" / "pages" / "session-factory.md").write_text(PAGE)
    idx = build_index(wiki_root, "demo")
    save_index(wiki_root, "demo", idx)
    graph = tmp_path / "graph.json"
    graph.write_text(json.dumps({"nodes": [
        {"label": "db.py", "source_file": "app/core/db.py"},
        {"label": "get_session_factory()", "norm_label": "get_session_factory()",
         "source_file": "app/core/db.py"},
    ], "links": []}))
    return graph


def test_doctor_reports_only_missing_identifiers(wiki_root, tmp_path):
    graph = _prepare(wiki_root, tmp_path)
    report = run_doctor(wiki_root, "demo", graph)
    assert report.pages_checked == 1
    missing = {(f.identifier, f.confidence) for f in report.findings}
    assert missing == {
        ("app/core/removed.py", "high"),
        ("vanished_helper()", "advisory"),
        ("GhostClass", "advisory"),
    }


def test_doctor_downgrades_paths_outside_graph_roots(wiki_root, tmp_path):
    graph = _prepare(wiki_root, tmp_path)
    page = PAGE.replace(
        "Gone: `app/core/removed.py` and `vanished_helper()` and `GhostClass`.",
        "Gone: `app/core/removed.py`, `tests/unit/test_x.py`, "
        "`scripts/seed_data.py`, `seed_data.py`.",
    )
    (wiki_root / "demo" / "pages" / "session-factory.md").write_text(page)
    idx = build_index(wiki_root, "demo")
    save_index(wiki_root, "demo", idx)
    report = run_doctor(wiki_root, "demo", graph)
    conf = {f.identifier: f.confidence for f in report.findings if f.kind == "path"}
    assert conf == {
        "app/core/removed.py": "high",       # under a covered root -> real staleness signal
        "tests/unit/test_x.py": "advisory",  # ungraphed tree
        "scripts/seed_data.py": "advisory",  # ungraphed tree
        "seed_data.py": "advisory",          # bare filename, ambiguous
    }


def test_doctor_path_suffix_matching(wiki_root, tmp_path):
    graph = _prepare(wiki_root, tmp_path)
    page = PAGE.replace("app/core/db.py", "api/backend/app/core/db.py")
    (wiki_root / "demo" / "pages" / "session-factory.md").write_text(page)
    idx = build_index(wiki_root, "demo")
    save_index(wiki_root, "demo", idx)
    report = run_doctor(wiki_root, "demo", graph)
    assert "api/backend/app/core/db.py" not in {f.identifier for f in report.findings}


# ---------- CLI tests ----------


def _cli(wiki_root, tmp_path, *args):
    cfg_path = _setup_config(tmp_path, wiki_root, tmp_path / "repo")
    # click 8.3 always separates stdout and stderr; no mix_stderr flag.
    return CliRunner().invoke(main, ["--config", str(cfg_path), *args])


def test_cli_doctor_exit_2_with_findings(wiki_root, tmp_path):
    graph = _prepare(wiki_root, tmp_path)
    res = _cli(wiki_root, tmp_path, "doctor", "demo", "--graph", str(graph))
    assert res.exit_code == 2, (res.stdout, res.stderr)
    payload = json.loads(res.stdout)
    assert payload["pages_checked"] == 1
    assert any(f["identifier"] == "app/core/removed.py" for f in payload["findings"])


def test_cli_doctor_exit_4_on_missing_graph(wiki_root, tmp_path):
    _prepare(wiki_root, tmp_path)
    res = _cli(wiki_root, tmp_path, "doctor", "demo", "--graph", str(tmp_path / "nope.json"))
    assert res.exit_code == 4, (res.stdout, res.stderr)
    assert "unavailable" in res.stderr


def test_cli_doctor_exit_0_when_clean(wiki_root, tmp_path):
    graph = _prepare(wiki_root, tmp_path)
    clean = "\n".join(l for l in PAGE.splitlines() if "Gone:" not in l) + "\n"
    (wiki_root / "demo" / "pages" / "session-factory.md").write_text(clean)
    idx = build_index(wiki_root, "demo")
    save_index(wiki_root, "demo", idx)
    res = _cli(wiki_root, tmp_path, "doctor", "demo", "--graph", str(graph))
    assert res.exit_code == 0, (res.stdout, res.stderr)
