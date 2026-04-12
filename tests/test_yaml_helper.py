from wiki_system._yaml import dumps, loads


def test_multiline_becomes_block_scalar():
    data = {"body": "line one\nline two\nline three"}
    out = dumps(data)
    assert "body: |" in out
    assert "line one" in out


def test_round_trip_preserves_content():
    data = {
        "state": "proposed",
        "canonical_page": {
            "frontmatter": {"id": "foo", "title": "Foo"},
            "body": "# Foo\n\nSome paragraph.\n",
        },
    }
    text = dumps(data)
    parsed = loads(text)
    assert parsed["state"] == "proposed"
    assert parsed["canonical_page"]["frontmatter"]["id"] == "foo"
    assert "# Foo" in parsed["canonical_page"]["body"]


def test_round_trip_byte_identical_after_one_cycle():
    data = {
        "state": "proposed",
        "canonical_page": {
            "frontmatter": {"id": "foo", "title": "Foo", "type": "system"},
            "body": "# Foo\n\nBody here.\n",
        },
    }
    first = dumps(data)
    second = dumps(loads(first))
    assert first == second
