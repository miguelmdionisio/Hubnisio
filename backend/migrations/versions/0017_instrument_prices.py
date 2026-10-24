"""Prices and value over time (ADR-0008, slice T3): instruments' daily prices, global like
`fx_rates`, and each instrument's symbol at the price source. In `analytics` (ADR-0006), what
net worth now loads for an investment account: its latest portfolio snapshot and holdings, its
fills, and the prices of the instruments the member's visible accounts have traded or held.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# analytics.accounts as 0011 made it; this revision adds is_investment at the end.
_ACCOUNTS = """
        SELECT a.id,
               coalesce(
                   nullif(a.display_name, ''),
                   nullif(a.product, ''),
                   concat_ws(' ', a.institution_name, a.currency,
                       CASE a.cash_account_type
                           WHEN 'SVGS' THEN 'savings'
                           WHEN 'CARD' THEN 'card'
                           WHEN 'LOAN' THEN 'loan'
                       END)
               ) AS name,
               a.institution_name AS institution,
               a.currency,
               a.cash_account_type AS account_type,
               a.visibility::text AS visibility,
               v.is_owner,
               a.is_pot,
               a.pot_category_id,
               a.include_in_net_worth,
               NOT v.listed AS hidden{extra}
        FROM finance.accounts a
        JOIN analytics.visible_accounts v ON v.account_id = a.id
"""
_ACCOUNTS_COMMENT = (
    "Visible accounts, hidden ones included (their history still counts). A shared pot "
    "(is_pot) is left out of the personal view, where money moved into it is spending in "
    "pot_category_id."
)
_ACCOUNTS_COMMENT_T3 = (
    f"{_ACCOUNTS_COMMENT} An investment account (is_investment) is valued from its portfolio, "
    "not a bank balance."
)

# The latest portfolio snapshot of each visible account that isn't hidden.
_LATEST = """
        SELECT DISTINCT ON (s.account_id) s.*
        FROM finance.portfolio_snapshots s
        JOIN analytics.visible_accounts v ON v.account_id = s.account_id AND v.listed
        ORDER BY s.account_id, s.fetched_at DESC, s.id DESC
