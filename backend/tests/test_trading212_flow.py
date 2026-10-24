"""Linking Trading 212 with `cli t212-link`, syncing it and reading it through the API, against a
fake Trading 212 (ADR-0008, slice T1). Synthetic data only."""

import base64
import json
import re
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from analytics_data import email_of
from households import Home, add, api, make_home
from procrastinate.testing import InMemoryConnector
from sqlalchemy import select

from hubnisio.cli import t212_link
from hubnisio.core.auth import Principal
from hubnisio.core.db import get_sessionmaker
from hubnisio.core.settings import get_settings
from hubnisio.finance import sync
from hubnisio.finance.models import (
    Account,
    AccountOwner,
    Connection,
    ConnectionStatus,
    ProviderName,
    ProviderPayload,
    SyncRun,
)
from hubnisio.finance.providers.trading212.client import Trading212Client
from hubnisio.jobs import app as job_app

pytestmark = pytest.mark.anyio

TODAY = datetime.now(UTC).date()
SUMMARY_PATH = "/api/v0/equity/account/summary"


def moment(days_ago: int) -> str:
    return f"{(TODAY - timedelta(days=days_ago)).isoformat()}T12:00:00.000Z"


def movement(kind: str, amount: float, days_ago: int, reference: str) -> dict[str, Any]:
    return {
        "type": kind,
        "amount": amount,
        "currency": "EUR",
        "dateTime": moment(days_ago),
        "reference": reference,
    }


def dividend(amount: float, days_ago: int, reference: str) -> dict[str, Any]:
    return {
        "amount": amount,
        "amountInEuro": amount,
        "currency": "EUR",
        "paidOn": moment(days_ago),
        "reference": reference,
        "ticker": "VWRL_EQ",
        "instrument": {"ticker": "VWRL_EQ", "name": "Vanguard FTSE All-World"},
        "type": "ORDINARY",
    }


@dataclass
class FakeTrading212:
    """Trading 212 as the hub sees it: answers by path and records every request. History
    comes newest first, two items a page, joined by `nextPagePath`."""

    account_id: int = 4242
    transactions: list[dict[str, Any]] = field(default_factory=list)
    dividends: list[dict[str, Any]] = field(default_factory=list)
    errors: dict[str, httpx.Response] = field(default_factory=dict)  # path -> one-off error
    limited: set[str] = field(default_factory=set)  # paths that always answer 429
    requests: list[httpx.Request] = field(default_factory=list)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path in self.limited:
            return httpx.Response(429)
        if (error := self.errors.pop(path, None)) is not None:
            return error
        if path == SUMMARY_PATH:
            body = {
                "id": self.account_id,
                "currency": "EUR",
                "totalValue": 1234.56,
                "cash": {"availableToTrade": 34.56, "inPies": 0, "reservedForOrders": 0},
                "investments": {"currentValue": 1200, "totalCost": 1100},
            }
            return httpx.Response(200, json=body)
        match = re.fullmatch(r"/api/v0/equity/history/(transactions|dividends)", path)
        if match is None:
            return httpx.Response(404)
        endpoint = match.group(1)
        items = self.transactions if endpoint == "transactions" else self.dividends
        start = int(request.url.params.get("cursor", "0"))
        following = (
            f"/api/v0/equity/history/{endpoint}?limit=50&cursor={start + 2}"
            if start + 2 < len(items)
            else None
        )
        return httpx.Response(
            200, json={"items": items[start : start + 2], "nextPagePath": following}
        )

    def calls(self, endpoint: str) -> list[httpx.Request]:
        return [request for request in self.requests if request.url.path.endswith(endpoint)]


async def _no_sleep(_seconds: float) -> None:
    return None


@dataclass
class Setup:
    home: Home
    t212: FakeTrading212
    jobs: InMemoryConnector
    keys: Path

    def client(self, path: Path) -> Trading212Client:
        return Trading212Client(path, transport=httpx.MockTransport(self.t212), sleep=_no_sleep)

    async def link(self, principal: Principal, key_file: str = "invest") -> int:
        return await t212_link(await email_of(principal), key_file, client_factory=self.client)

    async def sync(
        self, connection_id: uuid.UUID, trigger: sync.SyncTrigger = sync.SyncTrigger.SCHEDULED
    ) -> sync.SyncOutcome:
        return await sync.sync_connection(
            connection_id,
            trigger=trigger,
            client_factory=lambda connection: self.client(self.keys / (connection.key_file or "")),
        )


@pytest.fixture
def setup(home: Home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Setup]:
    (tmp_path / "invest").write_text("key=key-1\nsecret=secret-1\n", encoding="utf-8")
    monkeypatch.setenv("HUBNISIO_TRADING212_KEYS_DIR", str(tmp_path))
    get_settings.cache_clear()
    jobs = InMemoryConnector()
    with job_app.replace_connector(jobs):
        yield Setup(home, FakeTrading212(), jobs, tmp_path)
    get_settings.cache_clear()


