from wiki_system.doctor import Identifier, extract_identifiers


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
