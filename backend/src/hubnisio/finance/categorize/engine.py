"""Categorizing transactions (ADR-0007): counterparty, then rules, then the counterparty's
default category.

Everything automatic is recomputed on every run, so it's safe to run again (after a sync, a
rule edit, or "Run rules now"). Anything set by hand (`Source.MANUAL`) is never touched, and an
AI suggestion survives until something of higher precedence applies.

Precedence for the category: manual > rule > counterparty default > ai. Transfers get no
automatic category: they're neither income nor spending.
"""

import logging
import uuid
from collections.abc import Collection
from dataclasses import dataclass, field

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.finance.categorize.rules import (
    AddTag,
    RuleSpec,
    SetCategory,
    SetCounterparty,
    SetKind,
    facts_for,
    matches,
)
from hubnisio.finance.categorize.text import match_key
from hubnisio.finance.models import (
    Account,
    Category,
    CategoryAssignment,
    Counterparty,
    CounterpartyAlias,
    Rule,
    Source,
    Transaction,
    TransactionAnnotation,
    TransactionKind,
    Transfer,
)

logger = logging.getLogger(__name__)


@dataclass
class CategorizeResult:
    processed: int = 0
    categorized: int = 0  # transactions that have a category after the run
    counterparties_created: int = 0


@dataclass
class _Rule:
    id: uuid.UUID
    spec: RuleSpec
    stop_processing: bool


@dataclass
class _Context:
    """Everything the run needs that isn't per transaction, loaded once."""

    household_id: uuid.UUID
    rules: list[_Rule]
    usable_categories: set[uuid.UUID]  # not archived
    counterparties: dict[uuid.UUID, Counterparty]
    aliases: dict[str, uuid.UUID]
    transfer_ids: set[uuid.UUID]
    created: list[Counterparty] = field(default_factory=list)


async def categorize(
    session: AsyncSession,
    household_id: uuid.UUID,
    transaction_ids: Collection[uuid.UUID] | None = None,
) -> CategorizeResult:
    """Categorize the household's transactions (or just `transaction_ids`). Caller commits."""
    context = await _load_context(session, household_id)
    query = (
        select(Transaction)
        .join(Account, Account.id == Transaction.account_id)
        .where(Account.household_id == household_id)
        .order_by(Transaction.occurred_on, Transaction.id)
    )
    if transaction_ids is not None:
        if not transaction_ids:
            return CategorizeResult()
        query = query.where(Transaction.id.in_(transaction_ids))
    transactions = list(await session.scalars(query))
    ids = [transaction.id for transaction in transactions]
    annotations = {
        annotation.transaction_id: annotation
        for annotation in await session.scalars(
            select(TransactionAnnotation).where(TransactionAnnotation.transaction_id.in_(ids))
        )
    }
    assignments: dict[uuid.UUID, list[CategoryAssignment]] = {}
    for assignment in await session.scalars(
        select(CategoryAssignment).where(CategoryAssignment.transaction_id.in_(ids))
    ):
        assignments.setdefault(assignment.transaction_id, []).append(assignment)

    result = CategorizeResult(processed=len(transactions))
    for transaction in transactions:
        categorized = await _categorize_one(
            session,
            context,
            transaction,
            annotations.get(transaction.id),
            assignments.get(transaction.id, []),
        )
        result.categorized += categorized
    result.counterparties_created = len(context.created)
    await session.flush()
    return result


async def _load_context(session: AsyncSession, household_id: uuid.UUID) -> _Context:
    rules: list[_Rule] = []
    for rule in await session.scalars(
        select(Rule)
        .where(Rule.household_id == household_id, Rule.enabled.is_(True))
        .order_by(Rule.position, Rule.created_at)
    ):
        try:
            spec = RuleSpec.model_validate(
                {"match": rule.match, "conditions": rule.conditions, "actions": rule.actions}
            )
        except ValidationError:
            logger.warning("Skipping rule %s: its conditions or actions are invalid.", rule.id)
            continue
        rules.append(_Rule(rule.id, spec, rule.stop_processing))

    usable_categories = set(
        await session.scalars(
            select(Category.id).where(
                Category.household_id == household_id, Category.archived_at.is_(None)
            )
        )
    )
    counterparties = {
        counterparty.id: counterparty
        for counterparty in await session.scalars(
            select(Counterparty).where(Counterparty.household_id == household_id)
        )
    }
    aliases = {
        key: counterparty_id
        for key, counterparty_id in await session.execute(
            select(CounterpartyAlias.alias_key, CounterpartyAlias.counterparty_id).where(
                CounterpartyAlias.household_id == household_id
            )
        )
    }
    transfer_ids: set[uuid.UUID] = set()
    for outgoing, incoming in await session.execute(
        select(Transfer.outgoing_id, Transfer.incoming_id).where(
            Transfer.household_id == household_id
        )
    ):
        transfer_ids.update((outgoing, incoming))
    return _Context(household_id, rules, usable_categories, counterparties, aliases, transfer_ids)


