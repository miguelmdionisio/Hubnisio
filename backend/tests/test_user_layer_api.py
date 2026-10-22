"""The user-layer API: transactions, categories, counterparties, rules, transfers."""

import uuid
from typing import Any

import httpx
import pytest
from households import Home, add, api, refresh

from hubnisio.core.db import get_sessionmaker
from hubnisio.finance.models import (
    TransferDismissal,
)

pytestmark = pytest.mark.anyio


async def items(client: httpx.AsyncClient, **params: Any) -> list[dict[str, Any]]:
    response = await client.get("/api/finance/transactions", params=params)
    assert response.status_code == 200, response.text
    return response.json()["items"]


async def counterparty_id(client: httpx.AsyncClient, name: str) -> str:
    listed = (await client.get("/api/finance/counterparties")).json()
    return next(item["id"] for item in listed if item["name"] == name)


async def test_setting_a_category_by_hand_offers_the_merchant_default(home: Home) -> None:
    first = await add(home, "-10", 1, counterparty="Continente")
    second = await add(home, "-20", 2, counterparty="Continente")
    await refresh(home)
    groceries = str(home.categories["Groceries"])

    async with api(home.owner) as client:
        updated = await client.patch(
            f"/api/finance/transactions/{first}", json={"category_id": groceries}
        )
        offer = updated.json()["offer"]
        assert updated.json()["transaction"]["category"]["source"] == "manual"
        assert (offer["counterparty_name"], offer["other_transactions"]) == ("Continente", 1)

        await client.patch(
            f"/api/finance/counterparties/{offer['counterparty_id']}",
            json={"default_category_id": groceries},
        )
        by_id = {item["id"]: item for item in await items(client)}

    assert by_id[str(second)]["category"]["name"] == "Groceries"
    assert by_id[str(second)]["category"]["source"] == "counterparty"
    assert by_id[str(second)]["category"]["group_name"] == "Food"


async def test_clearing_a_manual_choice_hands_it_back_to_the_automatic_layer(home: Home) -> None:
    transaction = await add(home, "-10", 1, counterparty="Continente")
    await refresh(home)
    async with api(home.owner) as client:
        cid = await counterparty_id(client, "Continente")
        await client.patch(
            f"/api/finance/counterparties/{cid}",
            json={"default_category_id": str(home.categories["Groceries"])},
        )
        url = f"/api/finance/transactions/{transaction}"
        await client.patch(url, json={"category_id": str(home.categories["Travel"])})
        cleared = (await client.patch(url, json={"category_id": None})).json()["transaction"]
        noted = await client.patch(url, json={"note": " Para a festa ", "tags": ["a", "A", " b "]})

    assert (cleared["category"]["name"], cleared["category"]["source"]) == (
        "Groceries",
        "counterparty",
    )
    assert noted.json()["transaction"]["note"] == "Para a festa"
    assert noted.json()["transaction"]["tags"] == ["a", "b"]


async def test_filters(home: Home) -> None:
    salary = await add(home, "2100", 1, description="SALARIO")
    coffee = await add(home, "-3", 2, counterparty="Cafe Central")
    out = await add(home, "-500", 3)
    into = await add(home, "500", 3, account=home.savings)
    await refresh(home)
    async with api(home.owner) as client:
        cid = await counterparty_id(client, "Cafe Central")
        await client.patch(
            f"/api/finance/counterparties/{cid}",
            json={"default_category_id": str(home.categories["Cafés & snacks"])},
        )
        await client.patch(f"/api/finance/transactions/{coffee}", json={"note": "com o Rui"})

        def ids(found: list[dict[str, Any]]) -> set[str]:
            return {item["id"] for item in found}

        assert ids(await items(client, kind="transfer")) == {str(out), str(into)}
        assert ids(await items(client, kind="income")) == {str(salary)}
        assert ids(await items(client, kind="expense")) == {str(coffee)}
        assert ids(await items(client, uncategorized=True)) == {str(salary)}
        food = str(home.categories["Food"])
        assert ids(await items(client, category_id=food)) == {str(coffee)}  # a group's children
        assert ids(await items(client, counterparty_id=cid)) == {str(coffee)}
        assert ids(await items(client, q="RUI")) == {str(coffee)}  # notes are searched


