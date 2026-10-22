"""Linking, syncing and reading through the API, against a fake Enable Banking."""

import asyncio
import json
import re
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from procrastinate.testing import InMemoryConnector
from sqlalchemy import select
from starlette.requests import Request

from hubnisio.core.auth import Principal, get_principal
from hubnisio.core.crypto import SecretBox
from hubnisio.core.db import get_sessionmaker
from hubnisio.core.models import Household, HouseholdMember, HouseholdRole, User
from hubnisio.finance import api as finance_api
from hubnisio.finance import sync
from hubnisio.finance.ingest.apply import APPLY_FAILED
from hubnisio.finance.ingest.renormalize import renormalize_account
from hubnisio.finance.linking import session_id_context
from hubnisio.finance.models import (
    AccountOwner,
    Connection,
    ConnectionStatus,
    ProviderAccount,
    ProviderPayload,
    SyncRun,
    SyncStatus,
)
from hubnisio.finance.providers.enable_banking.client import EnableBankingClient
from hubnisio.jobs import app as job_app
from hubnisio.main import app

pytestmark = pytest.mark.anyio

APP_ID = "app-test"
BOX = SecretBox({1: bytes(range(32))})
TODAY = datetime.now(UTC).date()
IBAN_1 = "PT50000201231234567890154"
IBAN_2 = "PT50000201231234567890155"


@pytest.fixture(scope="module")
def private_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def ok(body: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json=body)


def failure(status: int, code: str) -> httpx.Response:
    return httpx.Response(status, json={"message": "Failed", "code": status, "error": code})


def bank_account(uid: str, identification_hash: str, iban: str) -> dict[str, Any]:
    return {
        "uid": uid,
        "identification_hash": identification_hash,
        "account_id": {"iban": iban},
        "currency": "EUR",
        "cash_account_type": "CACC",
        "product": "Conta à Ordem",
        "name": "Ana Exemplo",
    }


def balance(balance_type: str, amount: str) -> dict[str, Any]:
    return {"balance_type": balance_type, "balance_amount": {"currency": "EUR", "amount": amount}}


def tx(
    reference: str | None,
    amount: str,
    days_ago: int,
    *,
    status: str = "BOOK",
    direction: str = "DBIT",
    text: str = "COMPRA SUPERMERCADO",
) -> dict[str, Any]:
    day = (TODAY - timedelta(days=days_ago)).isoformat()
    item: dict[str, Any] = {
        "transaction_amount": {"currency": "EUR", "amount": amount},
        "credit_debit_indicator": direction,
        "status": status,
        "transaction_date": day,
        "remittance_information": [text],
    }
    if status == "BOOK":
        item["booking_date"] = day
    if reference:
        item["entry_reference"] = reference
    return item


@dataclass
class FakeBank:
    """Enable Banking as the hub sees it: answers by path and records every request.
    Transactions come in pages of two, joined by continuation keys."""

    session_accounts: list[dict[str, Any]]
    balances: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    transactions: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    errors: dict[str, httpx.Response] = field(default_factory=dict)  # path -> one-off error
    requests: list[httpx.Request] = field(default_factory=list)
    sessions_created: int = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if (error := self.errors.pop(path, None)) is not None:
            return error
        if path == "/aspsps":
            return ok(
                {
                    "aspsps": [
                        {
                            "name": "Banco BPI",
                            "country": "PT",
                            "maximum_consent_validity": 180 * 86400,
                            "psu_types": ["personal"],
                        },
                        {"name": "Banco Empresas", "country": "PT", "psu_types": ["business"]},
                    ]
                }
            )
        if path == "/auth":
            return ok({"url": "https://bank.test/authorize", "authorization_id": "a1"})
        if path == "/sessions":
            self.sessions_created += 1
            return ok(
                {
                    "session_id": f"session-{self.sessions_created}",
                    "accounts": self.session_accounts,
                    "aspsp": {"name": "Banco BPI", "country": "PT"},
                    "psu_type": "personal",
                    "access": {
                        "valid_until": (datetime.now(UTC) + timedelta(days=179)).isoformat()
                    },
                }
            )
        if path.startswith("/sessions/"):
            return ok({})
        match = re.fullmatch(r"/accounts/([^/]+)/(balances|transactions)", path)
        if match is not None:
            uid, kind = match.groups()
            if kind == "balances":
                return ok({"balances": self.balances.get(uid, [])})
            items = self.transactions.get(uid, [])
            start = int(request.url.params.get("continuation_key", "0"))
            following = str(start + 2) if start + 2 < len(items) else None
            return ok({"transactions": items[start : start + 2], "continuation_key": following})
        return httpx.Response(404, json={"message": "Unknown", "error": "NOT_FOUND"})

    def calls(self, pattern: str) -> list[httpx.Request]:
        return [request for request in self.requests if re.fullmatch(pattern, request.url.path)]

    def state(self, index: int = -1) -> str:
        return json.loads(self.calls("/auth")[index].content)["state"]