async def _categorize_one(
    session: AsyncSession,
    context: _Context,
    transaction: Transaction,
    annotation: TransactionAnnotation | None,
    assignments: list[CategoryAssignment],
) -> bool:
    """Returns whether the transaction has a category afterwards."""
    manual_counterparty = annotation is not None and annotation.counterparty_source is Source.MANUAL
    # A kind set by hand stays, and so does an `auto` transfer: the kept side of a pair whose
    # other account was deleted (finance/api.py, delete_account).
    fixed_kind = annotation is not None and annotation.kind_source in (Source.MANUAL, Source.AUTO)

    # 1. Counterparty from the bank's name, unless set by hand.
    counterparty_id: uuid.UUID | None
    counterparty_source: Source | None
    if annotation is not None and manual_counterparty:
        counterparty_id, counterparty_source = annotation.counterparty_id, Source.MANUAL
    else:
        counterparty_id = await _counterparty_from_bank(session, context, transaction)
        counterparty_source = Source.BANK if counterparty_id else None

    # 2. Rules, in order.
    counterparty = context.counterparties.get(counterparty_id) if counterparty_id else None
    facts = facts_for(transaction, counterparty.name if counterparty else None)
    rule_category: tuple[uuid.UUID, uuid.UUID] | None = None  # (category, rule)
    rule_kind: TransactionKind | None = None
    rule_tags: set[str] = set()
    for rule in context.rules:
        if not matches(rule.spec, facts):
            continue
        for action in rule.spec.actions:
            match action:
                case SetCategory(category_id=category_id):
                    if category_id in context.usable_categories:
                        rule_category = (category_id, rule.id)
                case SetCounterparty(counterparty_id=target):
                    if not manual_counterparty and target in context.counterparties:
                        counterparty_id, counterparty_source = target, Source.RULE
                        facts.counterparty = _counterparty_key(context, target)
                case AddTag(tag=tag):
                    rule_tags.add(tag.strip())
                case SetKind(kind=kind):
                    rule_kind = kind
        if rule.stop_processing:
            break

    # 3. Kind: a rule's override applies unless the kind is fixed.
    if annotation is None:
        annotation = TransactionAnnotation(
            transaction_id=transaction.id, household_id=context.household_id, tags=[]
        )
        if counterparty_id or rule_kind or rule_tags:
            session.add(annotation)
    if not manual_counterparty:
        annotation.counterparty_id = counterparty_id
        annotation.counterparty_source = counterparty_source
    if not fixed_kind:
        annotation.kind_override = rule_kind
        annotation.kind_source = Source.RULE if rule_kind else None
    annotation.rule_tags = sorted(rule_tags)
    is_transfer = (
        transaction.id in context.transfer_ids
        or annotation.kind_override is TransactionKind.TRANSFER
    )

    # 4. Category, by precedence.
    if any(assignment.source is Source.MANUAL for assignment in assignments):
        return True
    decided: tuple[uuid.UUID, Source, uuid.UUID | None] | None = None
    if not is_transfer:
        counterparty = context.counterparties.get(counterparty_id) if counterparty_id else None
        default = counterparty.default_category_id if counterparty else None
        if rule_category is not None:
            decided = (rule_category[0], Source.RULE, rule_category[1])
        elif default is not None and default in context.usable_categories:
            decided = (default, Source.COUNTERPARTY, None)
    ai = [assignment for assignment in assignments if assignment.source is Source.AI]
    automatic = [assignment for assignment in assignments if assignment.source is not Source.AI]

    current = automatic[0] if len(automatic) == 1 else None
    if decided is None:
        for assignment in automatic:
            await session.delete(assignment)
        if is_transfer:
            for assignment in ai:
                await session.delete(assignment)
            return False
        return bool(ai)
    category_id, source, rule_id = decided
    if current is not None and (current.category_id, current.source, current.rule_id) == decided:
        return True
    for assignment in [*automatic, *ai]:
        await session.delete(assignment)
    session.add(
        CategoryAssignment(
            household_id=context.household_id,
            transaction_id=transaction.id,
            category_id=category_id,
            source=source,
            rule_id=rule_id,
        )
    )
    return True


async def _counterparty_from_bank(
    session: AsyncSession, context: _Context, transaction: Transaction
) -> uuid.UUID | None:
    """The counterparty the bank's name maps to, created on first sight."""
    name = (transaction.counterparty_name or "").strip()
    key = match_key(name)
    if not key:
        return None
    if key in context.aliases:
        return context.aliases[key]
    counterparty = Counterparty(household_id=context.household_id, name=name[:100])
    session.add(counterparty)
    await session.flush()
    session.add(
        CounterpartyAlias(
            household_id=context.household_id, alias_key=key, counterparty_id=counterparty.id
        )
    )
    context.counterparties[counterparty.id] = counterparty
    context.aliases[key] = counterparty.id
    context.created.append(counterparty)
    return counterparty.id


def _counterparty_key(context: _Context, counterparty_id: uuid.UUID | None) -> str:
    counterparty = context.counterparties.get(counterparty_id) if counterparty_id else None
    return match_key(counterparty.name) if counterparty else ""
