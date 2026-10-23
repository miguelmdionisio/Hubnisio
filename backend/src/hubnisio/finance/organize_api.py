"""Categories, counterparties (merchants) and rules: the household's tools for saying what
transactions are (ADR-0007).

These belong to the household (ADR-0005). Counts only include transactions the principal may
see. Changes that affect categorization re-run it, so the result shows at once.
"""

import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import Select, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from hubnisio.core.auth import Principal
from hubnisio.finance import schemas
from hubnisio.finance.categorize.engine import CategorizeResult, categorize
from hubnisio.finance.categorize.rules import (
    AddTag,
    RuleSpec,
    SetCategory,
    SetCounterparty,
    facts_for,
    matches,
)
from hubnisio.finance.categorize.run import run_all
from hubnisio.finance.categorize.text import match_key
from hubnisio.finance.deps import CurrentPrincipal, DbSession
from hubnisio.finance.models import (
    Category,
    CategoryAssignment,
    CategoryKind,
    Counterparty,
    CounterpartyAlias,
    Rule,
    Transaction,
    TransactionAnnotation,
)
from hubnisio.finance.scoping import visible_account_ids
from hubnisio.finance.transactions_api import (
    transaction_out,
    transactions_query,
    visible_accounts,
)

router = APIRouter(prefix="/finance", tags=["finance"])

PREVIEW_EXAMPLES = 5


# Categories


@router.get("/categories", operation_id="listCategories")
async def list_categories(
    session: DbSession, principal: CurrentPrincipal
) -> list[schemas.CategoryGroupOut]:
    """Groups and their categories, archived ones included (flagged)."""
    categories = list(
        await session.scalars(
            select(Category)
            .where(Category.household_id == principal.household_id, Category.user_id.is_(None))
            .order_by(Category.position, Category.name)
        )
    )
    counts = dict(
        await _counts(
            session,
            principal,
            select(CategoryAssignment.category_id, func.count())
            .join(Transaction, Transaction.id == CategoryAssignment.transaction_id)
            .group_by(CategoryAssignment.category_id),
        )
    )
    children: dict[uuid.UUID, list[schemas.CategoryOut]] = defaultdict(list)
    for category in categories:
        if category.parent_id is not None:
            children[category.parent_id].append(_category_out(category, counts))
    return [
        schemas.CategoryGroupOut(
            **_category_out(category, counts).model_dump(), children=children[category.id]
        )
        for category in categories
        if category.parent_id is None
    ]


@router.post("/categories", status_code=status.HTTP_201_CREATED, operation_id="createCategory")
async def create_category(
    body: schemas.CategoryCreate, session: DbSession, principal: CurrentPrincipal
) -> schemas.CategoryOut:
    """A new group (no parent) or a category in a group."""
    if body.parent_id is not None:
        parent = await _own_category(session, principal, body.parent_id)
        if parent.parent_id is not None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "Categories go inside a group."
            )
        kind = parent.kind
    else:
        kind = body.kind or CategoryKind.EXPENSE
    last = await session.scalar(
        select(func.max(Category.position)).where(
            Category.household_id == principal.household_id,
            Category.parent_id == body.parent_id
            if body.parent_id
            else Category.parent_id.is_(None),
        )
    )
    category = Category(
        household_id=principal.household_id,
        parent_id=body.parent_id,
        name=body.name.strip(),
        kind=kind,
        position=(last + 1) if last is not None else 0,
    )
    session.add(category)
    await session.commit()
    return _category_out(category, {})


