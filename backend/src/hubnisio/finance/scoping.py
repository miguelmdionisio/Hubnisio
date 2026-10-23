"""What a principal may see (ADR-0005). Every finance query that returns account data goes
through `visible_account_ids` or `listed_account_ids`.

- An account belongs to a household. `shared` accounts are visible to every member.
- `private` accounts are visible to their owners only.
- Transactions and balances inherit their account's visibility.
- A hidden account (ADR-0007, "Retiring an account") stays visible, so its past transactions
  keep counting in spending, budgets and the transactions list, but it isn't listed: account
  lists and filters, net worth and upcoming payments leave it out.
"""

import uuid

from sqlalchemy import Exists, Select, exists, or_, select
from sqlalchemy.orm import InstrumentedAttribute

from hubnisio.core.auth import Principal
from hubnisio.finance.models import Account, AccountOwner, AccountVisibility


def is_owner(
    principal: Principal, account_id: InstrumentedAttribute[uuid.UUID] | uuid.UUID
) -> Exists:
    """SQL condition: the principal owns the account (a column, or one account's ID)."""
    return exists().where(
        AccountOwner.account_id == account_id, AccountOwner.user_id == principal.user_id
    )


def visible_account_ids(principal: Principal) -> Select[uuid.UUID]:
    """The accounts whose data the principal may see, hidden ones included."""
    return select(Account.id).where(
        Account.household_id == principal.household_id,
        or_(Account.visibility == AccountVisibility.SHARED, is_owner(principal, Account.id)),
    )


def listed_account_ids(principal: Principal) -> Select[uuid.UUID]:
    """The visible accounts that aren't hidden: what's listed and counted as current."""
    return visible_account_ids(principal).where(Account.hidden_at.is_(None))
