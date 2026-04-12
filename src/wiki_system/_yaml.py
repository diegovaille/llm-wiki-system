"""Shared YAML setup for wiki-system.

We use ruamel.yaml in round-trip mode because:
- staged envelopes embed markdown bodies as block scalars (`|`)
- tests assert parse->serialize->parse byte-identical round-trip
- pydantic serialization output is fed through this module's dumper
"""
from __future__ import annotations

import io
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import LiteralScalarString


def _build_yaml() -> YAML:
    y = YAML(typ="rt")
    y.default_flow_style = False
    y.indent(mapping=2, sequence=4, offset=2)
    y.width = 10_000  # effectively disable line wrapping for block scalars
    y.preserve_quotes = True
    return y


_YAML = _build_yaml()


def dumps(data: Any) -> str:
    """Serialize a Python object to YAML. Multiline strings become block scalars."""
    prepared = _prepare_for_dump(data)
    buf = io.StringIO()
    _YAML.dump(prepared, buf)
    return buf.getvalue()


def loads(text: str) -> Any:
    """Parse a YAML document into a plain Python object."""
    return _YAML.load(text)


def _prepare_for_dump(obj: Any) -> Any:
    """Recursively convert multiline strings to LiteralScalarString for block-scalar output."""
    if isinstance(obj, str):
        if "\n" in obj:
            return LiteralScalarString(obj)
        return obj
    if isinstance(obj, dict):
        return {k: _prepare_for_dump(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_prepare_for_dump(v) for v in obj]
    return obj