@router.patch("/categories/{category_id}", operation_id="updateCategory")
async def update_category(
    category_id: uuid.UUID,
    body: schemas.CategoryUpdate,
    session: DbSession,
    principal: CurrentPrincipal,
) -> schemas.CategoryOut:
    """Rename, reorder, move a category to another group, or archive (and unarchive).
    Archiving a group archives its categories; archived categories get no new transactions."""
    category = await _own_category(session, principal, category_id)
    fields = body.model_fields_set
    if body.name is not None:
        category.name = body.name.strip()
    if body.position is not None:
        category.position = body.position
    if "parent_id" in fields and body.parent_id != category.parent_id:
        if category.parent_id is None or body.parent_id is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Groups stay at the top level, and categories stay in a group.",
            )
        group = await _own_category(session, principal, body.parent_id)
        if group.parent_id is not None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "Categories go inside a group."
            )
        category.parent_id, category.kind = group.id, group.kind
    recategorize = False
    if body.archived is not None and body.archived != (category.archived_at is not None):
        archived_at = datetime.now(UTC) if body.archived else None
        category.archived_at = archived_at
        if body.archived and category.parent_id is None:
            await session.execute(
                update(Category)
                .where(Category.parent_id == category.id)
                .values(archived_at=archived_at)
            )
        recategorize = True
    await session.flush()
    if recategorize:
        await categorize(session, principal.household_id)
    await session.commit()
    counts = dict(
        await _counts(
            session,
            principal,
            select(CategoryAssignment.category_id, func.count())
            .join(Transaction, Transaction.id == CategoryAssignment.transaction_id)
            .where(CategoryAssignment.category_id == category.id)
            .group_by(CategoryAssignment.category_id),
        )
    )
    return _category_out(category, counts)


@router.delete(
    "/categories/{category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteCategory",
)
async def delete_category(
    category_id: uuid.UUID, session: DbSession, principal: CurrentPrincipal
) -> Response:
    """Only unused categories can be deleted; archive the others."""
    category = await _own_category(session, principal, category_id)
    in_use = (
        await session.scalar(
            select(func.count()).select_from(Category).where(Category.parent_id == category.id)
        )
        or await session.scalar(
            select(func.count())
            .select_from(CategoryAssignment)
            .where(CategoryAssignment.category_id == category.id)
        )
        or await session.scalar(
            select(func.count())
            .select_from(Counterparty)
            .where(Counterparty.default_category_id == category.id)
        )
        or any(
            isinstance(action, SetCategory) and action.category_id == category.id
            for spec in await _rule_specs(session, principal)
            for action in spec.actions
        )
    )
    if in_use:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This category is in use (transactions, merchants, rules or subcategories). "
            "Archive it instead.",
        )
    await session.delete(category)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# Counterparties


@router.get("/counterparties", operation_id="listCounterparties")
async def list_counterparties(
    session: DbSession,
    principal: CurrentPrincipal,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> list[schemas.CounterpartyOut]:
    """Most used first."""
    query = select(Counterparty).where(Counterparty.household_id == principal.household_id)
    if q and q.strip():
        query = query.where(Counterparty.name.ilike(f"%{q.strip()}%"))
    counterparties = list(await session.scalars(query))
    counts = dict(
        await _counts(
            session,
            principal,
            select(TransactionAnnotation.counterparty_id, func.count())
            .join(Transaction, Transaction.id == TransactionAnnotation.transaction_id)
            .group_by(TransactionAnnotation.counterparty_id),
        )
    )
    aliases: dict[uuid.UUID, list[str]] = defaultdict(list)
    for key, counterparty_id in await session.execute(
        select(CounterpartyAlias.alias_key, CounterpartyAlias.counterparty_id).where(
            CounterpartyAlias.household_id == principal.household_id
        )
    ):
        aliases[counterparty_id].append(key)
    counterparties.sort(key=lambda item: (-counts.get(item.id, 0), item.name.casefold()))
    return [_counterparty_out(item, counts, aliases) for item in counterparties]


@router.post(
    "/counterparties", status_code=status.HTTP_201_CREATED, operation_id="createCounterparty"
)
async def create_counterparty(
    body: schemas.CounterpartyCreate, session: DbSession, principal: CurrentPrincipal
) -> schemas.CounterpartyOut:
    """A merchant no bank name has made yet, for a rule or a transaction to point at. Names
    that compare the same as an existing one's are refused."""
    name = body.name.strip()
    key = match_key(name)
    if not key:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Give it a name.")
    for existing in await session.scalars(
        select(Counterparty).where(Counterparty.household_id == principal.household_id)
    ):
        if match_key(existing.name) == key:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, f"{existing.name} already exists."
            )
    if body.default_category_id is not None:
        await _usable_category(session, principal, body.default_category_id)
    counterparty = Counterparty(
        household_id=principal.household_id,
        name=name,
        default_category_id=body.default_category_id,
    )
    session.add(counterparty)
    await session.commit()
    return _counterparty_out(counterparty, {}, {})