async def test_transfers_by_hand_and_unlinking(home: Home) -> None:
    out = await add(home, "-100", 5)
    into = await add(home, "100", 9, account=home.savings)  # too far apart to pair by itself
    await refresh(home)
    async with api(home.owner) as client:
        bad = await client.post(
            "/api/finance/transfers", json={"outgoing_id": str(into), "incoming_id": str(out)}
        )
        linked = await client.post(
            "/api/finance/transfers", json={"outgoing_id": str(out), "incoming_id": str(into)}
        )
        again = await client.post(
            "/api/finance/transfers", json={"outgoing_id": str(out), "incoming_id": str(into)}
        )
        transfer = linked.json()[0]["transfer"]
        unlinked = await client.delete(f"/api/finance/transfers/{transfer['id']}")
        after = {item["id"]: item for item in await items(client)}

    assert bad.status_code == 422
    assert linked.status_code == 201
    assert transfer["other_account_name"] == "Poupança"
    assert again.status_code == 409
    assert unlinked.status_code == 204
    assert after[str(out)]["kind"] == "expense"
    async with get_sessionmaker()() as session:
        assert await session.get(TransferDismissal, (out, into)) is not None


async def test_marking_a_paired_transaction_as_an_expense_unlinks_it(home: Home) -> None:
    out = await add(home, "-100", 5)
    await add(home, "100", 5, account=home.savings)
    await refresh(home)
    async with api(home.owner) as client:
        assert (await items(client))[0]["kind"] == "transfer"
        updated = await client.patch(f"/api/finance/transactions/{out}", json={"kind": "expense"})

    transaction = updated.json()["transaction"]
    assert (transaction["kind"], transaction["kind_source"]) == ("expense", "manual")
    assert transaction["transfer"] is None


async def test_private_accounts_stay_private(home: Home) -> None:
    secret = await add(home, "-50", 1, account=home.private, counterparty="Joalharia")
    out = await add(home, "-200", 2, account=home.private)
    into = await add(home, "200", 2)  # shared account: a transfer from the private one
    await refresh(home)

    async with api(home.member) as client:
        visible = await items(client)
        refused = await client.patch(f"/api/finance/transactions/{secret}", json={"note": "x"})
        merchants = (await client.get("/api/finance/counterparties")).json()

    assert {item["id"] for item in visible} == {str(into)}
    assert visible[0]["transfer"]["other_account_name"] == "Another household account"
    assert refused.status_code == 404
    assert next(item for item in merchants if item["name"] == "Joalharia")["transactions"] == 0
    assert str(out) not in {item["id"] for item in visible}


async def test_categories(home: Home) -> None:
    transaction = await add(home, "-10", 1, description="VETERINARIO")
    await refresh(home)
    async with api(home.owner) as client:
        group = (await client.post("/api/finance/categories", json={"name": "Animals"})).json()
        vet = (
            await client.post(
                "/api/finance/categories", json={"name": "Vet", "parent_id": group["id"]}
            )
        ).json()
        await client.patch(
            f"/api/finance/transactions/{transaction}", json={"category_id": vet["id"]}
        )
        in_use = await client.delete(f"/api/finance/categories/{vet['id']}")
        moved = await client.patch(
            f"/api/finance/categories/{vet['id']}",
            json={"parent_id": str(home.categories["Family"]), "name": "Veterinarian"},
        )
        empty_group = await client.delete(f"/api/finance/categories/{group['id']}")
        archived = await client.patch(
            f"/api/finance/categories/{home.categories['Leisure']}", json={"archived": True}
        )
        tree = (await client.get("/api/finance/categories")).json()

    assert in_use.status_code == 409
    assert moved.json()["name"] == "Veterinarian"
    assert empty_group.status_code == 204
    assert archived.json()["archived"] is True
    family = next(item for item in tree if item["name"] == "Family")
    leisure = next(item for item in tree if item["name"] == "Leisure")
    assert {"name": "Veterinarian", "transactions": 1}.items() <= next(
        child for child in family["children"] if child["name"] == "Veterinarian"
    ).items()
    assert all(child["archived"] for child in leisure["children"])


