"""Request and response models of the finance API. Money is sent as decimal strings."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field

from hubnisio.finance.categorize.rules import Action, Condition
from hubnisio.finance.models import (
    AccountVisibility,
    Cadence,
    CategoryKind,
    ConnectionStatus,
    Overspend,
    ProviderName,
    RecurringStatus,
    Review,
    RuleMatch,
    Source,
    TransactionKind,
    TransactionStatus,
)


class Bank(BaseModel):
    name: str
    country: str
    logo: str | None
    beta: bool


class StartConnection(BaseModel):
    institution_name: str = Field(min_length=1, max_length=100)
    country: str = Field(pattern=r"^[A-Z]{2}$")


class StartedConnection(BaseModel):
    url: str  # send the browser here


class CompleteConnection(BaseModel):
    code: str = Field(min_length=1)
    state: str = Field(min_length=1)


class ConnectionOut(BaseModel):
    id: uuid.UUID
    provider: ProviderName
    institution_name: str
    institution_country: str | None  # null for Trading 212
    status: ConnectionStatus
    valid_until: datetime | None  # null when access doesn't expire (Trading 212's key)
    days_left: int | None  # days until the consent expires; warn from 14
    key_file: str | None  # Trading 212: the name of the API key's file
    last_synced_at: datetime | None
    syncing: bool
    last_error: str | None  # error code of the latest finished sync, if it failed
    account_ids: list[uuid.UUID]


class SyncQueued(BaseModel):
    queued: bool  # false when a sync was already waiting


class Balance(BaseModel):
    balance_type: str
    amount: Decimal
    currency: str
    fetched_at: datetime


class AccountOut(BaseModel):
    id: uuid.UUID
    name: str
    institution_name: str
    iban_masked: str | None
    currency: str
    cash_account_type: str | None
    visibility: AccountVisibility
    include_in_net_worth: bool
    is_owner: bool
    hidden_at: datetime | None
    is_pot: bool  # a shared pot: out of the Mine view (ADR-0005)
    pot_category_id: uuid.UUID | None  # where contributions to the pot count in Mine
    # A broker account: its balance is its value, type TVAL (ADR-0008).
    is_investment: bool
    transaction_count: int
    balance: Balance | None


class AccountUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=100)
    visibility: AccountVisibility | None = None
    include_in_net_worth: bool | None = None
    hidden: bool | None = None
    is_pot: bool | None = None
    pot_category_id: uuid.UUID | None = None  # an expense category; null clears it


class AccountDeleteBlocked(BaseModel):
    """Why a delete needs `confirm=true`: what would go with the account."""

    detail: str
    transaction_count: int
    transfer_count: int  # pairs with accounts that stay; their side stays a transfer


class TransactionCategory(BaseModel):
    id: uuid.UUID
    name: str
    group_name: str | None
    source: Source  # manual, rule, counterparty or ai


class TransactionCounterparty(BaseModel):
    id: uuid.UUID
    name: str
    source: Source | None


class TransactionTransfer(BaseModel):
    id: uuid.UUID
    other_transaction_id: uuid.UUID
    other_account_id: uuid.UUID
    other_account_name: str
    source: Source


class TransactionOut(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    status: TransactionStatus
    occurred_on: date
    booking_date: date | None
    value_date: date | None
    amount: Decimal
    currency: str
    original_amount: Decimal | None
    original_currency: str | None
    counterparty_name: str | None  # as the bank sent it
    description: str | None
    reference: str | None
    mcc: str | None
    bank_code: str | None
    # The user layer.
    kind: TransactionKind
    kind_source: Source | None  # set when the kind isn't derived from the category or sign
    category: TransactionCategory | None
    counterparty: TransactionCounterparty | None
    transfer: TransactionTransfer | None
    note: str | None
    tags: list[str]  # added by hand
    rule_tags: list[str]  # added by rules


class TransactionPage(BaseModel):
    items: list[TransactionOut]
    next_cursor: str | None


class TransactionUpdate(BaseModel):
    """Only the fields sent change. `null` hands a field back to the automatic layer
    (category, counterparty, kind) or clears it (note)."""

    category_id: uuid.UUID | None = None
    counterparty_id: uuid.UUID | None = None
    kind: TransactionKind | None = None
    note: str | None = Field(default=None, max_length=2000)
    tags: list[str] | None = Field(default=None, max_length=20)


class ApplyToCounterparty(BaseModel):
    """Offered after a category is set by hand: make it the counterparty's default too."""

    counterparty_id: uuid.UUID
    counterparty_name: str
    category_id: uuid.UUID
    other_transactions: int


