import re
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from itertools import pairwise

import httpx
import pytest
from sqlalchemy import delete, select

from hubnisio import cli
from hubnisio.core.db import get_sessionmaker
from hubnisio.core.models import Household, User
from hubnisio.finance import tasks
from hubnisio.finance.fx.sources import FxClient
from hubnisio.finance.fx.store import (
    RefreshResult,
    currencies_in_use,
    earliest_transaction_day,
    refresh_rates,
    sample_dates,
)
from hubnisio.finance.models import (
    Account,
    BalanceSnapshot,
    Connection,
    ConnectionStatus,
    FxRate,
    FxSource,
    ProviderName,
    ProviderPayload,
    Transaction,
    TransactionStatus,
)

pytestmark = pytest.mark.anyio

# The tests are relative to the real "today", because the CLI and the job read the clock.
TODAY = datetime.now(UTC).date()


def ago(days: int) -> date:
    return TODAY - timedelta(days=days)


ECB_DAYS = [
    day
    for n in range(60, 0, -1)
    if (day := ago(n)).weekday() < 5  # the ECB publishes on business days
]
ECB_BASES = {"GBP": Decimal("0.86"), "CHF": Decimal("0.93"), "USD": Decimal("1.12")}
ECB_HEADER = "KEY,FREQ,CURRENCY,CURRENCY_DENOM,EXR_TYPE,EXR_SUFFIX,TIME_PERIOD,OBS_VALUE,OBS_STATUS"


def ecb_rate(currency: str, day: date) -> Decimal:
    return ECB_BASES[currency] + Decimal(day.day) / 1000


def mad_rate(day: date) -> float:
    return float(f"11.0{day.day % 10}")


class World:
    """The ECB and currency-api as they are today. The ECB publishes GBP, CHF and USD up to
    its last business day, and its MAD series ended years ago. currency-api has a file for
    every day, with the dirham and the dollar in it."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.down: set[str] = set()  # a request whose URL contains any of these gets a 503

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if any(fragment in str(request.url) for fragment in self.down):
            return httpx.Response(503)
        if request.url.host == "data-api.ecb.europa.eu":
            return self.ecb(request)
        match = re.search(r"\d{4}-\d{2}-\d{2}", str(request.url))
        assert match
        day = date.fromisoformat(match[0])
        return httpx.Response(
            200, json={"date": day.isoformat(), "eur": {"mad": mad_rate(day), "usd": 1.12}}
        )

    def ecb(self, request: httpx.Request) -> httpx.Response:
        currency = request.url.path.rsplit("/", 1)[1].split(".")[1]
        params = request.url.params
        if currency == "MAD":
            rows = {date(2020, 10, 30): Decimal("10.7485")} if "lastNObservations" in params else {}
        elif currency in ECB_BASES:
            rows = {day: ecb_rate(currency, day) for day in ECB_DAYS}
            if "lastNObservations" in params:
                rows = {max(rows): rows[max(rows)]}
            else:
                since = date.fromisoformat(params["startPeriod"])
                rows = {day: rate for day, rate in rows.items() if day >= since}
        else:
            return httpx.Response(404, json={"title": "Not Found"})
        lines = [
            f"EXR.D.{currency}.EUR.SP00.A,D,{currency},EUR,SP00,A,{day},{rate},A"
            for day, rate in rows.items()
        ]
        return httpx.Response(200, text="\n".join([ECB_HEADER, *lines]) if lines else "")

    def client(self) -> FxClient:
        return FxClient(transport=httpx.MockTransport(self))

    def currency_api_days(self) -> list[date]:
        """The days asked of currency-api's CDN, in order."""
        return [
            date.fromisoformat(request.url.path.split("@")[2].split("/")[0])
            for request in self.requests
            if request.url.host == "cdn.jsdelivr.net"
        ]

    def ecb_asked(self, currency: str, param: str) -> list[str]:
        return [
            request.url.params[param]
            for request in self.requests
            if request.url.host == "data-api.ecb.europa.eu"
            and f"D.{currency}." in request.url.path
            and param in request.url.params
        ]


