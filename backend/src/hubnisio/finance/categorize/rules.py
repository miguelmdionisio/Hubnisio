"""The rule format (stored as JSONB in `finance.rules`) and how a rule matches a transaction.

A rule has conditions, joined by `all` or `any`, and actions. Rules run in position order; a
later rule's action replaces an earlier one's, and "stop processing" ends the run for that
transaction. Text is compared by match key (lowercase, no accents); amounts by absolute value.

    {"field": "description", "op": "contains", "value": "continente"}
    {"field": "amount", "op": "between", "value": ["10", "50"]}
    {"type": "set_category", "category_id": "..."}
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hubnisio.finance.categorize.text import match_key
from hubnisio.finance.models import RuleMatch, Transaction, TransactionKind

TEXT_FIELDS = ("description", "counterparty", "bank_counterparty")
TEXT_OPS = ("contains", "starts_with", "equals")
AMOUNT_OPS = ("equals", "gte", "lte", "between")
DIRECTIONS = ("in", "out")

ConditionField = Literal[
    "description",
    "counterparty",
    "bank_counterparty",
    "bank_code",
    "account",
    "direction",
    "amount",
]
ConditionOp = Literal["contains", "starts_with", "equals", "is", "gte", "lte", "between"]


class Condition(BaseModel):
    model_config = ConfigDict(frozen=True)

    field: ConditionField
    op: ConditionOp
    value: str | Decimal | list[Decimal]

    @model_validator(mode="before")
    @classmethod
    def _amounts_as_decimals(cls, data: object) -> object:
        """JSON may carry amounts as strings or numbers."""
        if isinstance(data, dict) and data.get("field") == "amount":
            value = data.get("value")
            try:
                if isinstance(value, list):
                    return {**data, "value": [Decimal(str(item)) for item in value]}
                if value is not None:
                    return {**data, "value": Decimal(str(value))}
            except ArithmeticError as exc:
                raise ValueError("amount takes a number.") from exc
        return data

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.field in TEXT_FIELDS:
            if self.op not in TEXT_OPS or not isinstance(self.value, str) or not self.value.strip():
                raise ValueError(f"{self.field} takes contains / starts_with / equals and text.")
        elif self.field == "amount":
            if self.op not in AMOUNT_OPS:
                raise ValueError("amount takes equals / gte / lte / between.")
            if self.op == "between":
                if not (isinstance(self.value, list) and len(self.value) == 2):
                    raise ValueError("between takes [minimum, maximum].")
            elif not isinstance(self.value, Decimal):
                raise ValueError("amount takes a number.")
        else:
            if self.op != "is" or not isinstance(self.value, str):
                raise ValueError(f"{self.field} takes `is` and a value.")
            if self.field == "direction" and self.value not in DIRECTIONS:
                raise ValueError("direction is `in` or `out`.")
            if self.field == "account":
                uuid.UUID(self.value)
        return self


class SetCategory(BaseModel):
    type: Literal["set_category"]
    category_id: uuid.UUID


class SetCounterparty(BaseModel):
    type: Literal["set_counterparty"]
    counterparty_id: uuid.UUID


class AddTag(BaseModel):
    type: Literal["add_tag"]
    tag: str = Field(min_length=1, max_length=40)


class SetKind(BaseModel):
    type: Literal["set_kind"]
    kind: TransactionKind


Action = Annotated[SetCategory | SetCounterparty | AddTag | SetKind, Field(discriminator="type")]


class RuleSpec(BaseModel):
    """What a rule does, as stored in a `finance.rules` row."""

    match: RuleMatch
    conditions: list[Condition] = Field(min_length=1)
    actions: list[Action] = Field(min_length=1)


@dataclass(slots=True)
class Facts:
    """What conditions look at, for one transaction."""

    description: str  # match keys
    counterparty: str  # the counterparty's name as currently resolved (may change mid-run)
    bank_counterparty: str
    bank_code: str
    account_id: uuid.UUID
    direction: str  # in / out
    amount: Decimal  # absolute


def facts_for(transaction: Transaction, counterparty_name: str | None) -> Facts:
    """The facts of one transaction, with its counterparty as currently resolved."""
    return Facts(
        description=match_key(transaction.description),
        counterparty=match_key(counterparty_name),
        bank_counterparty=match_key(transaction.counterparty_name),
        bank_code=(transaction.bank_transaction_code or {}).get("code") or "",
        account_id=transaction.account_id,
        direction="in" if transaction.amount > 0 else "out",
        amount=abs(transaction.amount),
    )


def matches(spec: RuleSpec, facts: Facts) -> bool:
    results = (_holds(condition, facts) for condition in spec.conditions)
    return all(results) if spec.match is RuleMatch.ALL else any(results)


def _holds(condition: Condition, facts: Facts) -> bool:
    value = condition.value
    match condition.field:
        case "description" | "counterparty" | "bank_counterparty":
            text = getattr(facts, condition.field)
            needle = match_key(str(value))
            match condition.op:
                case "contains":
                    return needle in text
                case "starts_with":
                    return text.startswith(needle)
                case _:
                    return text == needle
        case "bank_code":
            return facts.bank_code.casefold() == str(value).casefold()
        case "account":
            return str(facts.account_id) == str(value)
        case "direction":
            return facts.direction == value
        case "amount":
            match condition.op, value:
                case "between", [low, high]:
                    return min(low, high) <= facts.amount <= max(low, high)
                case "gte", Decimal():
                    return facts.amount >= value
                case "lte", Decimal():
                    return facts.amount <= value
                case "equals", Decimal():
                    return facts.amount == value
                case _:
                    return False
        case _:
            return False
