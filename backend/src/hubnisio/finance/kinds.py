"""A transaction's kind as SQL (ADR-0007): a transfer if it's in a transfer pair or overridden,
otherwise its override, otherwise its sign.

The expressions read `Transfer` and `TransactionAnnotation`, so the query must outer-join both
(see `transactions_api._query`).
"""

from typing import Any

from sqlalchemy import and_, not_, or_

from hubnisio.finance.models import (
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
    override = TransactionAnnotation.kind_override
    match kind:
        case TransactionKind.TRANSFER:
            return IS_TRANSFER
        case TransactionKind.INCOME:
            sign = and_(override.is_(None), Transaction.amount > 0)
        case _:
            sign = and_(override.is_(None), Transaction.amount <= 0)
    return and_(not_(IS_TRANSFER), or_(override.is_not_distinct_from(kind), sign))
