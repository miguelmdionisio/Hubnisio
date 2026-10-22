import uuid

import psycopg
import pytest

from hubnisio.cli import main


def test_bootstrap_creates_owner_once(
    migrated_database: str, capsys: pytest.CaptureFixture[str]
) -> None:
    email = f"owner-{uuid.uuid4().hex[:8]}@example.com"
    args = ["bootstrap", "--email", email, "--name", "Owner", "--household", "Casa"]

    assert main(args) == 0
    assert main(args) == 1
    assert "already exists" in capsys.readouterr().err

    with psycopg.connect(migrated_database) as connection:
        rows = connection.execute(
            """
            SELECT u.display_name, h.name, m.role::text
            FROM core.users u
            JOIN core.household_members m ON m.user_id = u.id
            JOIN core.households h ON h.id = m.household_id
            WHERE u.email = %s
            """,
            (email,),
        ).fetchall()
    assert rows == [("Owner", "Casa", "owner")]