@router.patch("/counterparties/{counterparty_id}", operation_id="updateCounterparty")
async def update_counterparty(
    counterparty_id: uuid.UUID,
    body: schemas.CounterpartyUpdate,
    session: DbSession,
    principal: CurrentPrincipal,
) -> schemas.CounterpartyOut:
    """Rename, or set the default category for all its transactions (past and future), unless
    a rule or a choice made by hand says otherwise."""
    counterparty = await _own_counterparty(session, principal, counterparty_id)
    if body.name is not None:
        counterparty.name = body.name.strip()
    if "default_category_id" in body.model_fields_set:
        if body.default_category_id is not None:
            await _usable_category(session, principal, body.default_category_id)
        counterparty.default_category_id = body.default_category_id
    await session.flush()
    await categorize(
        session, principal.household_id, await _transactions_of(session, [counterparty.id])
    )
    await session.commit()
    return await _one_counterparty(session, principal, counterparty)


@router.post("/counterparties/{counterparty_id}/merge", operation_id="mergeCounterparty")
async def merge_counterparty(
    counterparty_id: uuid.UUID,
    body: schemas.CounterpartyMerge,
    session: DbSession,
    principal: CurrentPrincipal,
) -> schemas.CounterpartyOut:
    """Fold one counterparty into another: its bank names, transactions and rules follow."""
    source = await _own_counterparty(session, principal, counterparty_id)
    target = await _own_counterparty(session, principal, body.into_id)
    if source.id == target.id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "That's the same one.")
    affected = await _transactions_of(session, [source.id])
    await session.execute(
        update(CounterpartyAlias)
        .where(CounterpartyAlias.counterparty_id == source.id)
        .values(counterparty_id=target.id)
    )
    await session.execute(
        update(TransactionAnnotation)
        .where(TransactionAnnotation.counterparty_id == source.id)
        .values(counterparty_id=target.id)
    )
    for rule in await session.scalars(
        select(Rule).where(Rule.household_id == principal.household_id)
    ):
        if any(action.get("counterparty_id") == str(source.id) for action in rule.actions):
            rule.actions = [
                {**action, "counterparty_id": str(target.id)}
                if action.get("counterparty_id") == str(source.id)
                else action
                for action in rule.actions
            ]
    target.default_category_id = target.default_category_id or source.default_category_id
    await session.delete(source)
    await session.flush()
    await categorize(session, principal.household_id, affected)
    await session.commit()
    return await _one_counterparty(session, principal, target)


# Rules


@router.get("/rules", operation_id="listRules")
async def list_rules(session: DbSession, principal: CurrentPrincipal) -> list[schemas.RuleOut]:
    return [_rule_out(rule) for rule in await _rules(session, principal)]


@router.post("/rules", status_code=status.HTTP_201_CREATED, operation_id="createRule")
async def create_rule(
    body: schemas.RuleIn, session: DbSession, principal: CurrentPrincipal
) -> schemas.RuleOut:
    """A new rule, last in order. Categorization re-runs."""
    await _check_references(session, principal, body)
    last = await session.scalar(
        select(func.max(Rule.position)).where(Rule.household_id == principal.household_id)
    )
    rule = Rule(household_id=principal.household_id, position=(last or 0) + 1)
    _apply(rule, body)
    session.add(rule)
    await session.flush()
    await run_all(session, principal.household_id)
    await session.commit()
    return _rule_out(rule)


