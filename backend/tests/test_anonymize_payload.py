import json
import runpy
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "anonymize_payload.py"
FIXTURE = Path(__file__).parent / "fixtures" / "enable_banking" / "transactions_page.json"


def anonymize(
    path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> Any:
    monkeypatch.setattr(sys, "argv", ["anonymize_payload.py", str(path), "--salt", "test"])
    runpy.run_path(str(SCRIPT), run_name="__main__")
    return json.loads(capsys.readouterr().out)


def test_people_and_free_text_are_replaced(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    output = json.dumps(anonymize(FIXTURE, monkeypatch, capsys))

    for secret in ("SUPERMERCADO", "ANA EXEMPLO", "PT50000201231234567890154", "SALARIO"):
        assert secret not in output


def test_amounts_dates_and_codes_are_kept(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    first = anonymize(FIXTURE, monkeypatch, capsys)["transactions"][0]

    assert first["transaction_amount"] == {"currency": "EUR", "amount": "42.17"}
    assert (first["status"], first["credit_debit_indicator"]) == ("BOOK", "DBIT")
    assert first["booking_date"] == "2026-10-14"
    assert first["merchant_category_code"] == "5411"


def test_pseudonyms_keep_shape_and_repeat_consistently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = tmp_path / "payload.json"
    payload.write_text(
        json.dumps(
            {
                "transactions": [
                    {"creditor": {"name": "Café Central 12"}, "entry_reference": "AB-1234"},
                    {"creditor": {"name": "Café Central 12"}, "entry_reference": "AB-1235"},
                ]
            }
        )
    )

    first, second = anonymize(payload, monkeypatch, capsys)["transactions"]

    name = first["creditor"]["name"]
    assert name == second["creditor"]["name"]
    assert name != "Café Central 12"
    assert [len(word) for word in name.split()] == [4, 7, 2]
    assert name.split()[2].isdigit()
    assert first["entry_reference"][2] == "-"
    assert first["entry_reference"] != second["entry_reference"]
