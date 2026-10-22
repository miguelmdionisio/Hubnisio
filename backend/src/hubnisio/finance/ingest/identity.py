"""Transaction identity (ADR-0007).

- Booked with an `entry_reference`: the identity is (account, entry_reference).
- Booked without one: a fingerprint of the bank facts, plus an occurrence index that keeps
  genuinely identical transactions on the same day apart. Indexes follow the order the bank
  listed them in; a fingerprint includes the booking date, and fetch windows cover whole days,
  so every fetch sees the whole group.
- Pending: no stable identity; the sync replaces them all each time.

Some banks send duplicate entry references (Enable Banking FAQ). The same transaction listed
twice collapses into one. Different transactions sharing a reference fall back to the
fingerprint, because the reference can't tell them apart.
"""

import hashlib
import logging
import re
import unicodedata
import uuid
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from hubnisio.finance.models import TransactionStatus
from hubnisio.finance.providers.base import TransactionRecord

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SeenRecord:
    """A record and the payload that reported it."""

    record: TransactionRecord
    payload_id: uuid.UUID
    seen_at: datetime


@dataclass(frozen=True, slots=True)
class Identified:
    seen: SeenRecord
    # For booked rows, None when the bank sent none or it can't serve as the identity.
    entry_reference: str | None
    fingerprint: str
    occurrence_index: int


def normalize_text(value: str | None) -> str:
    """Case, accents, punctuation, spacing and digit runs (card numbers, terminal IDs, times)
    don't change what a transaction is, so they don't change its fingerprint."""
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    with_digit_runs = re.sub(r"\d+", "#", without_accents)
    return " ".join(re.sub(r"[^\w#]+", " ", with_digit_runs).split())


def fingerprint(record: TransactionRecord) -> str:
    amount = record.amount.normalize() if record.amount else Decimal(0)
    parts = (
        (record.booking_date or record.occurred_on).isoformat(),
        format(amount, "f"),
        record.currency.upper(),
        normalize_text(record.counterparty_name),
        normalize_text(record.description),
    )
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


def identify(seen: Sequence[SeenRecord]) -> list[Identified]:
    """Assign identity to one fetch's records for one account, keeping the bank's order."""
    fingerprints = [fingerprint(item.record) for item in seen]

    # Which entry references can serve as identities, and which items are repeats.
    by_reference: dict[str, list[int]] = defaultdict(list)
    for position, item in enumerate(seen):
        if item.record.status is TransactionStatus.BOOKED and item.record.entry_reference:
            by_reference[item.record.entry_reference].append(position)
    repeats: set[int] = set()
    unusable: set[str] = set()
    for reference, positions in by_reference.items():
        first_by_fingerprint: dict[str, int] = {}
        for position in positions:
            if fingerprints[position] in first_by_fingerprint:
                repeats.add(position)
            else:
                first_by_fingerprint[fingerprints[position]] = position
        if len(first_by_fingerprint) > 1:
            unusable.add(reference)
    if repeats:
        logger.warning("Dropped %d transactions listed twice by the bank.", len(repeats))
    if unusable:
        logger.warning("%d entry references were shared by different transactions.", len(unusable))

    occurrences: Counter[tuple[TransactionStatus, str]] = Counter()
    identified: list[Identified] = []
    for position, item in enumerate(seen):
        if position in repeats:
            continue
        reference = item.record.entry_reference
        booked = item.record.status is TransactionStatus.BOOKED
        if booked and reference is not None and reference in unusable:
            reference = None
        # Pending rows keep the bank's reference too, but never use it as their identity.
        if booked and reference is not None:
            index = 0
        else:
            key = (item.record.status, fingerprints[position])
            index = occurrences[key]
            occurrences[key] += 1
        identified.append(
            Identified(
                seen=item,
                entry_reference=reference,
                fingerprint=fingerprints[position],
                occurrence_index=index,
            )
        )
    return identified
