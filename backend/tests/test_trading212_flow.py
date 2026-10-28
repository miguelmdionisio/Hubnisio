"""Linking Trading 212 with `cli t212-link`, syncing it and reading it through the API, against a
fake Trading 212 (ADR-0008, slices T1 to T3). Synthetic data only."""

import base64
import json
import re
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from analytics_data import email_of
from households import Home, add, api, make_home
from procrastinate.testing import InMemoryConnector
from sqlalchemy import func, select, update

from hubnisio.cli import t212_link
from hubnisio.core.auth import Principal
from hubnisio.core.db import get_sessionmaker
from hubnisio.core.settings import get_settings
from hubnisio.finance import sync
from hubnisio.finance.ingest.renormalize import renormalize_account
from hubnisio.finance.models import (
    Account,
    AccountOwner,
    AccountVisibility,
    Connection,
    ConnectionStatus,
    Fill,
    HoldingSnapshot,
    Instrument,
    InstrumentPrice,
    PortfolioSnapshot,
    PriceSource,
    ProviderName,
    ProviderPayload,
    SyncRun,
    Transaction,
)
from hubnisio.finance.providers.trading212.client import Trading212Client
from hubnisio.jobs import app as job_app

pytestmark = pytest.mark.anyio

TODAY = datetime.now(UTC).date()
SUMMARY_PATH = "/api/v0/equity/account/summary"
POSITIONS_PATH = "/api/v0/equity/positions"
INSTRUMENTS_PATH = "/api/v0/equity/metadata/instruments"
# Synthetic instruments: tickers no real one has.
INSTRUMENTS = {
    "XWLD_EQ": {"ticker": "XWLD_EQ", "isin": "XS0000000001", "name": "Test World ETF"},
    "XACM_US_EQ": {"ticker": "XACM_US_EQ", "isin": "XS0000000002", "name": "Acme Test Inc"},
    "XEUR_EQ": {"ticker": "XEUR_EQ", "isin": "XS0000000003", "name": "Test Euro ETF"},
}


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


def filled(
    fill_id: int,
    ticker: str,
    days_ago: int,
    quantity: float = 1,
    side: str = "BUY",
    *,
    currency: str = "USD",
    fx_rate: float = 1.25,
) -> dict[str, Any]:
    """An order with its fill, at 100 a share in `currency`. The net value comes positive
    both ways, as Trading 212 sends it."""
    return {
        "order": {
            "id": fill_id + 1000,
            "createdAt": moment(days_ago),
            "status": "FILLED",
            "side": side,
            "type": "MARKET",
            "initiatedFrom": "AUTOINVEST",
            "ticker": ticker,
            "instrument": {**INSTRUMENTS[ticker], "currency": currency},
        },
        "fill": {
            "id": fill_id,
            "filledAt": moment(days_ago),
            "quantity": quantity,
            "price": 100,
            "type": "TRADE",
            "walletImpact": {
                "currency": "EUR",
                "fxRate": fx_rate,
                "netValue": abs(quantity) * 100 / fx_rate,
                "realisedProfitLoss": 0,
                "taxes": [{"name": "CURRENCY_CONVERSION_FEE", "quantity": 0.12, "currency": "EUR"}],
            },
        },
    }


def held(
    ticker: str,
    quantity: float,
    value: float,
    cost: float,
    *,
    currency: str = "USD",
    price: float = 110,
) -> dict[str, Any]:
    return {
        "instrument": {**INSTRUMENTS[ticker], "currency": currency},
        "quantity": quantity,
        "averagePricePaid": 100,
        "currentPrice": price,
        "walletImpact": {
            "currency": "EUR",
            "currentValue": value,
            "totalCost": cost,
            "unrealizedProfitLoss": value - cost,
        },
    }