@dataclass(frozen=True)
class People:
    owner: Principal  # Ana
    member: Principal  # Rui


@pytest.fixture
async def people(migrated_database: str) -> People:
    async with get_sessionmaker()() as session, session.begin():
        ana = User(email=f"ana-{uuid.uuid4().hex[:8]}@example.com", display_name="Ana")
        rui = User(email=f"rui-{uuid.uuid4().hex[:8]}@example.com", display_name="Rui")
        household = Household(name="Casa")
        session.add_all([ana, rui, household])
        await session.flush()
        session.add_all(
            [
                HouseholdMember(
                    household_id=household.id, user_id=ana.id, role=HouseholdRole.OWNER
                ),
                HouseholdMember(
                    household_id=household.id, user_id=rui.id, role=HouseholdRole.MEMBER
                ),
            ]
        )
        result = People(
            owner=Principal(ana.id, household.id, HouseholdRole.OWNER),
            member=Principal(rui.id, household.id, HouseholdRole.MEMBER),
        )
    return result


@dataclass
class Hub:
    bank: FakeBank
    jobs: InMemoryConnector
    private_key: rsa.RSAPrivateKey

    def client(self) -> EnableBankingClient:
        return EnableBankingClient(
            APP_ID, self.private_key, transport=httpx.MockTransport(self.bank)
        )

    @asynccontextmanager
    async def api(self, principal: Principal) -> AsyncIterator[httpx.AsyncClient]:
        app.dependency_overrides[get_principal] = lambda: principal
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                yield client
        finally:
            app.dependency_overrides.pop(get_principal, None)

    async def link(self, principal: Principal) -> dict[str, Any]:
        async with self.api(principal) as client:
            started = await client.post(
                "/api/finance/connections", json={"institution_name": "Banco BPI", "country": "PT"}
            )
            assert started.status_code == 201, started.text
            completed = await client.post(
                "/api/finance/connections/complete",
                json={"code": "code-1", "state": self.bank.state()},
            )
            assert completed.status_code == 200, completed.text
            return completed.json()

    async def sync(
        self, connection: dict[str, Any], trigger: sync.SyncTrigger = sync.SyncTrigger.SCHEDULED
    ) -> sync.SyncOutcome:
        return await sync.sync_connection(
            uuid.UUID(connection["id"]), trigger=trigger, client_factory=self.client
        )


@pytest.fixture
def hub(private_key: rsa.RSAPrivateKey) -> Iterator[Hub]:
    bank = FakeBank(
        session_accounts=[
            bank_account("uid-1", "hash-1", IBAN_1),
            bank_account("uid-2", "hash-2", IBAN_2),
        ]
    )
    jobs = InMemoryConnector()
    hub = Hub(bank, jobs, private_key)

    async def banking() -> AsyncIterator[EnableBankingClient]:
        async with hub.client() as client:
            yield client

    app.dependency_overrides[finance_api.get_enable_banking] = banking
    app.dependency_overrides[finance_api.get_box] = lambda: BOX
    finance_api._bank_cache.clear()  # pyright: ignore[reportPrivateUsage]
    with job_app.replace_connector(jobs):
        yield hub
    app.dependency_overrides.clear()


async def account_for(connection: dict[str, Any], uid: str) -> uuid.UUID:
    async with get_sessionmaker()() as session:
        account_id = await session.scalar(
            select(ProviderAccount.account_id).where(
                ProviderAccount.connection_id == uuid.UUID(connection["id"]),
                ProviderAccount.provider_account_uid == uid,
            )
        )
    assert account_id is not None
    return account_id