class TransactionUpdated(BaseModel):
    transaction: TransactionOut
    offer: ApplyToCounterparty | None


class SuggestionApproval(BaseModel):
    """Transactions whose AI-suggested category the user keeps."""

    transaction_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


class SuggestionsApproved(BaseModel):
    approved: int  # now set by the user; the others had no AI suggestion


class TransferLink(BaseModel):
    outgoing_id: uuid.UUID
    incoming_id: uuid.UUID


# Categories, counterparties, rules


class CategoryOut(BaseModel):
    id: uuid.UUID
    name: str
    kind: CategoryKind
    position: int
    archived: bool
    transactions: int  # visible transactions in it (a group's own count excludes children)


class CategoryGroupOut(CategoryOut):
    children: list[CategoryOut]


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    parent_id: uuid.UUID | None = None  # none: a new group
    kind: CategoryKind | None = None  # groups only; categories take their group's kind


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    parent_id: uuid.UUID | None = None  # categories only: move to another group
    position: int | None = Field(default=None, ge=0, le=1000)
    archived: bool | None = None


class CounterpartyOut(BaseModel):
    id: uuid.UUID
    name: str
    default_category_id: uuid.UUID | None
    transactions: int
    aliases: list[str]


class CounterpartyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    default_category_id: uuid.UUID | None = None


class CounterpartyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    default_category_id: uuid.UUID | None = None  # null clears it


class CounterpartyMerge(BaseModel):
    into_id: uuid.UUID


class RuleIn(BaseModel):
    """The format of conditions and actions is described in categorize/rules.py."""

    name: str = Field(min_length=1, max_length=100)
    enabled: bool = True
    match: RuleMatch = RuleMatch.ALL
    conditions: list[Condition] = Field(min_length=1)
    actions: list[Action] = Field(min_length=1)
    stop_processing: bool = False


class RuleOut(RuleIn):
    id: uuid.UUID
    position: int


class RuleOrder(BaseModel):
    ids: list[uuid.UUID]


class RulePreviewIn(BaseModel):
    match: RuleMatch = RuleMatch.ALL
    conditions: list[Condition] = Field(min_length=1)


class RulePreview(BaseModel):
    matches: int
    examples: list[TransactionOut]


class RunResult(BaseModel):
    processed: int
    categorized: int
    counterparties_created: int


# Insights: amounts in euros, rounded to cents.


class SpendingCategory(BaseModel):
    id: uuid.UUID
    name: str
    amounts: list[Decimal]  # one per month; positive = spent, net of refunds


class SpendingGroup(SpendingCategory):
    categories: list[SpendingCategory]  # biggest first


class Spending(BaseModel):
    months: list[date]  # the first day of each month, oldest first
    groups: list[SpendingGroup]  # expense groups with any spending, biggest first
    uncategorized: list[Decimal]  # expenses without a category, per month
    unconverted: int  # transactions left out: no exchange rate for their day


class SpendingDay(BaseModel):
    day: date
    amount: Decimal  # spent that day, net of refunds (negative if only refunds came in)
    count: int  # transactions summed
    running: Decimal | None  # spent from the 1st through this day; null after `through`


class SpendingRank(BaseModel):
    id: uuid.UUID | None  # null: no category (or no merchant) assigned
    name: str | None
    parent_id: uuid.UUID | None  # categories only: the group a category belongs to
    amount: Decimal  # positive = spent, net of refunds
    count: int
    share: Decimal  # amount / total spent, four decimals; 0 if nothing was spent


class SpendingMonthPart(BaseModel):
    month: date  # its first day
    through: date | None  # the last day counted: today in the current month, else the month's end
    incomplete: bool  # the current month, or the accounts' data starts after the month does
    total: Decimal  # positive = spent, in euros, net of refunds
    count: int
    days: list[SpendingDay]  # every day of the month, in order