@dataclass
class FakeTrading212:
    """Trading 212 as the hub sees it: answers by path and records every request. History
    comes newest first, two items a page, joined by `nextPagePath`."""

    account_id: int = 4242
    total_value: float = 1234.56
    cash: float = 34.56
    transactions: list[dict[str, Any]] = field(default_factory=list)
    dividends: list[dict[str, Any]] = field(default_factory=list)
    orders: list[dict[str, Any]] = field(default_factory=list)
    positions: list[dict[str, Any]] = field(default_factory=list)
    # The instrument list: every instrument offered, held or not.
    instruments: list[dict[str, Any]] = field(
        default_factory=lambda: [
            {"ticker": "XWLD_EQ", "currencyCode": "USD", "type": "ETF"},
            {"ticker": "XACM_US_EQ", "currencyCode": "USD", "type": "STOCK"},
            {"ticker": "XOTH_EQ", "currencyCode": "EUR", "type": "ETF"},
        ]
    )
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
                "totalValue": self.total_value,
                "cash": {"availableToTrade": self.cash, "inPies": 0, "reservedForOrders": 0},
                "investments": {"currentValue": 1200, "totalCost": 1100},
            }
            return httpx.Response(200, json=body)
        if path == POSITIONS_PATH:
            return httpx.Response(200, json=self.positions)
        if path == INSTRUMENTS_PATH:
            return httpx.Response(200, json=self.instruments)
        match = re.fullmatch(r"/api/v0/equity/history/(transactions|dividends|orders)", path)
        if match is None:
            return httpx.Response(404)
        endpoint = match.group(1)
        items = {
            "transactions": self.transactions,
            "dividends": self.dividends,
            "orders": self.orders,
        }[endpoint]
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
    assert kinds == [
        "summary",
        "positions",
        "transactions",
        "transactions",
        "transactions",
        "dividends",
        "orders",
    ]  # no instrument list: nothing is held or traded

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
    # With no bank side to pair with, still a transfer: by seeded rule.
    assert (items["t2"]["kind"], items["t2"]["transfer"]) == ("transfer", None)
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


async def investments_of(principal: Principal, **params: Any) -> dict[str, Any]:
    async with api(principal) as client:
        response = await client.get("/api/finance/investments", params=params)
    assert response.status_code == 200
    return response.json()