async def test_link_sync_and_read(hub: Hub, people: People) -> None:
    ana = people.owner
    async with hub.api(ana) as client:
        banks = (await client.get("/api/finance/banks", params={"country": "PT"})).json()
    assert [bank["name"] for bank in banks] == ["Banco BPI"]  # business-only banks left out

    connection = await hub.link(ana)

    auth = json.loads(hub.bank.calls("/auth")[0].content)
    assert auth["redirect_url"] == "https://localhost:5173/finance/connections/callback"
    consent = datetime.fromisoformat(auth["access"]["valid_until"]) - datetime.now(UTC)
    assert timedelta(days=179) < consent < timedelta(days=180)
    assert connection["status"] == "active"
    assert len(connection["account_ids"]) == 2
    (job,) = hub.jobs.jobs.values()
    assert job["task_name"] == "finance:sync_connection"
    assert job["args"]["trigger"] == "initial"

    async with get_sessionmaker()() as session:
        row = await session.get_one(Connection, uuid.UUID(connection["id"]))
        assert row.session_id_encrypted is not None
        assert BOX.decrypt(row.session_id_encrypted, session_id_context(row.id)) == "session-1"
        payload = await session.scalar(
            select(ProviderPayload).where(
                ProviderPayload.connection_id == row.id, ProviderPayload.kind == "session"
            )
        )
        assert payload is not None
        assert "session-1" not in json.dumps(payload.response)

    hub.bank.balances["uid-1"] = [balance("CLBD", "100.00"), balance("ITAV", "90.00")]
    hub.bank.transactions["uid-1"] = [
        tx("R1", "10.00", 3),
        tx("R2", "5.00", 2),
        tx("R3", "2100.00", 1, direction="CRDT", text="SALARIO OUTUBRO"),
        tx(None, "3.50", 0, status="PDNG"),
    ]
    outcome = await hub.sync(connection, sync.SyncTrigger.INITIAL)

    assert (outcome.succeeded, outcome.failed) == (2, 0)
    transaction_calls = hub.bank.calls(r"/accounts/.+/transactions")
    assert {call.url.params["strategy"] for call in transaction_calls} == {"longest"}
    assert len(hub.bank.calls("/accounts/uid-1/transactions")) == 2  # two pages

    async with hub.api(ana) as client:
        accounts = (await client.get("/api/finance/accounts")).json()
        (with_balance,) = [account for account in accounts if account["balance"]]
        assert with_balance["balance"]["balance_type"] == "ITAV"  # spendable first
        assert with_balance["balance"]["amount"] == "90.0000"
        assert with_balance["iban_masked"] == "PT50 •••• 0154"
        assert with_balance["name"] == "Conta à Ordem"
        assert with_balance["is_owner"] is True

        items: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"limit": 2} | ({"cursor": cursor} if cursor else {})
            page = (await client.get("/api/finance/transactions", params=params)).json()
            items += page["items"]
            cursor = page["next_cursor"]
            if cursor is None:
                break
        assert [item["amount"] for item in items] == ["-3.5000", "2100.0000", "-5.0000", "-10.0000"]

        found = await client.get("/api/finance/transactions", params={"q": "salario"})
        assert [item["amount"] for item in found.json()["items"]] == ["2100.0000"]
        pending = await client.get("/api/finance/transactions", params={"status": "pending"})
        assert [item["status"] for item in pending.json()["items"]] == ["pending"]

        reloaded = await client.post(
            "/api/finance/connections/complete",
            json={"code": "code-1", "state": hub.bank.state()},
        )
        assert reloaded.json()["id"] == connection["id"]
    assert hub.bank.sessions_created == 1
    assert len(hub.jobs.jobs) == 1

    await hub.sync(connection)
    latest = hub.bank.calls("/accounts/uid-1/transactions")[-1]
    expected_from = TODAY - timedelta(days=1) - sync.OVERLAP  # latest booked, minus two weeks
    assert latest.url.params["date_from"] == expected_from.isoformat()
    assert latest.url.params["strategy"] == "default"


async def test_a_joint_account_linked_by_both_partners_is_stored_once(
    hub: Hub, people: People
) -> None:
    ana_connection = await hub.link(people.owner)
    hub.bank.session_accounts = [bank_account("uid-9", "hash-1", IBAN_1)]  # a new session's UID
    rui_connection = await hub.link(people.member)

    (joint_id,) = rui_connection["account_ids"]
    async with get_sessionmaker()() as session:
        owners = set(
            await session.scalars(
                select(AccountOwner.user_id).where(AccountOwner.account_id == uuid.UUID(joint_id))
            )
        )
    assert owners == {people.owner.user_id, people.member.user_id}
    assert joint_id == str(await account_for(ana_connection, "uid-1"))

    async with hub.api(people.member) as client:
        connections = (await client.get("/api/finance/connections")).json()
        accounts = (await client.get("/api/finance/accounts")).json()
    assert [connection["id"] for connection in connections] == [rui_connection["id"]]
    assert len(accounts) == 2  # both of Ana's accounts are shared by default