@router.put("/rules/{rule_id}", operation_id="updateRule")
async def update_rule(
    rule_id: uuid.UUID, body: schemas.RuleIn, session: DbSession, principal: CurrentPrincipal
) -> schemas.RuleOut:
    rule = await _own_rule(session, principal, rule_id)
    await _check_references(session, principal, body)
    _apply(rule, body)
    rule.updated_at = datetime.now(UTC)
    await session.flush()
    await run_all(session, principal.household_id)
    await session.commit()
    return _rule_out(rule)


@router.delete(
    "/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT, operation_id="deleteRule"
)
async def delete_rule(
    rule_id: uuid.UUID, session: DbSession, principal: CurrentPrincipal
) -> Response:
    rule = await _own_rule(session, principal, rule_id)
    await session.delete(rule)
    await session.flush()
    await run_all(session, principal.household_id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/rules-order", operation_id="reorderRules")
async def reorder_rules(
    body: schemas.RuleOrder, session: DbSession, principal: CurrentPrincipal
) -> list[schemas.RuleOut]:
    """The new order of all the household's rules, first to last."""
    rules = {rule.id: rule for rule in await _rules(session, principal)}
    if set(body.ids) != set(rules) or len(body.ids) != len(rules):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "List every rule exactly once.")
    for position, rule_id in enumerate(body.ids):
        rules[rule_id].position = position
    await session.flush()
    await run_all(session, principal.household_id)
    await session.commit()
    return [_rule_out(rules[rule_id]) for rule_id in body.ids]


@router.post("/rules/preview", operation_id="previewRule")
async def preview_rule(
    body: schemas.RulePreviewIn, session: DbSession, principal: CurrentPrincipal
) -> schemas.RulePreview:
    """How many visible transactions these conditions match, with the most recent examples."""
    spec = RuleSpec(match=body.match, conditions=body.conditions, actions=[_NO_OP])
    rows = (
        await session.execute(
            transactions_query(principal).order_by(
                Transaction.occurred_on.desc(), Transaction.id.desc()
            )
        )
    ).all()
    matching = [
        row
        for row in rows
        if matches(
            spec,
            facts_for(row.Transaction, row.Counterparty.name if row.Counterparty else None),
        )
    ]
    visible = await visible_accounts(session, principal)
    return schemas.RulePreview(
        matches=len(matching),
        examples=[transaction_out(row, visible) for row in matching[:PREVIEW_EXAMPLES]],
    )


@router.post("/rules/run", operation_id="runRules")
async def run_rules(session: DbSession, principal: CurrentPrincipal) -> schemas.RunResult:
    """Pair transfers and categorize everything again."""
    result = await run_all(session, principal.household_id)
    await session.commit()
    return _run_result(result)


# Helpers

_NO_OP = AddTag(type="add_tag", tag="preview")  # a preview needs no actions; specs need one


async def _counts(
    session: AsyncSession, principal: Principal, query: Select[Any, int]
) -> list[tuple[uuid.UUID, int]]:
    """Run a (key, count) query over the transactions the principal may see."""
    rows = await session.execute(
        query.where(Transaction.account_id.in_(visible_account_ids(principal)))
    )
    return [(row[0], row[1]) for row in rows]


def _category_out(category: Category, counts: dict[uuid.UUID, int]) -> schemas.CategoryOut:
    return schemas.CategoryOut(
        id=category.id,
        name=category.name,
        kind=category.kind,
        position=category.position,
        archived=category.archived_at is not None,
        transactions=counts.get(category.id, 0),
    )


async def _own_category(
    session: AsyncSession, principal: Principal, category_id: uuid.UUID
) -> Category:
    category = await session.get(Category, category_id)
    if category is None or category.household_id != principal.household_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such category.")
    return category


async def _usable_category(
    session: AsyncSession, principal: Principal, category_id: uuid.UUID
) -> Category:
    """A merchant's default category: the household's own, and not archived."""
    category = await _own_category(session, principal, category_id)
    if category.archived_at is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "It's archived.")
    return category


async def _own_counterparty(
    session: AsyncSession, principal: Principal, counterparty_id: uuid.UUID
) -> Counterparty:
    counterparty = await session.get(Counterparty, counterparty_id)
    if counterparty is None or counterparty.household_id != principal.household_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such counterparty.")
    return counterparty