"""

# Each new view with its comment, in creation order (each may read the ones before it).
VIEWS: list[tuple[str, str, str]] = [
    (
        "portfolios",
        "The latest portfolio snapshot of each visible investment account that isn't hidden, "
        "in the account's currency, as of the sync that read it (as_of). cash is available to "
        "trade; with cash_in_pies and cash_reserved (for orders) it's the account's cash. "
        "total_value is the broker's own: cash plus holdings at market value.",
        f"""
        SELECT s.account_id, s.fetched_at AS as_of, s.currency, s.total_value,
               s.cash, s.cash_in_pies, s.cash_reserved, s.investments_value,
               s.investments_cost, s.realised_result, s.unrealised_result
        FROM ({_LATEST}) s
        """,  # noqa: S608 (constants only)
    ),
    (
        "holdings",
        "The holdings in each portfolio (analytics.portfolios). Quantities in shares; prices "
        "per share in the instrument's currency; value, cost and results in currency, the "
        "account's.",
        f"""
        SELECT h.account_id, h.instrument_id, h.quantity, h.quantity_in_pies,
               h.average_price, h.current_price, h.currency, h.value, h.cost,
               h.unrealised_result, h.fx_impact, h.opened_at
        FROM finance.holding_snapshots h
        JOIN ({_LATEST}) s ON s.id = h.portfolio_snapshot_id
        """,  # noqa: S608 (constants only)
    ),
    (
        "fills",
        "Order fills on visible accounts (hidden ones too): trades, and corporate actions such "
        "as splits (fill_type). Never transactions: a buy moves cash into a holding. quantity "
        "comes negative on a sell, net_value positive both ways (the cash the fill moved, fees "
        "included), so side gives the direction. price is per share in the instrument's "
        "currency; net_value and realised_result are in currency, the account's; fx_rate is "
        "instrument currency per account currency. taxes: [{name, amount, currency}].",
        """
        SELECT f.id, f.account_id, f.instrument_id, f.side, f.fill_type, f.order_type,
               f.initiated_from, f.filled_at, f.quantity, f.price, f.currency, f.fx_rate,
               f.net_value, f.realised_result, f.taxes
        FROM finance.fills f
        JOIN analytics.visible_accounts v ON v.account_id = f.account_id
        """,
    ),
    (
        "instruments",
        "The instruments the member's visible accounts have traded or held. currency is its "
        "prices' (GBX is pence: a hundredth of GBP).",
        """
        SELECT i.id, i.ticker, i.isin, i.name, i.currency, i.type
        FROM finance.instruments i
        WHERE EXISTS (
            SELECT FROM finance.fills f
            JOIN analytics.visible_accounts v ON v.account_id = f.account_id
            WHERE f.instrument_id = i.id
        ) OR EXISTS (
            SELECT FROM finance.holding_snapshots h
            JOIN analytics.visible_accounts v ON v.account_id = h.account_id
            WHERE h.instrument_id = i.id
        )
        """,
    ),
    (
        "instrument_prices",
        "Those instruments' prices per share on each day, in their currency. A holding on a "
        "day is valued at the latest price on or before it, at most 10 days old; without one "
        "it's left out of that day. source: yahoo (the day's close), trading212 (the price "
        "at a sync) or fill (a trade's price).",
        """
        SELECT p.instrument_id, p.on AS price_date, p.price, p.source::text AS source
        FROM finance.instrument_prices p
        JOIN analytics.instruments i ON i.id = p.instrument_id
        """,
    ),
]


def _comment(name: str, comment: str) -> None:
    op.execute(f"COMMENT ON VIEW analytics.{name} IS '{comment.replace("'", "''")}'")


def upgrade() -> None:
    postgresql.ENUM("yahoo", "trading212", "fill", name="price_source", schema="finance").create(
        op.get_bind()
    )
    op.create_table(
        "instrument_prices",
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("on", sa.Date(), nullable=False),
        sa.Column("price", sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column(
            "source",
            postgresql.ENUM(name="price_source", schema="finance", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("price > 0", name=op.f("ck_instrument_prices_price_positive")),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["finance.instruments.id"],
            name=op.f("fk_instrument_prices_instrument_id_instruments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("instrument_id", "on", name=op.f("pk_instrument_prices")),
        schema="finance",
    )
    op.add_column(
        "instruments",
        sa.Column("price_symbol", sa.String(length=32), nullable=True),
        schema="finance",
    )
    op.add_column(
        "instruments",
        sa.Column(
            "price_symbol_by_hand", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        schema="finance",
    )

    # Adding a column at the end keeps the view's grant.
    op.execute(
        "CREATE OR REPLACE VIEW analytics.accounts WITH (security_barrier) AS "
        + _ACCOUNTS.format(extra=",\n               a.is_investment")
    )
    _comment("accounts", _ACCOUNTS_COMMENT_T3)
    for name, comment, query in VIEWS:
        op.execute(f"CREATE VIEW analytics.{name} WITH (security_barrier) AS {query}")
        _comment(name, comment)
        op.execute(f"GRANT SELECT ON analytics.{name} TO hub_ai")


def downgrade() -> None:
    for name, _, _ in reversed(VIEWS):
        op.execute(f"DROP VIEW analytics.{name}")
    # A column can't be dropped from a view in place; nothing else reads this one.
    op.execute("DROP VIEW analytics.accounts")
    op.execute(
        "CREATE VIEW analytics.accounts WITH (security_barrier) AS " + _ACCOUNTS.format(extra="")
    )
    _comment("accounts", _ACCOUNTS_COMMENT)
    op.execute("GRANT SELECT ON analytics.accounts TO hub_ai")

    op.drop_column("instruments", "price_symbol_by_hand", schema="finance")
    op.drop_column("instruments", "price_symbol", schema="finance")
    op.drop_table("instrument_prices", schema="finance")
    op.execute("DROP TYPE finance.price_source")
