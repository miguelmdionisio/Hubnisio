"""Finding recurring payments in one account's transactions (ADR-0007). Pure: no database.

Transactions are grouped by merchant, else by their description without digits (BPI sends no
merchant names), and by direction. Within a group, chains are built in date order: the gap to
a chain's last payment must fit the cadence (a missed period is allowed now and then) and the
amount must be within 30% of the chain's recent ones, which lets a price rise stay one series.
A chain needs
three payments, and at most half as many other similar payments to the same payee in its
span, so frequent shopping at one place doesn't pass as a series. Payments left over get a second
chance with any amount (utilities, say), marked as varying, on the slower cadences only.
"""

import re
import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from statistics import median

from hubnisio.finance.categorize.text import match_key
from hubnisio.finance.insights.spending import add_months
from hubnisio.finance.models import Cadence, RecurringStatus, TransactionKind

MIN_OCCURRENCES = 3
AMOUNT_TOLERANCE = Decimal("0.30")  # of the median of a chain's last three amounts
# A price change: more than 1% and at least 10 cents.
PRICE_CHANGE_SHARE = Decimal("0.01")
PRICE_CHANGE_MIN = Decimal("0.10")
MISSED_TO_CANCEL = 3


@dataclass(frozen=True)
class CadenceRule:
    days: float  # the average period
    tolerance: int  # days either side

    def fits(self, gap: int) -> tuple[int, int] | None:
        """How many periods the gap spans (two: a missed payment) and how far it is from them;
        None if it fits neither."""
        for periods in (1, 2):
            deviation = abs(gap - self.days * periods)
            if deviation <= self.tolerance * periods:
                return periods, round(deviation)
        return None


CADENCES: dict[Cadence, CadenceRule] = {
    Cadence.WEEKLY: CadenceRule(7, 2),
    Cadence.MONTHLY: CadenceRule(30.44, 5),
    Cadence.QUARTERLY: CadenceRule(91.31, 10),
    Cadence.YEARLY: CadenceRule(365.25, 20),
}
# Weekly first: its payments would otherwise make several interleaved monthly chains.
FIXED_ORDER = (Cadence.WEEKLY, Cadence.MONTHLY, Cadence.QUARTERLY, Cadence.YEARLY)
VARYING_ORDER = (Cadence.MONTHLY, Cadence.QUARTERLY, Cadence.YEARLY)


@dataclass(frozen=True)
class Payment:
    id: uuid.UUID
    on: date
    amount: Decimal  # signed: negative = money out
    currency: str
    counterparty_id: uuid.UUID | None
    counterparty_name: str | None  # the merchant's clean name
    description: str | None


@dataclass(frozen=True)
class Candidate:
    match_key: str
    name: str
    counterparty_id: uuid.UUID | None
    cadence: Cadence
    kind: TransactionKind
    currency: str
    amount_varies: bool
    members: list[Payment]  # oldest first
    expected_amount: Decimal
    next_expected_on: date
    previous_amount: Decimal | None
    amount_changed_on: date | None

    @property
    def member_ids(self) -> set[uuid.UUID]:
        return {payment.id for payment in self.members}


def detect(payments: Iterable[Payment]) -> list[Candidate]:
    """Recurring series among one account's booked payments that aren't transfers."""
    groups: dict[tuple[str, bool, str], list[Payment]] = defaultdict(list)
    for payment in payments:
        key = group_key(payment)
        if key:
            groups[(key, payment.amount > 0, payment.currency)].append(payment)
    candidates: list[Candidate] = []
    for (key, _, _), members in groups.items():
        members.sort(key=lambda p: (p.on, p.id))
        remaining = members
        for varies, order in ((False, FIXED_ORDER), (True, VARYING_ORDER)):
            for cadence in order:
                chains = _chains(remaining, cadence, check_amount=not varies)
                accepted = [c for c in chains if _accept(c, members, check_amount=not varies)]
                taken = {p.id for chain in accepted for p in chain}
                remaining = [p for p in remaining if p.id not in taken]
                candidates.extend(_candidate(key, chain, cadence, varies) for chain in accepted)
    return candidates


def group_key(payment: Payment) -> str:
    if payment.counterparty_id is not None:
        return f"merchant:{payment.counterparty_id}"
    text = description_key(payment.description)
    return f"text:{text}" if text else ""


def description_key(description: str | None) -> str:
    """The description without digits, which carry dates and references."""
    return " ".join(re.sub(r"\d+", " ", match_key(description)).split())