@pytest.fixture
async def holdings(migrated_database: str) -> None:
    """A pound account, a dirham account with a balance, and a euro account with a payment
    that was made in Swiss francs; no rates are stored."""
    async with get_sessionmaker()() as session, session.begin():
        await session.execute(delete(FxRate))  # global, shared by every test
        user = User(email=f"fx-{uuid.uuid4().hex[:8]}@example.com", display_name="Ana")
        household = Household(name="Casa")
        session.add_all([user, household])
        await session.flush()
        connection = Connection(
            household_id=household.id,
            user_id=user.id,
            provider=ProviderName.ENABLE_BANKING,
            institution_name="Revolut",
            institution_country="LT",
            status=ConnectionStatus.ACTIVE,
        )
        accounts = {
            currency: Account(
                household_id=household.id, institution_name="Revolut", currency=currency
            )
            for currency in ("GBP", "MAD", "EUR")
        }
        session.add_all([connection, *accounts.values()])
        await session.flush()
        payload = ProviderPayload(
            household_id=household.id,
            connection_id=connection.id,
            kind="transactions",
            request={},
            response={},
        )
        session.add(payload)
        await session.flush()
        session.add_all(
            [
                Transaction(
                    household_id=household.id,
                    account_id=accounts["EUR"].id,
                    status=TransactionStatus.BOOKED,
                    entry_reference=uuid.uuid4().hex,
                    fingerprint=uuid.uuid4().hex,
                    occurrence_index=0,
                    amount=Decimal("-12"),
                    currency="EUR",
                    original_amount=Decimal("-11"),
                    original_currency="CHF",
                    occurred_on=ago(30),
                    payload_id=payload.id,
                ),
                BalanceSnapshot(
                    household_id=household.id,
                    account_id=accounts["MAD"].id,
                    balance_type="ITAV",
                    amount=Decimal("1000"),
                    currency="MAD",
                    reference_date=ago(21),
                ),
            ]
        )


async def refresh(world: World, *, since: date | None = None, today: date = TODAY) -> RefreshResult:
    async with world.client() as client, get_sessionmaker()() as session, session.begin():
        return await refresh_rates(session, client, since=since, today=today)


async def stored(currency: str) -> dict[date, tuple[Decimal, FxSource]]:
    async with get_sessionmaker()() as session:
        rows = await session.execute(
            select(FxRate.on, FxRate.rate, FxRate.source).where(FxRate.quote_currency == currency)
        )
        return {day: (rate, source) for day, rate, source in rows}


def test_sample_dates_are_daily_for_the_last_two_weeks_and_weekly_before() -> None:
    end = date(2026, 10, 22)

    assert sample_dates(date(2026, 10, 22), end) == [end]
    assert sample_dates(date(2026, 10, 20), end) == [date(2026, 10, n) for n in (20, 21, 22)]

    days = sample_dates(date(2026, 8, 1), end)
    daily = [day for day in days if day >= date(2026, 10, 9)]
    assert daily == [date(2026, 10, n) for n in range(9, 23)]  # 14 days, today included
    weekly = [day for day in days if day < date(2026, 10, 9)]
    assert weekly[0] == date(2026, 8, 1)
    assert {(b - a).days for a, b in pairwise(weekly)} == {7}
    # No gap is wider than a week, so every day is within ten days of a rate.
    assert max((b - a).days for a, b in pairwise(days)) == 7


async def test_currencies_in_use_come_from_accounts_transactions_and_snapshots(
    holdings: None,
) -> None:
    async with get_sessionmaker()() as session:
        in_use = await currencies_in_use(session)

    assert {"GBP", "MAD", "CHF"} <= set(in_use)  # an account, a snapshot, an original currency
    assert "EUR" not in in_use
    assert in_use["CHF"] <= ago(30)
    assert in_use["MAD"] <= ago(21)


async def test_first_refresh_takes_each_currency_from_the_source_that_covers_it(
    holdings: None,
) -> None:
    world = World()

    result = await refresh(world)

    async with get_sessionmaker()() as session:
        earliest = await earliest_transaction_day(session)
    assert earliest is not None
    ecb_days = [day for day in ECB_DAYS if day >= earliest]
    for currency in ("GBP", "CHF"):
        assert result.written[(currency, FxSource.ECB)] == len(ecb_days)
        rows = await stored(currency)
        assert sorted(rows) == ecb_days
        assert rows[ecb_days[0]] == (ecb_rate(currency, ecb_days[0]), FxSource.ECB)
    # The ECB's dirham series is stale, so it isn't asked for rates: currency-api supplies them.
    mad_days = sample_dates(earliest, TODAY)
    assert result.written[("MAD", FxSource.CURRENCY_API)] == len(mad_days)
    assert ("MAD", FxSource.ECB) not in result.written
    assert world.ecb_asked("MAD", "startPeriod") == []
    rows = await stored("MAD")
    assert sorted(rows) == mad_days
    assert rows[mad_days[-1]] == (Decimal(str(mad_rate(mad_days[-1]))), FxSource.CURRENCY_API)
    assert result.failed == {}
    assert not any(request.url.path.endswith("/D.EUR.EUR.SP00.A") for request in world.requests)


async def test_refreshing_again_writes_nothing(holdings: None) -> None:
    world = World()
    async with get_sessionmaker()() as session:
        since = await earliest_transaction_day(session)
    await refresh(world, since=since)
    before = {currency: await stored(currency) for currency in ("GBP", "MAD")}
    async with get_sessionmaker()() as session:
        fetched_at = set(await session.scalars(select(FxRate.fetched_at)))
    world.requests.clear()

    result = await refresh(world, since=since)

    assert result.written == {}
    assert world.currency_api_days() == []  # every sampled day is stored already
    assert {currency: await stored(currency) for currency in ("GBP", "MAD")} == before
    async with get_sessionmaker()() as session:
        assert set(await session.scalars(select(FxRate.fetched_at))) == fetched_at


