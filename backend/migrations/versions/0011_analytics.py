"""AI access (ADR-0006): the `analytics` views, the `hub_ai` group role, per-member logins and
the audit of AI tool calls.

Every view finds the member through `session_user` and `core.ai_logins`, so a connection that
isn't a member's AI login sees nothing. The views are the SQL twins of finance/scoping.py,
finance/kinds.py and `monthly_sums`; tests/test_analytics.py checks that they agree.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# A currency's rate on a transaction's day: the latest within 10 days (finance/fx/convert.py).
_RATE = """
    LEFT JOIN LATERAL (
        SELECT r.rate FROM finance.fx_rates r
        WHERE r.quote_currency = t.currency AND r.on <= t.occurred_on AND r.on >= t.occurred_on - 10
        ORDER BY r.on DESC
        LIMIT 1
    ) fx ON true
"""

# Each view with its comment, in creation order (each may read the ones before it).
VIEWS: list[tuple[str, str, str]] = [
    (
        "me",
        "The member this login acts for, and their household.",
        """
        SELECT u.id AS user_id, m.household_id, u.display_name
        FROM core.ai_logins l
        JOIN core.users u ON u.id = l.user_id
        JOIN core.household_members m ON m.user_id = l.user_id
        WHERE l.role_name = session_user::text
        """,
    ),
    (
        "visible_accounts",
        "The accounts whose data the member may see: shared ones and their own private ones. "
        "in_mine: their own accounts that aren't shared pots (the personal view). listed: not "
        "hidden.",
        """
        SELECT a.id AS account_id,
               o.user_id IS NOT NULL AS is_owner,
               o.user_id IS NOT NULL AND NOT a.is_pot AS in_mine,
               a.hidden_at IS NULL AS listed
        FROM finance.accounts a
        JOIN analytics.me ON me.household_id = a.household_id
        LEFT JOIN finance.account_owners o ON o.account_id = a.id AND o.user_id = me.user_id
        WHERE a.visibility = 'shared' OR o.user_id IS NOT NULL
        """,
    ),
    (
        "accounts",
        "Visible accounts, hidden ones included (their history still counts). A shared pot "
        "(is_pot) is left out of the personal view, where money moved into it is spending in "
        "pot_category_id.",
        """
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
               NOT v.listed AS hidden
        FROM finance.accounts a
        JOIN analytics.visible_accounts v ON v.account_id = a.id
        """,
    ),
    (
        "transactions",
        "Transactions on visible accounts, booked and pending. amount is signed (negative = "
        "money out); eur_amount is null without an exchange rate for its day. kind: transfer, "
        "else the override, else the category's kind, else the sign, so money in with an "
        "expense category is a refund or repayment that lowers that category. in_mine: it "
        "counts in the personal view; pot_move: a move to or from a shared pot, which counts "
        "there as spending in the pot's category. transfer_account_id is null when that "
        "account isn't visible.",
        f"""
        SELECT t.id,
               t.account_id,
               t.status::text AS status,
               t.occurred_on,
               t.booking_date,
               t.value_date,
               t.amount,
               t.currency,
               t.original_amount,
               t.original_currency,
               CASE WHEN t.currency = 'EUR' THEN t.amount ELSE t.amount / fx.rate END
                   AS eur_amount,
               CASE
                   WHEN tr.id IS NOT NULL OR ann.kind_override = 'transfer' THEN 'transfer'
                   WHEN ann.kind_override IS NOT NULL THEN ann.kind_override::text
                   WHEN c.id IS NOT NULL THEN c.kind::text
                   WHEN t.amount > 0 THEN 'income'
                   ELSE 'expense'
               END AS kind,
               v.in_mine,
               pot.id IS NOT NULL AS pot_move,
               t.description,
               t.counterparty_name AS bank_counterparty,
               ann.counterparty_id AS merchant_id,
               cp.name AS merchant,
               c.id AS category_id,
               c.name AS category,
               coalesce(c.parent_id, c.id) AS group_id,
               coalesce(g.name, c.name) AS group_name,
               ca.source::text AS category_source,
               coalesce(ann.tags, '{{}}') AS tags,
               coalesce(ann.rule_tags, '{{}}') AS rule_tags,
               ann.note,
               ann.recurring_series_id,
               nullif(t.bank_transaction_code ->> 'code', '') AS bank_code,
               ov.account_id AS transfer_account_id
        FROM finance.transactions t
        JOIN analytics.visible_accounts v ON v.account_id = t.account_id
        LEFT JOIN finance.transaction_annotations ann ON ann.transaction_id = t.id
        LEFT JOIN finance.category_assignments ca ON ca.transaction_id = t.id
        LEFT JOIN finance.categories c ON c.id = ca.category_id
        LEFT JOIN finance.categories g ON g.id = c.parent_id
        LEFT JOIN finance.counterparties cp ON cp.id = ann.counterparty_id
        LEFT JOIN finance.transfers tr ON t.id IN (tr.outgoing_id, tr.incoming_id)
        LEFT JOIN finance.transactions other
            ON other.id IN (tr.outgoing_id, tr.incoming_id) AND other.id <> t.id
        LEFT JOIN analytics.visible_accounts ov ON ov.account_id = other.account_id
        LEFT JOIN finance.accounts pot ON pot.id = ov.account_id AND pot.is_pot
        {_RATE}
        """,  # noqa: S608 (constants only)
    ),
    (
        "monthly_category_spend",
        "Signed sums in euros per month and category, as the app computes spending, cash flow "
        "and budgets: booked transactions that aren't transfers. view: household (every "
        "visible account) or personal (the member's own accounts that aren't pots; a move to "
        "or from a pot counts in the pot's category). category_id is null for uncategorized, "
        "then kind is the override or the sign; otherwise it's the category's kind. "
        "unconverted: transactions left out for want of an exchange rate.",
        f"""
        WITH counted AS (
            SELECT 'household' AS view, t.amount, t.currency, t.occurred_on,
                   ca.category_id, ca.amount AS assigned, ann.kind_override
            FROM finance.transactions t
            JOIN analytics.visible_accounts v ON v.account_id = t.account_id
            LEFT JOIN finance.transfers tr ON t.id IN (tr.outgoing_id, tr.incoming_id)
            LEFT JOIN finance.transaction_annotations ann ON ann.transaction_id = t.id
            LEFT JOIN finance.category_assignments ca ON ca.transaction_id = t.id
            WHERE t.status = 'booked'
              AND tr.id IS NULL
              AND ann.kind_override IS DISTINCT FROM 'transfer'
            UNION ALL
            -- A move to or from a pot takes the pot's category and its own sign, whatever was
            -- decided about the transaction.
            SELECT 'personal', t.amount, t.currency, t.occurred_on,
                   coalesce(pot.pot_category_id, ca.category_id), ca.amount, ann.kind_override
            FROM finance.transactions t
            JOIN analytics.visible_accounts v ON v.account_id = t.account_id AND v.in_mine
            LEFT JOIN finance.transfers tr ON t.id IN (tr.outgoing_id, tr.incoming_id)
            LEFT JOIN finance.transactions other
                ON other.id IN (tr.outgoing_id, tr.incoming_id) AND other.id <> t.id
            LEFT JOIN analytics.visible_accounts ov ON ov.account_id = other.account_id
            LEFT JOIN finance.accounts pot ON pot.id = ov.account_id AND pot.is_pot
            LEFT JOIN finance.transaction_annotations ann
                ON ann.transaction_id = t.id AND pot.id IS NULL
            LEFT JOIN finance.category_assignments ca
                ON ca.transaction_id = t.id AND pot.id IS NULL
            WHERE t.status = 'booked'
              AND ((tr.id IS NULL AND ann.kind_override IS DISTINCT FROM 'transfer')
                   OR pot.id IS NOT NULL)
        ),
        converted AS (
            SELECT t.view,
                   date_trunc('month', t.occurred_on::timestamp)::date AS month,
                   t.category_id,
                   CASE
                       WHEN c.id IS NOT NULL THEN c.kind::text
                       WHEN t.kind_override IS NOT NULL THEN t.kind_override::text
                       WHEN t.amount > 0 THEN 'income'
                       ELSE 'expense'
                   END AS kind,
                   CASE
                       WHEN t.currency = 'EUR' THEN coalesce(t.assigned, t.amount)
                       ELSE coalesce(t.assigned, t.amount) / fx.rate
                   END AS eur
            FROM counted t
            LEFT JOIN finance.categories c ON c.id = t.category_id
            {_RATE}
        )
        SELECT view, month, category_id, kind,
               sum(eur) AS eur,
               count(*) AS transactions,
               count(*) FILTER (WHERE eur IS NULL) AS unconverted
        FROM converted
        GROUP BY view, month, category_id, kind
        """,  # noqa: S608 (constants only)
    ),
    (
        "categories",
        "The household's categories, archived ones too. Two levels: groups (parent_id null) "
        "and the categories in them; group_id is the group, or the category itself if it's one.",
        """
        SELECT c.id, c.name, c.kind::text AS kind, c.parent_id,
               coalesce(c.parent_id, c.id) AS group_id,
               coalesce(p.name, c.name) AS group_name,
               c.position, c.archived_at
        FROM finance.categories c
        JOIN analytics.me ON me.household_id = c.household_id
        LEFT JOIN finance.categories p ON p.id = c.parent_id
        WHERE c.user_id IS NULL OR c.user_id = me.user_id
        """,
    ),
    (
        "merchants",
        "The household's merchants (counterparties), with how many visible transactions each has.",
        """
        SELECT cp.id, cp.name, cp.default_category_id,
               (SELECT count(*)
                FROM finance.transaction_annotations a
                JOIN finance.transactions t ON t.id = a.transaction_id
                JOIN analytics.visible_accounts v ON v.account_id = t.account_id
                WHERE a.counterparty_id = cp.id) AS transactions
        FROM finance.counterparties cp
        JOIN analytics.me ON me.household_id = cp.household_id
        """,
    ),
    (
        "budgets",
        "Monthly budgets on an expense category or group; category_id is null for the overall "
        "budget, which counts all spending. The amounts are in budget_limits.",
        """
        SELECT b.id, b.category_id, b.rollover, b.overspend::text AS overspend
        FROM finance.budgets b
        JOIN analytics.me ON me.household_id = b.household_id
        WHERE b.category_id IS NULL OR b.category_id IN (SELECT id FROM analytics.categories)
        """,
    ),
    (
        "budget_limits",
        "A budget's amount in euros from starts_on's month until its next row.",
        """
        SELECT l.budget_id, l.starts_on, l.amount
        FROM finance.budget_limits l
        JOIN analytics.budgets b ON b.id = l.budget_id
        """,
    ),
    (
        "recurring_payments",
        "Recurring payments and income detected on visible accounts; only confirmed ones "
        "(review) count. Status is computed on read from cadence, next_expected_on and "
        "cancelled_on.",
        """
        SELECT s.id, s.account_id, s.counterparty_id AS merchant_id,
               coalesce(nullif(s.custom_name, ''), s.name) AS name,
               s.cadence::text AS cadence, s.kind::text AS kind,
               s.expected_amount, s.currency, s.amount_varies, s.occurrences,
               s.first_seen_on, s.last_seen_on, s.next_expected_on,
               s.previous_amount, s.amount_changed_on,
               s.review::text AS review, s.cancelled_on
        FROM finance.recurring_series s
        JOIN analytics.visible_accounts v ON v.account_id = s.account_id
        """,
    ),
    (
        "balances",
        "The latest bank-reported balance of each visible account that isn't hidden: balance "
        "is what the Accounts page shows (spendable first), booked_balance what net worth uses.",
        """
        WITH latest AS (
            SELECT s.account_id, s.balance_type, s.amount, s.currency, s.reference_date,
                   s.fetched_at
            FROM finance.balance_snapshots s
            JOIN analytics.visible_accounts v ON v.account_id = s.account_id AND v.listed
            WHERE s.fetched_at = (
                SELECT max(x.fetched_at) FROM finance.balance_snapshots x
                WHERE x.account_id = s.account_id
            )
        ),
        spendable AS (
            SELECT DISTINCT ON (account_id) * FROM latest
            ORDER BY account_id, coalesce(array_position(
                ARRAY['ITAV', 'CLAV', 'ITBD', 'CLBD', 'XPCD', 'OPAV', 'OPBD'],
                balance_type::text), 8)
        ),
        booked AS (
            SELECT DISTINCT ON (account_id) * FROM latest
            ORDER BY account_id, coalesce(array_position(
                ARRAY['CLBD', 'ITBD', 'XPCD', 'ITAV', 'CLAV', 'OPBD', 'OPAV'],
                balance_type::text), 8)
        )
        SELECT s.account_id,
               s.amount AS balance, s.balance_type, s.currency,
               b.amount AS booked_balance, b.balance_type AS booked_balance_type,
               b.currency AS booked_currency, b.reference_date, s.fetched_at
        FROM spendable s
        JOIN booked b ON b.account_id = s.account_id
        """,
    ),
]

RECORD_CALL = """
CREATE FUNCTION analytics.record_call(tool text, arguments jsonb, row_count integer)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM core.ai_logins l WHERE l.role_name = session_user::text) THEN
        RAISE EXCEPTION '% is not an AI login', session_user
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    INSERT INTO core.ai_calls (role_name, tool, arguments, row_count)
    VALUES (session_user, record_call.tool, coalesce(record_call.arguments, '{}'),
            record_call.row_count);