async def connection_of(principal: Principal) -> Connection:
    async with get_sessionmaker()() as session:
        connection = await session.scalar(
            select(Connection).where(
                Connection.user_id == principal.user_id,
                Connection.household_id == principal.household_id,
                Connection.provider == ProviderName.TRADING212,
            )
        )
    assert connection is not None
    return connection


async def account_of(principal: Principal) -> Account:
    async with get_sessionmaker()() as session:
        account = await session.scalar(
            select(Account).where(
                Account.household_id == principal.household_id,
                Account.identification_hash == "trading212:4242",
            )
        )
    assert account is not None
    return account


async def test_link_then_sync_brings_in_value_cash_and_dividends(setup: Setup) -> None:
    home = setup.home
    setup.t212.transactions = [
        movement("INTEREST_ON_FREE_CASH", 0.42, 2, "t6"),
        movement("DEPOSIT", 500, 3, "t5"),
        movement("FEE", 0.5, 10, "t4"),
        movement("TRANSFER", -50, 20, "t3"),
        movement("WITHDRAW", 300, 30, "t2"),
        movement("DEPOSIT", 1000, 79, "t1"),
    ]
    setup.t212.dividends = [dividend(3.21, 5, "d1")]
    # The bank's side of the deposits, one older than the sync's usual 60-day lookback.
    recent = await add(home, "-500", 0, on=TODAY - timedelta(days=4), counterparty="Trading 212")
    old = await add(home, "-1000", 0, on=TODAY - timedelta(days=80), counterparty="Trading 212")

    assert await setup.link(home.owner) == 0

    (request,) = setup.t212.requests
    expected = base64.b64encode(b"key-1:secret-1").decode()
    assert request.headers["authorization"] == f"Basic {expected}"
    connection = await connection_of(home.owner)
    assert (connection.status, connection.key_file) == (ConnectionStatus.ACTIVE, "invest")
    assert (connection.institution_name, connection.institution_country) == ("Trading 212", None)
    assert connection.valid_until is None
    account = await account_of(home.owner)
    assert account.is_investment
    assert not account.include_in_net_worth  # until slice T3 builds its value over time
    assert (account.institution_name, account.currency) == ("Trading 212", "EUR")
    (job,) = setup.jobs.jobs.values()
    assert job["task_name"] == "finance:sync_connection"
    assert job["args"] == {
        "connection_id": str(connection.id),
        "trigger": "initial",
        "psu_headers": None,
    }
    async with get_sessionmaker()() as session:
        owners = set(
            await session.scalars(
                select(AccountOwner.user_id).where(AccountOwner.account_id == account.id)
            )
        )
        (summary,) = await session.scalars(
            select(ProviderPayload).where(ProviderPayload.connection_id == connection.id)
        )
    assert owners == {home.owner.user_id}
    assert summary.kind == "summary"
    assert "secret-1" not in json.dumps([summary.request, summary.response])

    outcome = await setup.sync(connection.id, sync.SyncTrigger.INITIAL)

    assert (outcome.succeeded, outcome.failed) == (1, 0)
    async with get_sessionmaker()() as session:
        kinds = list(
            await session.scalars(
                select(ProviderPayload.kind)
                .where(ProviderPayload.sync_run_id.is_not(None))
                .where(ProviderPayload.account_id == account.id)
                .order_by(ProviderPayload.fetched_at, ProviderPayload.id)
            )
        )
    assert kinds == ["summary", "transactions", "transactions", "transactions", "dividends"]

    async with api(home.owner) as client:
        accounts = (await client.get("/api/finance/accounts")).json()
        (listed,) = [item for item in accounts if item["id"] == str(account.id)]
        page = await client.get(
            "/api/finance/transactions", params={"account_id": str(account.id), "limit": 50}
        )
        connections = (await client.get("/api/finance/connections")).json()
        setup.jobs.jobs.clear()  # the worker took the initial sync
        queued = await client.post(f"/api/finance/connections/{connection.id}/sync")

    assert listed["balance"]["balance_type"] == "TVAL"
    assert listed["balance"]["amount"] == "1234.5600"
    assert (listed["is_investment"], listed["include_in_net_worth"]) == (True, False)
    assert listed["name"] == "Trading 212 EUR"

    items = {item["reference"]: item for item in page.json()["items"]}
    assert set(items) == {"t1", "t2", "t3", "t4", "t5", "t6", "d1"}
    assert items["t2"]["amount"] == "-300.0000"  # a withdrawal is money out
    assert items["t4"]["amount"] == "-0.5000"
    assert (items["d1"]["bank_code"], items["d1"]["kind"]) == ("T212_DIVIDEND", "income")
    assert items["d1"]["category"]["name"] == "Dividends"
    assert items["t6"]["category"]["name"] == "Interest"
    assert items["t4"]["category"]["name"] == "Bank fees"
    assert items["t3"]["kind"] == "transfer"  # between Trading 212 accounts, by seeded rule
    # Both deposits paired with the bank's outflows, the old one too: a first sync pairs
    # across all history.
    assert items["t5"]["transfer"]["other_transaction_id"] == str(recent)
    assert items["t1"]["transfer"]["other_transaction_id"] == str(old)
    assert items["t5"]["kind"] == items["t1"]["kind"] == "transfer"

    (listed_connection,) = [item for item in connections if item["id"] == str(connection.id)]
    assert listed_connection["provider"] == "trading212"
    assert listed_connection["key_file"] == "invest"
    assert listed_connection["days_left"] is None
    assert listed_connection["institution_country"] is None
    assert listed_connection["last_error"] is None
    assert (queued.status_code, queued.json()) == (202, {"queued": True})
    (user_job,) = setup.jobs.jobs.values()
    assert user_job["args"]["trigger"] == "user"
    assert user_job["args"]["psu_headers"] is None  # only banks get the user's details