async def test_private_accounts_are_hidden_from_other_members(hub: Hub, people: People) -> None:
    connection = await hub.link(people.owner)
    hub.bank.transactions["uid-1"] = [tx("R1", "10.00", 1)]
    await hub.sync(connection, sync.SyncTrigger.INITIAL)
    private_id = str(await account_for(connection, "uid-1"))
    url = f"/api/finance/accounts/{private_id}"

    async with hub.api(people.member) as client:
        refused = await client.patch(url, json={"visibility": "private"})
    assert refused.status_code == 404  # only owners can change an account

    async with hub.api(people.owner) as client:
        changed = await client.patch(
            url, json={"visibility": "private", "display_name": "Conta da Ana"}
        )
    assert changed.status_code == 200
    assert (changed.json()["visibility"], changed.json()["name"]) == ("private", "Conta da Ana")

    async with hub.api(people.member) as client:
        accounts = (await client.get("/api/finance/accounts")).json()
        everything = (await client.get("/api/finance/transactions")).json()
        targeted = await client.get("/api/finance/transactions", params={"account_id": private_id})
    assert private_id not in [account["id"] for account in accounts]
    assert everything["items"] == []
    assert targeted.json()["items"] == []

    async with hub.api(people.owner) as client:
        own = (await client.get("/api/finance/transactions")).json()
    assert len(own["items"]) == 1


async def test_an_ended_session_expires_the_connection(hub: Hub, people: People) -> None:
    connection = await hub.link(people.owner)
    hub.bank.errors["/accounts/uid-1/balances"] = failure(401, "EXPIRED_SESSION")

    outcome = await hub.sync(connection)

    assert outcome.session_ended
    assert hub.bank.calls("/accounts/uid-2/.*") == []  # no point trying the other account
    async with hub.api(people.owner) as client:
        (listed,) = (await client.get("/api/finance/connections")).json()
        retry = await client.post(f"/api/finance/connections/{connection['id']}/sync")
    assert (listed["status"], listed["last_error"]) == ("expired", "EXPIRED_SESSION")
    assert retry.status_code == 409


async def test_a_rate_limit_fails_that_account_only(hub: Hub, people: People) -> None:
    connection = await hub.link(people.owner)
    hub.bank.errors["/accounts/uid-1/transactions"] = failure(429, "ASPSP_RATE_LIMIT_EXCEEDED")

    outcome = await hub.sync(connection)

    assert outcome.rate_limited
    assert (outcome.succeeded, outcome.failed) == (1, 1)
    async with get_sessionmaker()() as session:
        failed = await session.scalar(
            select(SyncRun).where(
                SyncRun.account_id == await account_for(connection, "uid-1"),
                SyncRun.status == SyncStatus.FAILED,
            )
        )
    assert failed is not None
    assert failed.error_code == "ASPSP_RATE_LIMIT_EXCEEDED"


async def test_a_period_the_bank_no_longer_has_falls_back_to_the_longest(
    hub: Hub, people: People
) -> None:
    connection = await hub.link(people.owner)
    hub.bank.transactions["uid-1"] = [tx("R1", "10.00", 200)]
    await hub.sync(connection, sync.SyncTrigger.INITIAL)
    hub.bank.errors["/accounts/uid-1/transactions"] = failure(422, "WRONG_TRANSACTIONS_PERIOD")

    outcome = await hub.sync(connection)

    assert outcome.failed == 0
    last = hub.bank.calls("/accounts/uid-1/transactions")[-1]
    assert last.url.params["strategy"] == "longest"


