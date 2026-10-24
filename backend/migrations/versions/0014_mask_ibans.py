"""IBANs masked in `analytics.transactions` (ADR-0006): the AI never sees an account number.

Banks write the other party's IBAN into some descriptions (BPI's SEPA transfers do), so the
view's description, bank counterparty and note show `[IBAN]` in its place: written compact or
in groups of four, in any case. Every tool and `query_sql` read the view, so none of them can
see or search for one. The view keeps its columns, so `CREATE OR REPLACE VIEW` keeps its grants.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-23
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Two letters, two check digits, then 11 to 30 letters or digits, compact or in groups of four.
IBAN = (
    r"\m[a-z]{2}[0-9]{2}"
    r"(?:[0-9a-z]{11,30}|(?: [0-9a-z]{4}){2,7}(?: [0-9a-z]{1,4})?)\M"
)
MASK = "[IBAN]"


def _masked(column: str) -> str:
    return f"regexp_replace({column}, '{IBAN}', '{MASK}', 'gi')"


# As migration 0011 made it, but for the three text columns.
TRANSACTIONS = """
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
       {description} AS description,
       {counterparty} AS bank_counterparty,
       ann.counterparty_id AS merchant_id,
       cp.name AS merchant,
       c.id AS category_id,
       c.name AS category,
       coalesce(c.parent_id, c.id) AS group_id,
       coalesce(g.name, c.name) AS group_name,
       ca.source::text AS category_source,
       coalesce(ann.tags, '{{}}') AS tags,
       coalesce(ann.rule_tags, '{{}}') AS rule_tags,
       {note} AS note,
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
LEFT JOIN LATERAL (
    SELECT r.rate FROM finance.fx_rates r
    WHERE r.quote_currency = t.currency AND r.on <= t.occurred_on AND r.on >= t.occurred_on - 10
    ORDER BY r.on DESC
    LIMIT 1
) fx ON true
"""
COMMENT = (
    "Transactions on visible accounts, booked and pending. amount is signed (negative = "
    "money out); eur_amount is null without an exchange rate for its day. kind: transfer, "
    "else the override, else the category's kind, else the sign, so money in with an "
    "expense category is a refund or repayment that lowers that category. in_mine: it "
    "counts in the personal view; pot_move: a move to or from a shared pot, which counts "
    "there as spending in the pot's category. transfer_account_id is null when that "
    "account isn't visible."
)
MASKED_COMMENT = f"{COMMENT} An IBAN in description, bank_counterparty or note shows as {MASK}."


def _replace(description: str, counterparty: str, note: str, comment: str) -> None:
    query = TRANSACTIONS.format(description=description, counterparty=counterparty, note=note)
    op.execute(f"CREATE OR REPLACE VIEW analytics.transactions WITH (security_barrier) AS {query}")
    op.execute(f"COMMENT ON VIEW analytics.transactions IS '{comment.replace("'", "''")}'")


def upgrade() -> None:
    _replace(
        _masked("t.description"),
        _masked("t.counterparty_name"),
        _masked("ann.note"),
        MASKED_COMMENT,
    )


def downgrade() -> None:
    _replace("t.description", "t.counterparty_name", "ann.note", COMMENT)