async def test_a_later_sync_pages_back_only_two_weeks(setup: Setup) -> None:
    setup.t212.transactions = [
        movement("DEPOSIT", days, days, f"t{days}") for days in (1, 3, 20, 30, 40, 50)
    ]
    setup.t212.dividends = [dividend(1, days, f"d{days}") for days in (10, 100, 200)]
    assert await setup.link(setup.home.owner) == 0
    connection = await connection_of(setup.home.owner)

    await setup.sync(connection.id, sync.SyncTrigger.INITIAL)
    assert (len(setup.t212.calls("transactions")), len(setup.t212.calls("dividends"))) == (3, 2)

    await setup.sync(connection.id)
    # From 15 days ago (the latest item, minus two weeks): the second page of cash movements
    # reaches back past it, and so does the first page of dividends.
    assert (len(setup.t212.calls("transactions")), len(setup.t212.calls("dividends"))) == (5, 3)


async def test_a_rejected_key_expires_the_connection_until_linked_again(setup: Setup) -> None:
    home = setup.home
    assert await setup.link(home.owner) == 0
    connection = await connection_of(home.owner)
    setup.t212.errors[SUMMARY_PATH] = httpx.Response(401)

    outcome = await setup.sync(connection.id)

    assert outcome.session_ended
    async with api(home.owner) as client:
        (listed,) = [
            item
            for item in (await client.get("/api/finance/connections")).json()
            if item["id"] == str(connection.id)
        ]
        retry = await client.post(f"/api/finance/connections/{connection.id}/sync")
    assert (listed["status"], listed["last_error"]) == ("expired", "KEY_REJECTED")
    assert retry.status_code == 409

    assert await setup.link(home.owner) == 0
    relinked = await connection_of(home.owner)  # one connection: the same one, active again
    assert (relinked.id, relinked.status) == (connection.id, ConnectionStatus.ACTIVE)


async def test_a_rate_limit_that_lasts_fails_the_sync_for_a_retry(setup: Setup) -> None:
    assert await setup.link(setup.home.owner) == 0
    connection = await connection_of(setup.home.owner)
    setup.t212.limited.add("/api/v0/equity/history/transactions")

    outcome = await setup.sync(connection.id)

    assert outcome.rate_limited
    assert outcome.provider is ProviderName.TRADING212
    async with get_sessionmaker()() as session:
        run = await session.scalar(select(SyncRun).where(SyncRun.connection_id == connection.id))
    assert run is not None
    assert run.error_code == "RATE_LIMITED"


async def test_linking_touches_only_the_members_own_household(setup: Setup) -> None:
    other = await make_home()
    assert await setup.link(setup.home.owner) == 0
    assert await setup.link(other.owner) == 0  # the same Trading 212 account, another household

    mine, theirs = await account_of(setup.home.owner), await account_of(other.owner)
    assert mine.id != theirs.id
    assert (mine.household_id, theirs.household_id) == (
        setup.home.owner.household_id,
        other.owner.household_id,
    )
    async with get_sessionmaker()() as session:
        owners = set(
            await session.scalars(
                select(AccountOwner.user_id).where(AccountOwner.account_id == mine.id)
            )
        )
    assert owners == {setup.home.owner.user_id}
    async with api(other.owner) as client:
        accounts = (await client.get("/api/finance/accounts")).json()
    assert str(mine.id) not in [item["id"] for item in accounts]


async def test_t212_link_refuses_what_it_cant_check(
    setup: Setup, capsys: pytest.CaptureFixture[str]
) -> None:
    owner = setup.home.owner
    assert await setup.link(owner, "../invest") == 1
    assert "a file's name" in capsys.readouterr().err
    assert await t212_link("nobody@example.com", "invest", client_factory=setup.client) == 1
    assert await setup.link(owner, "missing") == 1
    assert "Can't read the key file" in capsys.readouterr().err

    setup.t212.errors[SUMMARY_PATH] = httpx.Response(401)
    assert await setup.link(owner) == 1
    assert "rejected the key" in capsys.readouterr().err
    setup.t212.errors[SUMMARY_PATH] = httpx.Response(403)
    assert await setup.link(owner) == 1
    assert "Account data permission" in capsys.readouterr().err

    async with get_sessionmaker()() as session:
        linked = await session.scalar(
            select(Connection.id).where(
                Connection.household_id == owner.household_id,
                Connection.provider == ProviderName.TRADING212,
            )
        )
    assert linked is None
    assert setup.jobs.jobs == {}
