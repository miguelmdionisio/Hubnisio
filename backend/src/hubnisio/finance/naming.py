"""How accounts are named in the hub."""

from hubnisio.finance.models import Account

# ISO 20022 cash account types, for default names (current accounts need no word).
ACCOUNT_TYPES = {"SVGS": "savings", "CARD": "card", "LOAN": "loan"}


def account_name(account: Account) -> str:
    """The name the user gave it, else the bank's label, else a default."""
    return account.display_name or account.product or default_name(account)


def default_name(account: Account) -> str:
    """When the bank gives an account no name: its IBAN's end, else its currency and type."""
    if account.iban:
        return f"{account.institution_name} ••{account.iban[-4:]}"
    kind = ACCOUNT_TYPES.get(account.cash_account_type or "", "")
    return " ".join(part for part in (account.institution_name, account.currency, kind) if part)
