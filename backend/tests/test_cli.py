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

    with psycopg.connect(migrated_database) as connection:
        groups, categories, rules = connection.execute(
            """
            SELECT count(*) FILTER (WHERE c.parent_id IS NULL),
                   count(*) FILTER (WHERE c.parent_id IS NOT NULL),
                   (SELECT count(*) FROM finance.rules r WHERE r.household_id = m.household_id)
            FROM core.users u
            JOIN core.household_members m ON m.user_id = u.id
            JOIN finance.categories c ON c.household_id = m.household_id
            WHERE u.email = %s
            GROUP BY m.household_id
            """,
            (email,),
        ).fetchone() or (0, 0, 0)
    assert (groups, categories, rules) == (11, 42, 6)  # the household starts with defaults


def test_renormalize_an_account_without_syncs(
    migrated_database: str, capsys: pytest.CaptureFixture[str]
) -> None:
    account_id = uuid.uuid4()

    assert main(["renormalize", "--account", str(account_id)]) == 0
    assert (
        f"Account {account_id}: replayed 0 syncs, 0 transactions, 0 removed."
        in capsys.readouterr().out
    )