async def test_payloads_survive_a_failed_apply(
    hub: Hub, people: People, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = await hub.link(people.owner)
    hub.bank.transactions["uid-1"] = [tx("R1", "10.00", 1)]

    async def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("parser bug")

    monkeypatch.setattr(sync, "apply_payloads", broken)
    outcome = await hub.sync(connection, sync.SyncTrigger.INITIAL)
    monkeypatch.undo()

    assert outcome.failed == 2
    account_id = await account_for(connection, "uid-1")
    async with get_sessionmaker()() as session, session.begin():
        run = await session.scalar(select(SyncRun).where(SyncRun.account_id == account_id))
        assert run is not None
        assert run.error_code == APPLY_FAILED
        result = await renormalize_account(session, account_id)  # after the "fix"
    assert result.transactions == 1


async def test_closing_a_connection(hub: Hub, people: People) -> None:
    connection = await hub.link(people.owner)

    async with hub.api(people.owner) as client:
        closed = await client.delete(f"/api/finance/connections/{connection['id']}")
        listed = (await client.get("/api/finance/connections")).json()

    assert closed.status_code == 204
    assert [call.method for call in hub.bank.calls("/sessions/session-1")] == ["DELETE"]
    assert listed == []
    async with get_sessionmaker()() as session:
        row = await session.get_one(Connection, uuid.UUID(connection["id"]))
    assert (row.status, row.session_id_encrypted) == (ConnectionStatus.REVOKED, None)


async def test_sync_now_queues_one_sync_at_a_time(hub: Hub, people: People) -> None:
    connection = await hub.link(people.owner)
    hub.jobs.reset()  # forget the initial sync
    url = f"/api/finance/connections/{connection['id']}/sync"

    async with hub.api(people.owner) as client:
        first = await client.post(url)
        second = await client.post(url)
    async with hub.api(people.member) as client:
        not_theirs = await client.post(url)

    assert (first.status_code, first.json()) == (202, {"queued": True})
    assert second.json() == {"queued": False}
    assert not_theirs.status_code == 404
    (job,) = hub.jobs.jobs.values()
    assert (job["args"]["trigger"], job["args"]["psu_headers"]) == ("user", None)


async def test_bad_requests(hub: Hub, people: People) -> None:
    async with hub.api(people.owner) as client:
        unknown_bank = await client.post(
            "/api/finance/connections", json={"institution_name": "Nope", "country": "PT"}
        )
        await client.post(
            "/api/finance/connections", json={"institution_name": "Banco BPI", "country": "PT"}
        )
        bad_cursor = await client.get("/api/finance/transactions", params={"cursor": "%%%"})
    async with hub.api(people.member) as client:
        someone_elses = await client.post(
            "/api/finance/connections/complete", json={"code": "c", "state": hub.bank.state()}
        )
        unknown_state = await client.post(
            "/api/finance/connections/complete", json={"code": "c", "state": "made-up"}
        )

    assert unknown_bank.status_code == 404
    assert bad_cursor.status_code == 400
    assert someone_elses.status_code == 404
    assert unknown_state.status_code == 404
    assert hub.bank.sessions_created == 0


def test_psu_headers_only_for_public_addresses() -> None:
    def request(host: str) -> Request:
        return Request(
            {
                "type": "http",
                "client": (host, 1234),
                "headers": [(b"user-agent", b"Firefox"), (b"accept-language", b"pt-PT")],
            }
        )

    psu = finance_api._psu_headers  # pyright: ignore[reportPrivateUsage]
    assert psu(request("172.18.0.5")) is None
    assert psu(request("127.0.0.1")) is None
    assert psu(request("8.8.8.8")) == {
        "Psu-Ip-Address": "8.8.8.8",
        "Psu-User-Agent": "Firefox",
        "Psu-Accept-language": "pt-PT",
    }


async def test_two_simultaneous_callbacks_link_once(hub: Hub, people: People) -> None:
    async with hub.api(people.owner) as client:
        await client.post(
            "/api/finance/connections", json={"institution_name": "Banco BPI", "country": "PT"}
        )
        body = {"code": "code-1", "state": hub.bank.state()}
        first, second = await asyncio.gather(
            client.post("/api/finance/connections/complete", json=body),
            client.post("/api/finance/connections/complete", json=body),
        )

    assert (first.status_code, second.status_code) == (200, 200)
    assert first.json()["status"] == second.json()["status"] == "active"
    assert hub.bank.sessions_created == 1
    assert len(hub.jobs.jobs) == 1


async def test_linking_again_replaces_the_expired_connection(hub: Hub, people: People) -> None:
    expired = await hub.link(people.owner)
    hub.bank.errors["/accounts/uid-1/balances"] = failure(401, "EXPIRED_SESSION")
    await hub.sync(expired)

    hub.bank.session_accounts = [
        bank_account("uid-3", "hash-1", IBAN_1),
        bank_account("uid-4", "hash-2", IBAN_2),
    ]
    relinked = await hub.link(people.owner)

    async with hub.api(people.owner) as client:
        listed = (await client.get("/api/finance/connections")).json()
    assert [connection["id"] for connection in listed] == [relinked["id"]]
    assert relinked["account_ids"] == expired["account_ids"]


async def test_accounts_without_a_product_name_are_told_apart_by_iban(
    hub: Hub, people: People
) -> None:
    hub.bank.session_accounts = [
        {**bank_account("uid-1", "hash-1", IBAN_1), "product": None},
        {**bank_account("uid-2", "hash-2", IBAN_2), "product": None},
    ]
    await hub.link(people.owner)

    async with hub.api(people.owner) as client:
        names = sorted(
            account["name"] for account in (await client.get("/api/finance/accounts")).json()
        )
    assert names == ["Banco BPI ••0154", "Banco BPI ••0155"]
