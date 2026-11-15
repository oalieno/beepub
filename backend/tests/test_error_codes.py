"""The backend's error codes, held against the frontend's translations.

A failed request names itself by a code (``app/errors.py``) and the
frontend picks the reader's-language message by it
(``frontend/src/lib/api/errors.ts``). A code only one side knows is a
reader seeing English: nothing else fails, so this does.
"""

import ast
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import errors

REPO = Path(__file__).resolve().parents[2]
MESSAGES = REPO / "frontend" / "src" / "lib" / "api" / "errors.ts"


def _catalogue() -> list[errors.Problem]:
    return [v for v in vars(errors).values() if isinstance(v, errors.Problem)]


def _translated_codes() -> set[str]:
    source = MESSAGES.read_text()
    start = source.index("const MESSAGES")
    table = source[start : source.index("\n};", start)]
    return set(re.findall(r"^\s*(\w+):\s*\(\)\s*=>", table, re.M))


def test_each_code_is_listed_once():
    codes = [p.code for p in _catalogue()]
    assert len(codes) > 30
    assert len(codes) == len(set(codes))
    for name, value in vars(errors).items():
        if isinstance(value, errors.Problem):
            assert name == value.code.upper()


@pytest.mark.skipif(not MESSAGES.exists(), reason="frontend sources not present")
def test_backend_and_frontend_know_the_same_codes():
    ours = {p.code for p in _catalogue()}
    theirs = _translated_codes()
    assert ours - theirs == set(), "codes the frontend has no message for"
    assert theirs - ours == set(), "messages for codes the backend never sends"


def test_a_translated_sentence_is_not_raised_bare():
    """A sentence in the catalogue raised as a plain ``HTTPException``
    would reach the reader untranslated."""
    sentences = {p.detail for p in _catalogue()}
    bare = []
    for path in (REPO / "backend" / "app").rglob("*.py"):
        if path.name == "errors.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                value = keyword.value
                if (
                    keyword.arg == "detail"
                    and isinstance(value, ast.Constant)
                    and value.value in sentences
                ):
                    bare.append(f"{path.name}:{node.lineno} {value.value!r}")
    assert not bare, bare


def test_the_response_carries_the_code_beside_the_sentence():
    app = FastAPI()
    app.add_exception_handler(errors.ApiError, errors.api_error_handler)

    @app.get("/default")
    def default():
        raise errors.BOOK_NOT_FOUND()

    @app.get("/overridden")
    def overridden():
        raise errors.USERNAME_EXISTS(status_code=400, headers={"X-Why": "taken"})

    client = TestClient(app)
    resp = client.get("/default")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Book not found", "code": "book_not_found"}
    resp = client.get("/overridden")
    assert resp.status_code == 400
    assert resp.json()["code"] == "username_exists"
    assert resp.headers["x-why"] == "taken"