END
$$
"""
RECORD_CALL_SIGNATURE = "analytics.record_call(text, jsonb, integer)"


def upgrade() -> None:
    op.create_table(
        "ai_logins",
        sa.Column("role_name", sa.String(length=63), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["core.users.id"],
            name=op.f("fk_ai_logins_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("role_name", name=op.f("pk_ai_logins")),
        sa.UniqueConstraint("user_id", name=op.f("uq_ai_logins_user_id")),
        schema="core",
    )
    op.create_table(
        "ai_calls",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("role_name", sa.String(length=63), nullable=False),
        sa.Column("tool", sa.String(length=100), nullable=False),
        sa.Column("arguments", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_calls")),
        schema="core",
    )

    # Roles are cluster-wide, so the group may outlive a database (a test one, say).
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'hub_ai') THEN
                CREATE ROLE hub_ai NOLOGIN;
            END IF;
        END
        $$
        """
    )
    op.execute("CREATE SCHEMA analytics")
    for name, comment, query in VIEWS:
        op.execute(f"CREATE VIEW analytics.{name} WITH (security_barrier) AS {query}")
        op.execute(f"COMMENT ON VIEW analytics.{name} IS '{comment.replace("'", "''")}'")
    op.execute(RECORD_CALL)

    # Views run with their owner's rights, so the group needs nothing outside `analytics`.
    op.execute("GRANT USAGE ON SCHEMA analytics TO hub_ai")
    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA analytics TO hub_ai")
    op.execute(f"REVOKE ALL ON FUNCTION {RECORD_CALL_SIGNATURE} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {RECORD_CALL_SIGNATURE} TO hub_ai")


def downgrade() -> None:
    # The members' logins exist only for these views.
    op.execute(
        """
        DO $$
        DECLARE
            login record;
        BEGIN
            FOR login IN SELECT role_name FROM core.ai_logins LOOP
                EXECUTE format('DROP ROLE IF EXISTS %I', login.role_name);
            END LOOP;
        END
        $$
        """
    )
    op.execute(f"DROP FUNCTION {RECORD_CALL_SIGNATURE}")
    for name, _, _ in reversed(VIEWS):
        op.execute(f"DROP VIEW analytics.{name}")
    op.execute("DROP SCHEMA analytics")
    op.execute("DROP OWNED BY hub_ai")
    op.execute("DROP ROLE hub_ai")
    op.drop_table("ai_calls", schema="core")
    op.drop_table("ai_logins", schema="core")