async def returns_of(principal: Principal, **params: Any) -> dict[str, Any]:
    async with api(principal) as client:
        response = await client.get("/api/finance/investments/returns", params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def test_a_sync_brings_in_fills_and_holdings_for_the_investments_page(setup: Setup) -> None:
    home, t212 = setup.home, setup.t212
    t212.positions = [held("XACM_US_EQ", 4, 400, 400), held("XWLD_EQ", 7, 800, 700)]
    t212.orders = [
        filled(3, "XACM_US_EQ", 5, 4),
        {**filled(9, "XWLD_EQ", 6), "fill": None},  # cancelled
        filled(2, "XWLD_EQ", 40, 3),
        filled(1, "XWLD_EQ", 70, 4),
    ]
    this_month = TODAY.replace(day=1)
    last_month = (this_month - timedelta(days=1)).replace(day=1)
    t212.transactions = [
        movement("INTEREST_ON_FREE_CASH", 0.42, (TODAY - this_month).days, "t3"),
        movement("LENDING_INTEREST", 0.1, (TODAY - last_month).days, "t2"),
        movement("DEPOSIT", 1100, 80, "t1"),
    ]
    t212.dividends = [dividend(3.21, (TODAY - this_month).days, "d1")]
    assert await setup.link(home.owner) == 0
    connection = await connection_of(home.owner)
    account = await account_of(home.owner)

    await setup.sync(connection.id, sync.SyncTrigger.INITIAL)

    async with get_sessionmaker()() as session:
        fills = list(
            await session.scalars(
                select(Fill).where(Fill.account_id == account.id).order_by(Fill.fill_id)
            )
        )
        transactions = await session.scalar(
            select(func.count())
            .select_from(Transaction)
            .where(Transaction.account_id == account.id)
        )
        instruments = {
            instrument.ticker: instrument
            for instrument in await session.scalars(
                select(Instrument).where(
                    Instrument.ticker.in_(["XWLD_EQ", "XACM_US_EQ", "XOTH_EQ"])
                )
            )
        }
        stored = (
            await session.scalars(
                select(ProviderPayload).where(
                    ProviderPayload.account_id == account.id, ProviderPayload.kind == "instruments"
                )
            )
        ).one()
    assert [fill.fill_id for fill in fills] == [1, 2, 3]
    first = fills[0]
    assert (first.side, first.fill_type, first.quantity, first.price) == ("BUY", "TRADE", 4, 100)
    assert (first.currency, first.net_value, first.fx_rate) == ("EUR", 320, Decimal("1.25"))
    assert first.taxes == [
        {"name": "CURRENCY_CONVERSION_FEE", "amount": "0.12", "currency": "EUR", "charged_at": None}
    ]
    assert transactions == 4  # trades aren't transactions: cash movements and the dividend only
    assert set(instruments) == {"XWLD_EQ", "XACM_US_EQ"}  # only what's held or traded
    assert (instruments["XWLD_EQ"].type, instruments["XWLD_EQ"].name) == ("ETF", "Test World ETF")
    assert (instruments["XACM_US_EQ"].type, instruments["XACM_US_EQ"].isin) == (
        "STOCK",
        "XS0000000002",
    )
    assert [item["ticker"] for item in stored.response["items"]] == ["XWLD_EQ", "XACM_US_EQ"]

    body = await investments_of(home.owner)

    assert body["months"][-1] == this_month.isoformat()
    assert len(body["months"]) == 12
    (shown,) = body["accounts"]
    assert (shown["id"], shown["name"], shown["currency"]) == (
        str(account.id),
        "Trading 212 EUR",
        "EUR",
    )
    assert shown["as_of"] is not None
    assert (shown["value"], shown["cash"], shown["cost"]) == ("1234.56", "34.56", "1100.00")
    assert shown["result"] == "100.00"  # the summary gives no result: value less cost
    assert [holding["ticker"] for holding in shown["holdings"]] == ["XWLD_EQ", "XACM_US_EQ"]
    world, acme = shown["holdings"]
    assert (world["name"], world["type"], world["instrument_currency"]) == (
        "Test World ETF",
        "ETF",
        "USD",
    )
    assert (world["value"], world["cost"], world["result"]) == ("800.00", "700.00", "100.00")
    assert (world["weight"], acme["weight"]) == ("0.6667", "0.3333")
    assert Decimal(world["quantity"]) == 7
    assert Decimal(world["current_price"]) == 110
    assert shown["dividends"][-1] == "3.21"
    assert shown["interest"][-2:] == ["0.10", "0.42"]
    assert set(shown["dividends"][:-1]) == {"0.00"}


async def test_another_members_private_investment_account_never_shows(setup: Setup) -> None:
    home = setup.home
    setup.t212.positions = [held("XWLD_EQ", 1, 110, 100)]
    assert await setup.link(home.owner) == 0
    await setup.sync((await connection_of(home.owner)).id, sync.SyncTrigger.INITIAL)
    account = await account_of(home.owner)

    assert len((await investments_of(home.member))["accounts"]) == 1  # shared, by default
    async with get_sessionmaker()() as session, session.begin():
        await session.execute(
            update(Account)
            .where(Account.id == account.id)
            .values(visibility=AccountVisibility.PRIVATE)
        )

    assert (await investments_of(home.member))["accounts"] == []
    (mine,) = (await investments_of(home.owner))["accounts"]
    assert [holding["ticker"] for holding in mine["holdings"]] == ["XWLD_EQ"]


async def test_orders_page_back_two_weeks_from_the_latest_fill(setup: Setup) -> None:
    setup.t212.transactions = [movement("DEPOSIT", 500, 1, "t1")]
    assert await setup.link(setup.home.owner) == 0
    connection = await connection_of(setup.home.owner)
    await setup.sync(connection.id, sync.SyncTrigger.INITIAL)
    assert len(setup.t212.calls("orders")) == 1

    # Trades the hub hasn't seen, on an account it already has cash movements for: with no
    # fill stored yet, every order is read, however old.
    setup.t212.orders = [
        filled(fill_id, "XWLD_EQ", days) for fill_id, days in enumerate((1, 3, 20, 30, 40, 200))
    ]
    await setup.sync(connection.id)
    assert len(setup.t212.calls("orders")) == 1 + 3

    await setup.sync(connection.id)
    # From 15 days ago (the latest fill, minus two weeks): the second page reaches back past it.
    assert len(setup.t212.calls("orders")) == 1 + 3 + 2
    async with get_sessionmaker()() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(Fill)
            .where(Fill.account_id == (await account_of(setup.home.owner)).id)
        )
    assert count == 6