class SpendingMonth(SpendingMonthPart):
    """One month's spending, narrowed by at most one of account, category (a group takes its
    categories) or merchant. Transactions without a rate for their day are left out, as in
    the other insights."""

    daily_average: Decimal  # total over the days from the 1st through `through`
    categories: list[SpendingRank]  # biggest first
    merchants: list[SpendingRank]  # biggest first
    previous: SpendingMonthPart  # the month before, same narrowing
    previous_to_date: Decimal  # the month before, through the same day number as `through`


class CashFlowMonth(BaseModel):
    month: date
    income: Decimal
    spending: Decimal
    net: Decimal


class CashFlow(BaseModel):
    months: list[CashFlowMonth]  # oldest first
    unconverted: int


class NetWorthPoint(BaseModel):
    on: date
    amount: Decimal


class NetWorthAccount(BaseModel):
    id: uuid.UUID
    name: str
    currency: str
    balance: Decimal | None  # today, in the account's currency; None: no balance yet
    balance_eur: Decimal | None  # None: no balance, or no exchange rate
    as_of: date | None  # the date of the bank's latest balance


class NetWorthOut(BaseModel):
    total: Decimal  # today
    points: list[NetWorthPoint]  # daily, oldest first
    accounts: list[NetWorthAccount]  # the accounts included in net worth
    unconverted: int  # account-days left out: no exchange rate
    unpriced: int  # holding-days of investment accounts left out: no price or exchange rate


# Investments (ADR-0008): amounts in the account's currency, rounded to cents; prices per share
# in the instrument's currency.


class Holding(BaseModel):
    ticker: str  # Trading 212's, e.g. AAPL_US_EQ
    isin: str | None
    name: str  # the ticker when Trading 212 gives no name
    type: str | None  # STOCK, ETF, …; None when the key can't read the instrument list
    instrument_currency: str | None  # of its prices; GBX is pence
    quantity: Decimal
    average_price: Decimal | None
    current_price: Decimal | None
    value: Decimal | None
    cost: Decimal | None
    result: Decimal | None  # value less cost
    weight: Decimal | None  # its share of the holdings' value, 0 to 1


class UnexplainedQuantity(BaseModel):
    ticker: str
    name: str
    quantity: Decimal  # what the latest positions hold beyond what the fills add up to


class InvestmentCheck(BaseModel):
    """The value rebuilt from trades and daily prices against Trading 212's own (ADR-0008)."""

    on: date  # the day of the latest sync's positions
    rebuilt_value: Decimal | None  # cash plus holdings at that day's prices; None: no FX rate
    difference: Decimal | None  # rebuilt_value less the account's value
    unpriced: list[str]  # holdings left out of rebuilt_value: no price or exchange rate
    # What the history doesn't explain: cash and shares the rebuild has before any movement.
    unexplained_cash: Decimal
    unexplained: list[UnexplainedQuantity]


class InvestmentAccount(BaseModel):
    id: uuid.UUID
    name: str
    currency: str
    as_of: datetime | None  # when the holdings were read; None: not yet
    value: Decimal | None  # cash plus holdings at market value
    cash: Decimal | None  # available, in pies and reserved for orders
    cost: Decimal | None  # what the holdings cost
    result: Decimal | None  # the holdings' value less their cost
    realised_result: Decimal | None  # on what's been sold
    holdings: list[Holding]  # biggest first
    dividends: list[Decimal]  # one per month
    interest: list[Decimal]  # on cash and from share lending, one per month
    check: InvestmentCheck | None  # None: not synced since positions are read


class InvestmentsOut(BaseModel):
    months: list[date]  # the first day of each month, oldest first
    accounts: list[InvestmentAccount]


class ReturnsBreakdown(BaseModel):
    """The period's result, the change in value less net deposits, in parts that add up to it."""

    unrealised: Decimal  # price movements on what's held at the end
    realised: Decimal  # price movements on what was sold in the period
    dividends: Decimal
    interest: Decimal  # on cash and from share lending
    fees: Decimal  # fees and taxes, on trades and charged on their own; negative when paid
    other: Decimal  # cash movements of any other type
    total: Decimal


class ValuePoint(BaseModel):
    on: date
    value: Decimal | None  # None: no exchange rate for the account's currency
    net_deposits: Decimal  # deposits less withdrawals since the account opened


class ReturnGap(StrEnum):
    """Why a return is missing."""

    NO_MONEY = "no_money"  # nothing was invested in the period
    NO_VALUE = "no_value"  # no exchange rate for the account's currency at its start or end
    NO_SOLUTION = "no_solution"  # no rate fits the period's cash flows (money-weighted only)


