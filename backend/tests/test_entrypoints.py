import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    "entrypoint", ["hubnisio.worker", "hubnisio.main", "hubnisio.cli", "hubnisio.ai.server"]
)
def test_each_entrypoint_resolves_every_table_on_its_own(entrypoint: str) -> None:
    """Each process loads only what its entrypoint imports; every foreign key must still resolve.
    The worker once loaded finance models without the core ones, and every sync failed."""
    code = f"import {entrypoint}; from hubnisio.core.db import Base; Base.metadata.sorted_tables"
    result = subprocess.run(  # noqa: S603  # our own interpreter and code
        [sys.executable, "-c", code],
        env={**os.environ, "HUBNISIO_DATABASE_URL": "postgresql://unused"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
