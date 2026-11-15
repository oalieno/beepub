"""The models and the migrations describe the same database.

Nothing else checks this: a column added to a model without a migration
works in every test that builds its tables from the models and fails on
a real install; a migration without its model is a column the app never
writes. The suite's database is built by the migrations (conftest), so
comparing the models with it here catches both.

Indexes and unique constraints that only the migrations declare are not
part of the comparison (alembic/env.py, ``include_object``).
"""

import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]


def test_models_match_the_migrated_schema():
    # The CLI, not the API: backend/alembic/ shadows the package on
    # pytest's sys.path (see conftest).
    alembic = Path(sys.executable).parent / "alembic"
    result = subprocess.run(
        [str(alembic), "check"],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "models and migrations disagree — write the migration, or bring the "
        f"model in line with it:\n{result.stdout}\n{result.stderr[-3000:]}"
    )