async def test_rules_categorize_at_once_and_preview(home: Home) -> None:
    rent = await add(home, "-800", 1, description="TRF RENDA OUTUBRO")
    await add(home, "-800", 1, account=home.private, description="TRF RENDA GARAGEM")
    await refresh(home)
    condition = {"field": "description", "op": "contains", "value": "renda"}
    rule = {
        "name": "Rent",
        "conditions": [condition],
        "actions": [
            {"type": "set_category", "category_id": str(home.categories["Rent & mortgage"])}
        ],
    }
    async with api(home.member) as client:
        preview = (
            await client.post("/api/finance/rules/preview", json={"conditions": [condition]})
        ).json()
        created = await client.post("/api/finance/rules", json=rule)
        categorized = await items(client)
        rules = (await client.get("/api/finance/rules")).json()
        reordered = await client.put(
            "/api/finance/rules-order", json={"ids": [item["id"] for item in reversed(rules)]}
        )
        deleted = await client.delete(f"/api/finance/rules/{created.json()['id']}")
        after = await items(client)

    assert preview["matches"] == 1  # the private account's rent isn't the member's to see
    assert created.status_code == 201
    assert categorized[0]["id"] == str(rent)
    assert (categorized[0]["category"]["name"], categorized[0]["category"]["source"]) == (
        "Rent & mortgage",
        "rule",
    )
    assert reordered.json()[0]["name"] == "Rent"
    assert deleted.status_code == 204
    assert after[0]["category"] is None


async def test_rules_only_point_at_the_households_own_things(home: Home) -> None:
    async with api(home.owner) as client:
        response = await client.post(
            "/api/finance/rules",
            json={
                "name": "Elsewhere",
                "conditions": [{"field": "direction", "op": "is", "value": "out"}],
                "actions": [{"type": "set_category", "category_id": str(uuid.uuid4())}],
            },
        )
        invalid = await client.post(
            "/api/finance/rules",
            json={
                "name": "Broken",
                "conditions": [{"field": "amount", "op": "contains", "value": "1"}],
                "actions": [{"type": "add_tag", "tag": "x"}],
            },
        )

    assert response.status_code == 404
    assert invalid.status_code == 422


async def test_merging_counterparties(home: Home) -> None:
    await add(home, "-5", 1, counterparty="PINGO DOCE LISBOA")
    other = await add(home, "-6", 2, counterparty="Pingo Doce")
    await refresh(home)
    async with api(home.owner) as client:
        source = await counterparty_id(client, "PINGO DOCE LISBOA")
        target = await counterparty_id(client, "Pingo Doce")
        await client.post(
            "/api/finance/rules",
            json={
                "name": "Pingo",
                "conditions": [{"field": "description", "op": "contains", "value": "x"}],
                "actions": [{"type": "set_counterparty", "counterparty_id": source}],
            },
        )
        merged = await client.post(
            f"/api/finance/counterparties/{source}/merge", json={"into_id": target}
        )
        rules = (await client.get("/api/finance/rules")).json()
        by_id = {item["id"]: item for item in await items(client)}

    assert merged.json()["transactions"] == 2
    assert merged.json()["aliases"] == ["pingo doce", "pingo doce lisboa"]
    assert rules[-1]["actions"][0]["counterparty_id"] == target
    assert by_id[str(other)]["counterparty"]["name"] == "Pingo Doce"


async def test_run_rules_now(home: Home) -> None:
    await add(home, "-5", 1, counterparty="Continente")
    async with api(home.owner) as client:
        result = (await client.post("/api/finance/rules/run")).json()

    assert (result["processed"], result["counterparties_created"]) == (1, 1)