async def _transactions_of(
    session: AsyncSession, counterparty_ids: list[uuid.UUID]
) -> list[uuid.UUID]:
    return list(
        await session.scalars(
            select(TransactionAnnotation.transaction_id).where(
                TransactionAnnotation.counterparty_id.in_(counterparty_ids)
            )
        )
    )


def _counterparty_out(
    counterparty: Counterparty,
    counts: dict[uuid.UUID, int],
    aliases: dict[uuid.UUID, list[str]],
) -> schemas.CounterpartyOut:
    return schemas.CounterpartyOut(
        id=counterparty.id,
        name=counterparty.name,
        default_category_id=counterparty.default_category_id,
        transactions=counts.get(counterparty.id, 0),
        aliases=sorted(aliases.get(counterparty.id, [])),
    )


async def _one_counterparty(
    session: AsyncSession, principal: Principal, counterparty: Counterparty
) -> schemas.CounterpartyOut:
    counts = dict(
        await _counts(
            session,
            principal,
            select(TransactionAnnotation.counterparty_id, func.count())
            .join(Transaction, Transaction.id == TransactionAnnotation.transaction_id)
            .where(TransactionAnnotation.counterparty_id == counterparty.id)
            .group_by(TransactionAnnotation.counterparty_id),
        )
    )
    keys = list(
        await session.scalars(
            select(CounterpartyAlias.alias_key).where(
                CounterpartyAlias.counterparty_id == counterparty.id
            )
        )
    )
    return _counterparty_out(counterparty, counts, {counterparty.id: keys})


async def _rules(session: AsyncSession, principal: Principal) -> list[Rule]:
    return list(
        await session.scalars(
            select(Rule)
            .where(Rule.household_id == principal.household_id)
            .order_by(Rule.position, Rule.created_at)
        )
    )


async def _rule_specs(session: AsyncSession, principal: Principal) -> list[RuleSpec]:
    specs = []
    for rule in await _rules(session, principal):
        try:
            specs.append(
                RuleSpec.model_validate(
                    {"match": rule.match, "conditions": rule.conditions, "actions": rule.actions}
                )
            )
        except ValueError:
            continue
    return specs


async def _own_rule(session: AsyncSession, principal: Principal, rule_id: uuid.UUID) -> Rule:
    rule = await session.get(Rule, rule_id)
    if rule is None or rule.household_id != principal.household_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such rule.")
    return rule


async def _check_references(
    session: AsyncSession, principal: Principal, body: schemas.RuleIn
) -> None:
    """Rules may only point at the household's own, unarchived categories and counterparties."""
    for action in body.actions:
        if isinstance(action, SetCategory):
            category = await _own_category(session, principal, action.category_id)
            if category.archived_at is not None:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT, f"{category.name} is archived."
                )
        elif isinstance(action, SetCounterparty):
            await _own_counterparty(session, principal, action.counterparty_id)
    for condition in body.conditions:
        if condition.field == "account" and uuid.UUID(str(condition.value)) not in (
            await visible_accounts(session, principal)
        ):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such account.")


def _apply(rule: Rule, body: schemas.RuleIn) -> None:
    rule.name = body.name.strip()
    rule.enabled = body.enabled
    rule.match = body.match
    rule.conditions = [condition.model_dump(mode="json") for condition in body.conditions]
    rule.actions = [action.model_dump(mode="json") for action in body.actions]
    rule.stop_processing = body.stop_processing


def _rule_out(rule: Rule) -> schemas.RuleOut:
    return schemas.RuleOut.model_validate(
        {
            "id": rule.id,
            "position": rule.position,
            "name": rule.name,
            "enabled": rule.enabled,
            "match": rule.match,
            "conditions": rule.conditions,
            "actions": rule.actions,
            "stop_processing": rule.stop_processing,
        }
    )


def _run_result(result: CategorizeResult) -> schemas.RunResult:
    return schemas.RunResult(
        processed=result.processed,
        categorized=result.categorized,
        counterparties_created=result.counterparties_created,
    )