async def test_the_latest_sync_is_the_anchor_and_renormalize_rebuilds_it(setup: Setup) -> None:
    home, t212 = setup.home, setup.t212
    t212.positions = [held("XWLD_EQ", 2, 220, 200)]
    t212.orders = [filled(1, "XWLD_EQ", 10, 2)]
    assert await setup.link(home.owner) == 0
    connection = await connection_of(home.owner)
    account = await account_of(home.owner)
    await setup.sync(connection.id, sync.SyncTrigger.INITIAL)

    # Everything sold since: the latest sync has no positions, and that's what shows.
    t212.positions = []
    t212.orders = [filled(2, "XWLD_EQ", 1, 2, side="SELL"), *t212.orders]
    await setup.sync(connection.id)

    (shown,) = (await investments_of(home.owner))["accounts"]
    assert shown["holdings"] == []

    async with get_sessionmaker()() as session, session.begin():
        result = await renormalize_account(session, account.id)
    assert result.fills == 2
    async with get_sessionmaker()() as session:
        snapshots = await session.scalar(
            select(func.count())
            .select_from(PortfolioSnapshot)
            .where(PortfolioSnapshot.account_id == account.id)
        )
        holdings = await session.scalar(
            select(func.count())
            .select_from(HoldingSnapshot)
            .where(HoldingSnapshot.account_id == account.id)
        )
        sides = list(
            await session.scalars(
                select(Fill.side).where(Fill.account_id == account.id).order_by(Fill.fill_id)
            )
        )
    assert (snapshots, holdings, sides) == (2, 1, ["BUY", "SELL"])
    assert (await investments_of(home.owner))["accounts"][0]["holdings"] == []


async def test_an_account_not_synced_since_holdings_came_shows_no_figures(setup: Setup) -> None:
    assert await setup.link(setup.home.owner) == 0  # linked, but its first sync hasn't run

    (shown,) = (await investments_of(setup.home.owner, months=3))["accounts"]

    assert (shown["as_of"], shown["value"], shown["cash"], shown["holdings"]) == (
        None,
        None,
        None,
        [],
    )
    assert shown["dividends"] == ["0.00"] * 3


async def test_the_value_rebuilt_from_trades_is_checked_and_counts_in_net_worth(
    setup: Setup,
) -> None:
    home, t212 = setup.home, setup.t212
    # In euros, so no exchange rate is needed. Deposited 1000; bought 4 at 100, sold 1 (its
    # quantity negative, as Trading 212 sends it), bought 4 more: 7 held at 110 and 300 cash.
    euros = {"currency": "EUR", "fx_rate": 1}
    t212.positions = [held("XEUR_EQ", 7, 770, 700, currency="EUR")]
    t212.orders = [
        filled(3, "XEUR_EQ", 5, 4, **euros),
        filled(2, "XEUR_EQ", 20, -1, side="SELL", **euros),
        filled(1, "XEUR_EQ", 40, 4, **euros),
    ]
    t212.transactions = [movement("DEPOSIT", 1000, 50, "t1")]
    t212.cash, t212.total_value = 300, 1070
    t212.instruments = [{"ticker": "XEUR_EQ", "currencyCode": "EUR", "type": "ETF"}]
    assert await setup.link(home.owner) == 0
    connection = await connection_of(home.owner)
    account = await account_of(home.owner)

    await setup.sync(connection.id, sync.SyncTrigger.INITIAL)

    async with get_sessionmaker()() as session:
        instrument = await session.scalar(
            select(Instrument.id).where(Instrument.ticker == "XEUR_EQ")
        )
        prices = {
            on: (price, source)
            for on, price, source in await session.execute(
                select(InstrumentPrice.on, InstrumentPrice.price, InstrumentPrice.source).where(
                    InstrumentPrice.instrument_id == instrument
                )
            )
        }
    assert prices[TODAY] == (110, PriceSource.TRADING212)
    for days_ago in (5, 20, 40):
        assert prices[TODAY - timedelta(days=days_ago)] == (100, PriceSource.FILL)

    (shown,) = (await investments_of(home.owner))["accounts"]
    assert shown["check"] == {
        "on": TODAY.isoformat(),
        "rebuilt_value": "1070.00",
        "difference": "0.00",
        "unpriced": [],
        "unexplained_cash": "0.00",
        "unexplained": [],
    }

    async with api(home.owner) as client:
        included = await client.patch(
            f"/api/finance/accounts/{account.id}", json={"include_in_net_worth": True}
        )
        assert included.status_code == 200, included.text
        worth = (await client.get("/api/finance/insights/net-worth")).json()
    points = {point["on"]: point["amount"] for point in worth["points"]}
    assert min(points) == (TODAY - timedelta(days=50)).isoformat()  # its first movement
    assert points[TODAY.isoformat()] == "1070.00"
    # 4 shares at the price of 10 days before; after that none is recent enough: left out.
    assert points[(TODAY - timedelta(days=30)).isoformat()] == "1000.00"
    assert points[(TODAY - timedelta(days=25)).isoformat()] == "600.00"
    assert worth["unpriced"] > 0

    # A 2-for-1 split the order history doesn't show: the check says so.
    t212.positions = [held("XEUR_EQ", 14, 770, 700, currency="EUR", price=55)]
    await setup.sync(connection.id)
    (shown,) = (await investments_of(home.owner))["accounts"]
    assert shown["check"]["unexplained"] == [
        {"ticker": "XEUR_EQ", "name": "Test Euro ETF", "quantity": "7.0000000000"}
    ]
    assert (shown["check"]["rebuilt_value"], shown["check"]["difference"]) == ("1070.00", "0.00")


