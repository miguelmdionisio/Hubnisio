"""Turn a real provider payload into a test fixture.

From backend/:
    uv run python scripts/anonymize_payload.py payload.json > tests/fixtures/enable_banking/x.json

Every string is replaced by a pseudonym, except the fields listed in KEEP (amounts, dates,
currencies, statuses and other codes). Pseudonyms keep the shape of the original (letters stay
letters in the same case, digits stay digits, punctuation stays), and each word always maps to
the same pseudonym, so repeated counterparties and descriptions stay repeated and identity and
duplicate behaviour survives. Pass the same --salt to keep pseudonyms stable across files.

Always read the output before committing it: free text in an unexpected field is scrubbed, but
dates and amounts are not.
"""

import argparse
import hashlib
import hmac
import json
import re
import secrets
import sys
from pathlib import Path
from typing import Any

# Fields whose string values are kept: they describe the transaction, not the people in it.
KEEP = frozenset(
    {
        "amount",
        "balance_type",
        "booking_date",
        "cash_account_type",
        "code",
        "country",
        "credit_debit_indicator",
        "currency",
        "exchange_rate",
        "last_change_date_time",
        "merchant_category_code",
        "psu_type",
        "rate_type",
        "reference_date",
        "scheme_name",
        "status",
        "sub_code",
        "transaction_date",
        "unit_currency",
        "usage",
        "valid_until",
        "value_date",
    }
)


class Pseudonymizer:
    def __init__(self, salt: bytes) -> None:
        self._salt = salt
        self._words: dict[str, str] = {}

    def text(self, value: str) -> str:
        return re.sub(r"\w+", lambda match: self._word(match.group()), value)

    def _word(self, word: str) -> str:
        if word not in self._words:
            stream = b""
            counter = 0
            while len(stream) < len(word):
                message = f"{counter}:{word}".encode()
                stream += hmac.new(self._salt, message, hashlib.sha256).digest()
                counter += 1
            self._words[word] = "".join(
                _like(char, byte) for char, byte in zip(word, stream, strict=False)
            )
        return self._words[word]


def _like(char: str, byte: int) -> str:
    if char.isdigit():
        return str(byte % 10)
    if char.isalpha():
        letter = chr(ord("a") + byte % 26)
        return letter.upper() if char.isupper() else letter
    return char


def scrub(value: Any, pseudonymizer: Pseudonymizer, key: str | None = None) -> Any:
    if isinstance(value, dict):
        return {name: scrub(item, pseudonymizer, name) for name, item in value.items()}
    if isinstance(value, list):
        return [scrub(item, pseudonymizer, key) for item in value]
    if isinstance(value, str) and key not in KEEP:
        return pseudonymizer.text(value)
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="Anonymize a provider payload (JSON).")
    parser.add_argument("path", type=Path)
    parser.add_argument("--salt", help="reuse to keep pseudonyms stable across files")
    args = parser.parse_args()

    salt = args.salt or secrets.token_hex(16)
    if not args.salt:
        print(f"Salt: {salt}", file=sys.stderr)
    payload = json.loads(args.path.read_text(encoding="utf-8"))
    scrubbed = scrub(payload, Pseudonymizer(salt.encode()))
    sys.stdout.write(json.dumps(scrubbed, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
