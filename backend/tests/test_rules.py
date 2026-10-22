import uuid
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from hubnisio.finance.categorize.rules import Facts, RuleSpec, matches
from hubnisio.finance.categorize.text import match_key

ACCOUNT = uuid.uuid4()


def facts(**overrides: Any) -> Facts:
    values: dict[str, Any] = {
        "description": match_key("COMPRA 4450 Continente Matosinhos"),
        "counterparty": match_key("Continente"),
        "bank_counterparty": "",
        "bank_code": "CARD_PAYMENT",
        "account_id": ACCOUNT,
        "direction": "out",
        "amount": Decimal("42.17"),
    }
    return Facts(**{**values, **overrides})


def rule(*conditions: dict[str, Any], match: str = "all") -> RuleSpec:
    return RuleSpec.model_validate(
        {
            "match": match,
            "conditions": list(conditions),
            "actions": [{"type": "add_tag", "tag": "x"}],
        }
    )


def test_match_key_ignores_case_accents_and_punctuation_but_keeps_digits() -> None:
    assert match_key("  Café-Pastelaria  Nº 12 ") == "cafe pastelaria no 12"
    assert match_key(None) == ""


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        ({"field": "description", "op": "contains", "value": "CONTINENTE"}, True),
        ({"field": "description", "op": "contains", "value": "4450"}, True),
        ({"field": "description", "op": "starts_with", "value": "compra"}, True),
        ({"field": "description", "op": "starts_with", "value": "continente"}, False),
        ({"field": "counterparty", "op": "equals", "value": "continente"}, True),
        ({"field": "bank_counterparty", "op": "contains", "value": "x"}, False),
        ({"field": "bank_code", "op": "is", "value": "card_payment"}, True),
        ({"field": "account", "op": "is", "value": str(ACCOUNT)}, True),
        ({"field": "direction", "op": "is", "value": "in"}, False),
        ({"field": "amount", "op": "between", "value": ["40", "50"]}, True),
        ({"field": "amount", "op": "gte", "value": 42.17}, True),
        ({"field": "amount", "op": "lte", "value": "42"}, False),
        ({"field": "amount", "op": "equals", "value": "42.170"}, True),
    ],
)
def test_conditions(condition: dict[str, Any], expected: bool) -> None:
    assert matches(rule(condition), facts()) is expected


def test_all_and_any() -> None:
    yes = {"field": "direction", "op": "is", "value": "out"}
    no = {"field": "direction", "op": "is", "value": "in"}

    assert matches(rule(yes, no, match="all"), facts()) is False
    assert matches(rule(yes, no, match="any"), facts()) is True


@pytest.mark.parametrize(
    "condition",
    [
        {"field": "description", "op": "gte", "value": "x"},
        {"field": "description", "op": "contains", "value": "   "},
        {"field": "amount", "op": "contains", "value": "1"},
        {"field": "amount", "op": "between", "value": ["1"]},
        {"field": "amount", "op": "gte", "value": "lots"},
        {"field": "direction", "op": "is", "value": "sideways"},
        {"field": "account", "op": "is", "value": "not-a-uuid"},
        {"field": "bank_code", "op": "contains", "value": "CARD"},
        {"field": "colour", "op": "is", "value": "red"},
    ],
)
def test_invalid_conditions_are_rejected(condition: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        rule(condition)


def test_actions_are_typed() -> None:
    spec = RuleSpec.model_validate(
        {
            "match": "all",
            "conditions": [{"field": "direction", "op": "is", "value": "out"}],
            "actions": [
                {"type": "set_category", "category_id": str(uuid.uuid4())},
                {"type": "set_kind", "kind": "transfer"},
            ],
        }
    )
    assert [action.type for action in spec.actions] == ["set_category", "set_kind"]

    with pytest.raises(ValidationError):
        RuleSpec.model_validate(
            {
                "match": "all",
                "conditions": [{"field": "direction", "op": "is", "value": "out"}],
                "actions": [{"type": "delete_everything"}],
            }
        )
