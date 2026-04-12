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


def test_body_with_yaml_document_separator_is_safe():
    """Regression test for the core purpose of the block-scalar strategy.

    A markdown body containing `---` (thematic break or HR) must not corrupt
    the parent YAML document. It must serialize as a `|` block scalar and
    round-trip byte-identically.
    """
    data = {
        "state": "proposed",
        "canonical_page": {
            "frontmatter": {"id": "lv-story", "title": "Story"},
            "body": "# Story\n\nOpening paragraph.\n\n---\n\nSection after a thematic break.\n",
        },
    }
    first = dumps(data)
    # Body must be emitted as a block scalar
    assert "body: |" in first
    # Round-trip must be byte-identical
    second = dumps(loads(first))
    assert first == second
    # And the original body content (including the `---`) must be recoverable
    parsed = loads(first)
    assert "---" in parsed["canonical_page"]["body"]
