"""Net worth's inputs in `analytics` (ADR-0006): each visible account's daily movements, the
connections it comes through, and the exchange rates.

With `balances` (each account's anchor), they are what finance/insights/net_worth.py loads, so
the MCP server computes net worth with the app's own `compute_net_worth`;
tests/test_ai.py checks that they agree.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-23
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Each view with its comment, in creation order.
VIEWS: list[tuple[str, str, str]] = [
    (
        "daily_movements",
        "Per visible account and day, the sum of its booked transactions (hidden accounts "
        "too). A balance on another day is the bank's latest one (balances.booked_balance, as "
        "of its reference_date) moved by the movements in between.",
        """
        SELECT t.account_id, t.occurred_on, sum(t.amount) AS amount, count(*) AS transactions
        FROM finance.transactions t
        JOIN analytics.visible_accounts v ON v.account_id = t.account_id
        WHERE t.status = 'booked'
        GROUP BY t.account_id, t.occurred_on
        """,
    ),
    (
        "account_connections",
        "The bank connections (consents) each visible account comes through. A bank sends "
        "every account on a connection the same history, so an account's data starts with the "
        "earliest transaction of any account on its connection.",
        """
        SELECT DISTINCT p.account_id, p.connection_id
        FROM finance.provider_accounts p
        JOIN analytics.visible_accounts v ON v.account_id = p.account_id
        """,
    ),
    (
        "fx_rates",
        "Exchange rates: how many units of currency one euro bought on rate_date. A euro amount "
        "is the amount divided by the rate, using the latest rate on or before its day, at most "
        "10 days old; without one, it isn't converted.",
        """
        SELECT r.quote_currency AS currency, r.on AS rate_date, r.rate
        FROM finance.fx_rates r
        """,
    ),
]


def upgrade() -> None:
    for name, comment, query in VIEWS:
        op.execute(f"CREATE VIEW analytics.{name} WITH (security_barrier) AS {query}")
        op.execute(f"COMMENT ON VIEW analytics.{name} IS '{comment.replace("'", "''")}'")
        op.execute(f"GRANT SELECT ON analytics.{name} TO hub_ai")


def downgrade() -> None:
    for name, _, _ in reversed(VIEWS):
        op.execute(f"DROP VIEW analytics.{name}")
