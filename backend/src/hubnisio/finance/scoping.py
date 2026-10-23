"""What a principal may see, and which accounts count in each view (ADR-0005). Every finance
query that returns account data goes through one of the sets here.

- An account belongs to a household. `shared` accounts are visible to every member.
- `private` accounts are visible to their owners only.
- Transactions and balances inherit their account's visibility.
- A hidden account (ADR-0007, "Retiring an account") stays visible, so its past transactions
  keep counting in spending, budgets and the transactions list, but it isn't listed: account
  lists and filters, net worth and upcoming payments leave it out.
- Two views (ADR-0005, "Shared pots"): "household" counts every visible account; "personal"
  (Mine) counts only the principal's own accounts that aren't shared pots. A pot's spending
  and balance aren't the principal's; what they move into it is (`insights.spending`).
"""

import uuid
from typing import Literal

from sqlalchemy import Exists, Select, exists, not_, or_, select
from sqlalchemy.orm import InstrumentedAttribute

from hubnisio.core.auth import Principal
from hubnisio.finance.models import Account, AccountOwner, AccountVisibility

View = Literal["personal", "household"]


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


def mine_account_ids(principal: Principal) -> Select[uuid.UUID]:
    """The principal's own accounts that aren't shared pots, hidden ones included: what the
    personal view counts."""
    return visible_account_ids(principal).where(
        is_owner(principal, Account.id), not_(Account.is_pot)
    )


def listed_mine_account_ids(principal: Principal) -> Select[uuid.UUID]:
    """The principal's own accounts that aren't pots or hidden: the personal net worth."""
    return mine_account_ids(principal).where(Account.hidden_at.is_(None))


def counted_account_ids(principal: Principal, view: View) -> Select[uuid.UUID]:
    """The accounts whose transactions count in `view`, hidden ones included."""
    return mine_account_ids(principal) if view == "personal" else visible_account_ids(principal)


def listed_counted_account_ids(principal: Principal, view: View) -> Select[uuid.UUID]:
    """The accounts whose balances count in `view`."""
    if view == "personal":
        return listed_mine_account_ids(principal)
    return listed_account_ids(principal)