class InvestmentReturns(BaseModel):
    """An investment account's returns over a period (ADR-0008, "Returns"). Returns are
    fractions: 0.05 is 5%."""

    id: uuid.UUID
    name: str
    currency: str
    # The period: never before the account's first movement, nor after today. None: no history
    # yet (not synced since positions are read).
    date_from: date | None
    date_to: date | None
    start_value: Decimal | None  # at the end of the day before date_from; None: no history
    end_value: Decimal | None
    deposits: Decimal  # money in from outside the account, in the period
    withdrawals: Decimal  # money out, negative
    net_deposits: Decimal
    breakdown: ReturnsBreakdown | None  # None: no value at the start or the end
    time_weighted: Decimal | None  # over the period
    time_weighted_annual: Decimal | None  # a year's equivalent; None for a period under a year
    time_weighted_gap: ReturnGap | None
    money_weighted: Decimal | None  # over the period, from its first money in
    money_weighted_annual: Decimal | None  # the XIRR; None for a period under a year
    money_weighted_gap: ReturnGap | None
    unpriced: int  # holding-days in the period left out: no price or exchange rate
    unconverted: int  # days without an exchange rate for the account's currency
    points: list[ValuePoint]  # daily, oldest first


class InvestmentReturnsOut(BaseModel):
    accounts: list[InvestmentReturns]


# Budgets: amounts in euros.


class BudgetIn(BaseModel):
    amount: Decimal = Field(ge=0, max_digits=15, decimal_places=2)
    from_month: date  # any day of the first month the amount applies to
    rollover: bool = False
    overspend: Overspend = Overspend.FORGIVE


class BudgetLimitOut(BaseModel):
    starts_on: date
    amount: Decimal


class BudgetSettings(BaseModel):
    category_id: uuid.UUID | None  # None: the overall budget
    rollover: bool
    overspend: Overspend
    limits: list[BudgetLimitOut]  # oldest first; each holds until the next


class BudgetOut(BaseModel):
    category_id: uuid.UUID
    name: str
    group_id: uuid.UUID | None  # None: the budget is on a group
    rollover: bool
    overspend: Overspend
    starts_on: date  # the budget's first month
    limit: Decimal
    carried_in: Decimal  # from last month: positive left over, negative overspend
    available: Decimal
    spent: Decimal
    remaining: Decimal  # negative when over
    children: list[BudgetOut]  # a group's budgeted categories: sub-limits within it


class OverallBudgetOut(BaseModel):
    """The cap on all spending, uncategorized included: cash flow's figure for the month."""

    rollover: bool
    overspend: Overspend
    starts_on: date
    limit: Decimal
    carried_in: Decimal
    available: Decimal
    spent: Decimal
    remaining: Decimal  # negative when over


class BudgetsOut(BaseModel):
    month: date
    overall: OverallBudgetOut | None
    budgets: list[BudgetOut]  # in category order; categories under a budgeted group nest in it
    # Totals over the top-level category budgets only, so nothing is counted twice.
    total_limit: Decimal
    total_available: Decimal
    total_spent: Decimal
    unbudgeted: Decimal  # categorized spending that no budget covers
    uncategorized: Decimal
    unconverted: int


# Recurring payments.


class RecurringOut(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    account_name: str
    name: str  # the user's name for it, else the detected one
    counterparty_id: uuid.UUID | None
    cadence: Cadence
    kind: TransactionKind  # expense or income
    expected_amount: Decimal  # signed, like transactions; the latest price
    currency: str
    amount_varies: bool
    occurrences: int
    first_seen_on: date
    last_seen_on: date
    next_expected_on: date
    previous_amount: Decimal | None  # before the latest price change
    amount_changed_on: date | None
    status: RecurringStatus
    review: Review


class RecurringUpdate(BaseModel):
    """Only the fields sent change. An empty `name` goes back to the detected one."""

    review: Review | None = None
    name: str | None = Field(default=None, max_length=100)
    cancelled: bool | None = None  # it stopped; false undoes that


class UpcomingPayment(BaseModel):
    series_id: uuid.UUID
    name: str
    on: date
    kind: TransactionKind
    amount: Decimal  # signed, in the series' currency
    currency: str
    amount_eur: Decimal | None  # at today's rate; None without one
