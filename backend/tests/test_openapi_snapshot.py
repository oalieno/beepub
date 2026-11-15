"""The API's description, as the frontend's types are generated from it.

``frontend/openapi.json`` is the OpenAPI schema FastAPI derives from the
routes and their response models; ``frontend/src/lib/api/schema.d.ts``
is generated from that file (``pnpm gen:api``), and the frontend's own
types are checked against it at compile time. So a field renamed here
shows up as a type error there, instead of as ``undefined`` on a page.

This test keeps the committed file true. When the API changes on
purpose, rewrite it and regenerate the types:

    UPDATE_OPENAPI=1 uv run pytest tests/test_openapi_snapshot.py
    (cd ../frontend && pnpm gen:api)
"""

import json
import os
from pathlib import Path

import pytest

from app.main import app

SNAPSHOT = Path(__file__).resolve().parents[2] / "frontend" / "openapi.json"


def _current() -> str:
    return (
        json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )


@pytest.mark.skipif(not SNAPSHOT.parent.exists(), reason="frontend sources not present")
def test_the_committed_api_description_is_current():
    current = _current()
    if os.environ.get("UPDATE_OPENAPI"):
        SNAPSHOT.write_text(current)
    assert SNAPSHOT.exists(), (
        "frontend/openapi.json is missing — see this file's docstring"
    )
    assert SNAPSHOT.read_text() == current, (
        "the API changed and frontend/openapi.json did not — see this file's "
        "docstring for the two commands"
    )
