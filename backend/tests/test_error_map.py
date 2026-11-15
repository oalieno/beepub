"""The frontend translates an error by its English sentence.

``frontend/src/lib/api/client.ts`` maps the ``detail`` of a failed
request to a message in the reader's language, keyed by the exact
sentence the backend sends. Reword the sentence here and the
translation is silently lost: the reader sees English again and nothing
fails. This test is what fails instead.
"""

import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CLIENT = REPO / "frontend" / "src" / "lib" / "api" / "client.ts"


def _translated_details() -> list[str]:
    source = CLIENT.read_text()
    start = source.index("const ERROR_MAP")
    table = source[start : source.index("\n};", start)]
    return re.findall(r'^\s*"([^"\\]*)"\s*:', table, re.M)


def _backend_strings() -> set[str]:
    strings: set[str] = set()
    for path in (REPO / "backend" / "app").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                strings.add(node.value)
    return strings


@pytest.mark.skipif(not CLIENT.exists(), reason="frontend sources not present")
def test_every_translated_error_is_still_said_by_the_backend():
    details = _translated_details()
    assert len(details) > 30, "ERROR_MAP was not read — has its shape changed?"
    said = _backend_strings()
    gone = [d for d in details if d not in said]
    assert not gone, (
        "client.ts translates sentences the backend no longer sends "
        f"(reworded or removed?): {gone}"
    )