async def test_refresh_fills_the_gap_after_the_last_stored_day(holdings: None) -> None:
    world = World()
    await refresh(world, since=ago(21), today=ago(2))
    last_mad = max(await stored("MAD"))
    assert last_mad == ago(2)
    world.requests.clear()

    result = await refresh(world)

    assert world.currency_api_days() == [ago(1), TODAY]
    assert result.written[("MAD", FxSource.CURRENCY_API)] == 2
    assert sorted(await stored("MAD"))[-3:] == [ago(2), ago(1), TODAY]
    # The ECB has nothing new for the pound and the franc (the next business day isn't out):
    # that's no reason to ask currency-api about them.
    assert ("GBP", FxSource.CURRENCY_API) not in result.written
    assert world.ecb_asked("GBP", "startPeriod") == [str(max(await stored("GBP")) + timedelta(1))]
    assert max(await stored("GBP")) == ECB_DAYS[-1]


async def test_a_changed_rate_is_replaced(holdings: None) -> None:
    day = ECB_DAYS[-1]
    async with get_sessionmaker()() as session, session.begin():
        session.add(
            FxRate(quote_currency="GBP", on=day, rate=Decimal("9"), source=FxSource.CURRENCY_API)
        )

    result = await refresh(World(), since=day)

    assert result.written[("GBP", FxSource.ECB)] == 1
    assert (await stored("GBP"))[day] == (ecb_rate("GBP", day), FxSource.ECB)


async def test_a_failing_currency_does_not_stop_the_others(holdings: None) -> None:
    world = World()
    world.down = {"/D.GBP."}

    result = await refresh(world, since=ago(21))

    assert list(result.failed) == ["GBP"]
    assert "HTTP 503" in result.failed["GBP"]
    assert await stored("GBP") == {}
    assert result.written[("CHF", FxSource.ECB)] > 0
    assert result.written[("MAD", FxSource.CURRENCY_API)] > 0


async def test_a_failure_part_way_keeps_the_rates_fetched_before_it(holdings: None) -> None:
    world = World()
    broken = ago(10)
    world.down = {f"@{broken}", f"{broken}.currency-api"}

    result = await refresh(world, since=ago(21))

    assert list(result.failed) == ["MAD"]
    assert sorted(await stored("MAD")) == [ago(21), ago(14), ago(13), ago(12), ago(11)]
    assert result.written[("MAD", FxSource.CURRENCY_API)] == 5
    assert result.written[("GBP", FxSource.ECB)] > 0

    # Once the file is back, the next run carries on after the last stored day.
    world.down = set()
    world.requests.clear()
    assert (await refresh(world)).failed == {}
    assert world.currency_api_days()[0] == broken
    assert max(await stored("MAD")) == TODAY


async def test_the_cli_backfills_and_reports_what_is_stored(
    holdings: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    world = World()
    monkeypatch.setattr(cli, "FxClient", world.client)

    assert await cli.fx_backfill(ago(21)) == 0

    output = capsys.readouterr().out
    assert f"Fetched rates since {ago(21)}." in output
    assert re.search(r"^GBP \(ecb\): \d+ rows written\.$", output, re.MULTILINE)
    assert re.search(r"^MAD \(currency_api\): \d+ rows written\.$", output, re.MULTILINE)
    rows = len(sample_dates(ago(21), TODAY))
    assert f"Stored MAD (currency_api): {rows} rows, {ago(21)} to {TODAY}." in output
    # Nothing left to do the second time.
    assert await cli.fx_backfill(ago(21)) == 0
    assert "Nothing new to write." in capsys.readouterr().out


async def test_the_cli_exits_with_an_error_when_a_currency_fails(
    holdings: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    world = World()
    world.down = {"/D.CHF."}
    monkeypatch.setattr(cli, "FxClient", world.client)

    assert await cli.fx_backfill(ago(21)) == 1

    assert "CHF failed: data-api.ecb.europa.eu: HTTP 503" in capsys.readouterr().err
    assert await stored("CHF") == {}


async def test_the_daily_job_stores_rates_and_fails_when_a_currency_failed(
    holdings: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = World()
    world.down = {"/D.CHF."}
    monkeypatch.setattr(tasks, "FxClient", world.client)

    with pytest.raises(RuntimeError, match="not fetched for CHF"):
        await tasks.fetch_fx_rates(timestamp=0)

    assert await stored("CHF") == {}
    assert await stored("GBP")  # what was fetched is kept
    assert await stored("MAD")

    world.down = set()
    await tasks.fetch_fx_rates(timestamp=0)  # the next day's run fills the gap
    assert await stored("CHF")