async def test_returns_break_down_the_result_of_what_the_sync_brought_in(setup: Setup) -> None:
    """Deposited 1000 and withdrew 100; bought 4 at 100, sold 1, bought 4 more, each with a
    0.12 fee; 2.00 of interest, a 0.50 dividend and a 1.00 fee. Today: 7 at 110, 201.50 cash."""
    home, t212 = setup.home, setup.t212
    euros = {"currency": "EUR", "fx_rate": 1}
    t212.positions = [held("XEUR_EQ", 7, 770, 700, currency="EUR")]
    t212.orders = [
        filled(3, "XEUR_EQ", 5, 4, **euros),
        filled(2, "XEUR_EQ", 20, -1, side="SELL", **euros),
        filled(1, "XEUR_EQ", 40, 4, **euros),
    ]
    t212.transactions = [
        movement("DEPOSIT", 1000, 50, "t1"),
        movement("WITHDRAW", -100, 10, "t2"),
        movement("INTEREST_ON_FREE_CASH", 2, 3, "t3"),
        movement("FEE", -1, 3, "t4"),
    ]
    t212.dividends = [dividend(0.5, 3, "d1")]
    t212.cash, t212.total_value = 201.50, 971.50
    t212.instruments = [{"ticker": "XEUR_EQ", "currencyCode": "EUR", "type": "ETF"}]
    assert await setup.link(home.owner) == 0
    await setup.sync((await connection_of(home.owner)).id, sync.SyncTrigger.INITIAL)
    account = await account_of(home.owner)

    (shown,) = (await returns_of(home.owner))["accounts"]

    assert (shown["id"], shown["date_from"]) == (
        str(account.id),
        (TODAY - timedelta(days=50)).isoformat(),
    )
    assert (shown["start_value"], shown["end_value"]) == ("0.00", "971.50")
    assert (shown["deposits"], shown["withdrawals"], shown["net_deposits"]) == (
        "1000.00",
        "-100.00",
        "900.00",
    )
    # Cost 399.88 for 4, the fees apart; one sold for 100.12 against 99.97 of it. The 7 left
    # cost 699.79 and are worth 770.
    assert shown["breakdown"] == {
        "unrealised": "70.21",
        "realised": "0.15",
        "dividends": "0.50",
        "interest": "2.00",
        "fees": "-1.36",
        "other": "0.00",
        "total": "71.50",
    }
    assert shown["time_weighted"] is not None and shown["money_weighted"] is not None
    assert (shown["time_weighted_gap"], shown["money_weighted_gap"]) == (None, None)
    # Only the fills' prices before today's, each good for 10 days: 9 days with 4 shares and
    # 4 with 3 have none.
    assert shown["unpriced"] == 13
    assert shown["points"][-1]["value"] == "971.50"
    assert shown["points"][-1]["net_deposits"] == "900.00"

    async with api(home.owner) as client:
        backwards = await client.get(
            "/api/finance/investments/returns",
            params={"date_from": TODAY.isoformat(), "date_to": "2020-01-01"},
        )
    assert backwards.status_code == 422

    # Another member's private account never shows.
    assert len((await returns_of(home.member))["accounts"]) == 1
    async with get_sessionmaker()() as session, session.begin():
        await session.execute(
            update(Account)
            .where(Account.id == account.id)
            .values(visibility=AccountVisibility.PRIVATE)
        )
    assert (await returns_of(home.member))["accounts"] == []
