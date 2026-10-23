"""A transaction's kind as SQL (ADR-0007): a transfer if it's in a transfer pair or overridden,
otherwise its override, otherwise its category's kind, otherwise its sign.

The expressions read `Transfer` and `TransactionAnnotation`, and `kind_is` also `Category`, so
the query must outer-join them (see `transactions_api._query`).
"""

from typing import Any

from sqlalchemy import and_, not_, or_

from hubnisio.finance.models import (
    Category,
    CategoryKind,
    Transaction,
    TransactionAnnotation,
    TransactionKind,
    Transfer,
)

# NULL-safe: a transaction without an annotation or a transfer pair isn't a transfer.
IS_TRANSFER = or_(
    Transfer.id.is_not(None),
    TransactionAnnotation.kind_override.is_not_distinct_from(TransactionKind.TRANSFER),
)


def kind_is(kind: TransactionKind) -> Any:
    """Money in with an expense category is an expense (a repayment or refund lowers that
    category's spending); money out with an income category is income."""
    override = TransactionAnnotation.kind_override
    match kind:
        case TransactionKind.TRANSFER:
            return IS_TRANSFER
        case TransactionKind.INCOME:
            category_kind, sign = CategoryKind.INCOME, Transaction.amount > 0
        case _:
            category_kind, sign = CategoryKind.EXPENSE, Transaction.amount <= 0
    derived = and_(
        override.is_(None),
        or_(Category.kind == category_kind, and_(Category.id.is_(None), sign)),
    )
    return and_(not_(IS_TRANSFER), or_(override.is_not_distinct_from(kind), derived))
