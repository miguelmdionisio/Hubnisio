import uuid
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

from hubnisio.finance.ingest.identity import SeenRecord, fingerprint, identify, normalize_text
from hubnisio.finance.models import TransactionStatus
from hubnisio.finance.providers.base import TransactionRecord

BOOKED = TransactionStatus.BOOKED
PENDING = TransactionStatus.PENDING
PAYLOAD = uuid.uuid7()
SEEN_AT = datetime(2026, 10, 17, 7, 0, tzinfo=UTC)


def record(
    reference: str | None = None,
    *,
    amount: str = "-42.17",
    description: str = "COMPRA SUPERMERCADO",
    status: TransactionStatus = BOOKED,
    day: int = 14,
) -> TransactionRecord:
    return TransactionRecord(
        status=status,
        amount=Decimal(amount),
        currency="EUR",
        occurred_on=date(2026, 10, day),
        booking_date=date(2026, 10, day) if status is BOOKED else None,
        entry_reference=reference,
        counterparty_name="Supermercado",
        description=description,
    )


def seen(*records: TransactionRecord) -> list[SeenRecord]:
    return [SeenRecord(record=item, payload_id=PAYLOAD, seen_at=SEEN_AT) for item in records]


def test_normalize_text_ignores_case_accents_punctuation_and_digits() -> None:
    assert normalize_text("  Compra 4450  CAFÉ-Expresso, Lda. ") == "compra # cafe expresso lda"
    assert normalize_text("COMPRA 9999 cafe expresso LDA") == "compra # cafe expresso lda"
    assert normalize_text(None) == ""


def test_fingerprint_survives_cosmetic_changes_only() -> None:
    base = record()

    assert fingerprint(base) == fingerprint(replace(base, description="compra  supermercado"))
    assert fingerprint(base) == fingerprint(replace(base, amount=Decimal("-42.1700")))
    assert fingerprint(base) != fingerprint(replace(base, amount=Decimal("-42.18")))
    assert fingerprint(base) != fingerprint(record(day=15))
    assert fingerprint(base) != fingerprint(replace(base, counterparty_name="Outro"))


def test_identical_twins_get_increasing_occurrence_indexes() -> None:
    identified = identify(seen(record(), record(), record(amount="-1.00"), record()))

    assert [item.occurrence_index for item in identified] == [0, 1, 0, 2]
    assert all(item.entry_reference is None for item in identified)


def test_a_reference_listed_twice_for_the_same_transaction_collapses() -> None:
    identified = identify(seen(record("R1"), record("R2"), record("R1")))

    assert [item.entry_reference for item in identified] == ["R1", "R2"]


def test_a_reference_shared_by_different_transactions_falls_back_to_fingerprints() -> None:
    identified = identify(seen(record("R1"), record("R1", amount="-9.99"), record("R2")))

    assert [item.entry_reference for item in identified] == [None, None, "R2"]
    assert [item.occurrence_index for item in identified] == [0, 0, 0]


def test_pending_keeps_its_reference_but_never_uses_it_as_identity() -> None:
    identified = identify(
        seen(
            record("P1", status=PENDING),
            record("P1", status=PENDING),
            record("P1"),  # the same reference on a booked row is unaffected
        )
    )

    assert [item.entry_reference for item in identified] == ["P1", "P1", "P1"]
    assert [item.occurrence_index for item in identified] == [0, 1, 0]
