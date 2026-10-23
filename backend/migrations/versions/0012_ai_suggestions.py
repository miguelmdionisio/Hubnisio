"""AI category suggestions (ADR-0006): `analytics.suggest_category`, the AI logins' only write.

It's `SECURITY DEFINER`, so it writes as the migration's owner, and it decides who is asking
from `session_user`, as the views do. It writes only a category with source `ai`, the lowest
precedence, on transactions the member may see, and fails in a read-only transaction, so
`query_sql` can't call it.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-23
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SUGGEST_CATEGORY = """
CREATE FUNCTION analytics.suggest_category(
    transaction_ids uuid[], category_id uuid, OUT written integer, OUT skipped integer
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    member record;
    accepted uuid[];
BEGIN
    IF current_setting('transaction_read_only')::boolean THEN
        RAISE EXCEPTION 'suggest_category can''t run in a read-only transaction'
            USING ERRCODE = 'read_only_sql_transaction';
    END IF;
    SELECT me.user_id, me.household_id INTO member FROM analytics.me;
    IF NOT FOUND THEN
        RAISE EXCEPTION '% is not an AI login', session_user
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF NOT EXISTS (
        SELECT FROM analytics.categories c
        WHERE c.id = suggest_category.category_id AND c.archived_at IS NULL
    ) THEN
        RAISE EXCEPTION 'No category % to suggest: it isn''t the household''s, or it''s archived',
            suggest_category.category_id
            USING ERRCODE = 'invalid_parameter_value';
    END IF;

    -- What the member may see (the view is scoping.py's twin), booked and not a transfer, with
    -- no category from the user, a rule or a merchant's default.
    SELECT coalesce(array_agg(DISTINCT t.id), '{}') INTO accepted
    FROM analytics.transactions t
    WHERE t.id = ANY(suggest_category.transaction_ids)
      AND t.status = 'booked'
      AND t.kind <> 'transfer'
      AND NOT EXISTS (
          SELECT FROM finance.category_assignments ca
          WHERE ca.transaction_id = t.id AND ca.source <> 'ai'
      );

    DELETE FROM finance.category_assignments ca
    WHERE ca.transaction_id = ANY(accepted) AND ca.source = 'ai';
    INSERT INTO finance.category_assignments (id, household_id, transaction_id, category_id, source)
    SELECT uuidv7(), member.household_id, accepted_id, suggest_category.category_id, 'ai'
    FROM unnest(accepted) AS accepted_id;

    written := cardinality(accepted);
    skipped := (SELECT count(DISTINCT asked) FROM unnest(suggest_category.transaction_ids) asked)
        - written;
END
$$
"""
SIGNATURE = "analytics.suggest_category(uuid[], uuid)"


def upgrade() -> None:
    op.execute(SUGGEST_CATEGORY)
    op.execute(
        f"COMMENT ON FUNCTION {SIGNATURE} IS 'Suggests a category for transactions, with source "
        "ai: only booked ones the member may see that aren''t transfers and have no category "
        "from the user, a rule or a merchant''s default. Replaces an earlier ai suggestion. "
        "skipped: the rest.'"
    )
    op.execute(f"REVOKE ALL ON FUNCTION {SIGNATURE} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {SIGNATURE} TO hub_ai")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION {SIGNATURE}")