def next_date(on: date, cadence: Cadence, periods: int = 1) -> date:
    match cadence:
        case Cadence.WEEKLY:
            return on + timedelta(weeks=periods)
        case Cadence.MONTHLY:
            return _same_day(on, add_months(on.replace(day=1), periods))
        case Cadence.QUARTERLY:
            return _same_day(on, add_months(on.replace(day=1), 3 * periods))
        case Cadence.YEARLY:
            return _same_day(on, add_months(on.replace(day=1), 12 * periods))


def status_on(
    cadence: Cadence, next_expected_on: date, today: date, cancelled_on: date | None = None
) -> RecurringStatus:
    """Active until the next payment is later than the tolerance; dormant once it is; cancelled
    after three missed in a row, or when the user said so."""
    if cancelled_on is not None:
        return RecurringStatus.CANCELLED
    rule = CADENCES[cadence]
    late = (today - next_expected_on).days - rule.tolerance
    if late <= 0:
        return RecurringStatus.ACTIVE
    missed = 1 + int(late // rule.days)
    return RecurringStatus.CANCELLED if missed >= MISSED_TO_CANCEL else RecurringStatus.DORMANT


def _same_day(original: date, month: date) -> date:
    """`original`'s day of the month in `month`, clamped to the month's length."""
    following = add_months(month, 1)
    last_day = (following - timedelta(days=1)).day
    return month.replace(day=min(original.day, last_day))


def _chains(
    payments: Sequence[Payment], cadence: Cadence, *, check_amount: bool
) -> list[list[Payment]]:
    rule = CADENCES[cadence]
    chains: list[list[Payment]] = []
    missed: list[int] = []  # per chain
    for payment in payments:
        best: tuple[int, int, int] | None = None  # deviation, chain index, periods
        for index, chain in enumerate(chains):
            fit = rule.fits((payment.on - chain[-1].on).days)
            if fit is None or (check_amount and not _similar(chain, payment.amount)):
                continue
            periods, deviation = fit
            if periods > 1 and missed[index] >= _missed_allowed(chain):
                continue
            if best is None or deviation < best[0]:
                best = (deviation, index, periods)
        if best is None:
            chains.append([payment])
            missed.append(0)
        else:
            _, index, periods = best
            chains[index].append(payment)
            missed[index] += periods - 1
    return [chain for chain in chains if len(chain) >= MIN_OCCURRENCES]


def _missed_allowed(chain: Sequence[Payment]) -> int:
    """One missed payment, and one more per six made: payment every other month isn't
    monthly."""
    return 1 + len(chain) // 6


def _similar(chain: Sequence[Payment], amount: Decimal) -> bool:
    recent = median(p.amount for p in chain[-3:])
    return abs(amount - recent) <= abs(recent) * AMOUNT_TOLERANCE


def _accept(chain: list[Payment], group: Sequence[Payment], *, check_amount: bool) -> bool:
    """At most half as many other payments to the same payee in the chain's span as the chain
    has: otherwise the regularity is chance, e.g. shopping every few days makes interleaved
    weekly chains. Two identical subscriptions billed apart are lost to this; that's rare."""
    ids = {p.id for p in chain}
    first, last = chain[0].on, chain[-1].on
    others = sum(
        1
        for p in group
        if p.id not in ids
        and first <= p.on <= last
        and (not check_amount or _similar(chain, p.amount))
    )
    return others <= len(chain) // 2


def _candidate(key: str, chain: list[Payment], cadence: Cadence, varies: bool) -> Candidate:
    latest = chain[-1]
    amounts = [p.amount for p in chain]
    previous_amount = changed_on = None
    if not varies:
        # The latest step in price that every later payment kept.
        for index in range(len(chain) - 1, 0, -1):
            if _changed(amounts[index - 1], amounts[index]):
                if all(not _changed(amounts[index], later) for later in amounts[index + 1 :]):
                    previous_amount, changed_on = amounts[index - 1], chain[index].on
                break
    expected = Decimal(median(amounts[-3:])) if varies else latest.amount
    return Candidate(
        match_key=key,
        name=_name(chain),
        counterparty_id=latest.counterparty_id,
        cadence=cadence,
        kind=TransactionKind.INCOME if latest.amount > 0 else TransactionKind.EXPENSE,
        currency=latest.currency,
        amount_varies=varies,
        members=chain,
        expected_amount=expected,
        next_expected_on=next_date(latest.on, cadence),
        previous_amount=previous_amount,
        amount_changed_on=changed_on,
    )


def _changed(before: Decimal, after: Decimal) -> bool:
    difference = abs(after - before)
    return difference >= PRICE_CHANGE_MIN and difference > abs(before) * PRICE_CHANGE_SHARE


def _name(chain: Sequence[Payment]) -> str:
    latest = chain[-1]
    if latest.counterparty_name:
        return latest.counterparty_name[:100]
    text = description_key(latest.description)
    return (text[:1].upper() + text[1:])[:100] or "Recurring payment"
