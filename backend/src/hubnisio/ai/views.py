"""The `analytics` views loaded into the app's own dataclasses, so the app's pure functions
compute the AI's figures and they match the pages (tests/test_ai.py checks it). The views are
already scoped to the member whose login runs the query."""

import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from psycopg import AsyncConnection

from hubnisio.finance.budgets import BudgetSpec
from hubnisio.finance.fx.convert import (
    BASE_CURRENCY,
    MAX_RATE_AGE_DAYS,
    RateTable,
    rated_currency,
)
from hubnisio.finance.insights.investments import (
    INCOME_CODES,
    Holding,
    InvestmentInputs,
    Totals,
)
from hubnisio.finance.insights.net_worth import Anchor, IncludedAccount, NetWorthInputs
from hubnisio.finance.insights.portfolio import FillMove, Portfolio
from hubnisio.finance.insights.returns import ReturnsInputs, add_movement
from hubnisio.finance.insights.spending import CategoryInfo, MonthlySums, add_months, month_start
from hubnisio.finance.models import CategoryKind, Overspend, TransactionKind
from hubnisio.finance.prices.table import MAX_PRICE_AGE_DAYS, InstrumentInfo, PriceTable
from hubnisio.finance.scoping import View
from hubnisio.health.insights.body import AgeReading, WeighIn
from hubnisio.health.insights.performance import ActivityFacts, ClimbFacts
from hubnisio.health.insights.recovery import DayFacts
from hubnisio.health.insights.recovery_loader import LOOKBACK as RECOVERY_LOOKBACK
from hubnisio.health.insights.sleep import HrvRow, NightRow
from hubnisio.health.insights.training import ActivityRow
from hubnisio.health.sync import today_in

Connection = AsyncConnection[tuple[Any, ...]]


async def monthly_sums(connection: Connection, view: View, first: date, last: date) -> MonthlySums:
    """What `monthly_sums` gives for the months from `first`'s to `last`'s."""
    cursor = await connection.execute(
        "SELECT month, category_id, kind, eur, unconverted FROM analytics.monthly_category_spend"
        " WHERE view = %s AND month BETWEEN %s AND %s",
        [view, month_start(first), month_start(last)],
    )
    sums = MonthlySums()
    for month, category_id, kind, eur, unconverted in await cursor.fetchall():
        sums.add(month, category_id, TransactionKind(kind), eur, unconverted)
    return sums


async def categories(connection: Connection) -> dict[uuid.UUID, CategoryInfo]:
    """What `household_categories` gives: archived categories too."""
    cursor = await connection.execute(
        "SELECT id, name, kind, parent_id, position FROM analytics.categories"
    )
    return {
        id_: CategoryInfo(id_, name, CategoryKind(kind), parent_id, position)
        for id_, name, kind, parent_id, position in await cursor.fetchall()
    }


async def budget_specs(connection: Connection) -> list[BudgetSpec]:
    """The budgets `budgets_for_month` computes: the overall one and those on a category."""
    limits: dict[uuid.UUID, list[tuple[date, Decimal]]] = defaultdict(list)
    cursor = await connection.execute(
        "SELECT budget_id, starts_on, amount FROM analytics.budget_limits"
    )
    for budget_id, starts_on, amount in await cursor.fetchall():
        limits[budget_id].append((starts_on, amount))
    cursor = await connection.execute(
        "SELECT id, category_id, rollover, overspend FROM analytics.budgets"
    )
    return [
        BudgetSpec(category_id, rollover, Overspend(overspend), limits[id_])
        for id_, category_id, rollover, overspend in await cursor.fetchall()
    ]


async def balance_inputs(connection: Connection) -> NetWorthInputs:
    """What `load_inputs` gives, for every account that isn't hidden; `only` with
    `net_worth_accounts` narrows it to a view's net worth."""
    cursor = await connection.execute(
        "SELECT a.id, a.name, a.currency, a.is_investment, b.booked_balance, b.booked_currency,"
        " coalesce(b.reference_date, b.fetched_at::date)"
        " FROM analytics.accounts a LEFT JOIN analytics.balances b ON b.account_id = a.id"
        " WHERE NOT a.hidden ORDER BY a.institution, a.name"
    )
    inputs = NetWorthInputs(accounts=[], anchors={})
    investments: list[uuid.UUID] = []
    for id_, name, currency, is_investment, amount, anchor_currency, on in await cursor.fetchall():
        inputs.accounts.append(IncludedAccount(id_, name, currency))
        if is_investment:
            investments.append(id_)
        elif amount is not None:
            inputs.anchors[id_] = Anchor(amount, anchor_currency, on)
    inputs.portfolios = await portfolios(connection, investments)
    if not inputs.anchors:
        return inputs

    daily: dict[uuid.UUID, dict[date, Decimal]] = defaultdict(dict)
    cursor = await connection.execute(
        "SELECT account_id, occurred_on, amount FROM analytics.daily_movements"
        " WHERE account_id = ANY(%s)",
        [list(inputs.anchors)],
    )
    for account_id, on, amount in await cursor.fetchall():
        daily[account_id][on] = amount
    inputs.daily = dict(daily)
    cursor = await connection.execute(
        "SELECT connection_id, account_id FROM analytics.account_connections"
        " WHERE account_id = ANY(%s)",
        [list(daily)],
    )
    inputs.links = [
        (connection_id, account_id) for connection_id, account_id in await cursor.fetchall()
    ]
    return inputs


async def portfolios(
    connection: Connection, account_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Portfolio]:
    """What `load_portfolios` gives."""
    if not account_ids:
        return {}
    cursor = await connection.execute(
        "SELECT account_id, currency, as_of, cash + cash_in_pies + cash_reserved, total_value"
        " FROM analytics.portfolios WHERE account_id = ANY(%s)",
        [account_ids],
    )
    found = {
        account_id: Portfolio(account_id, currency, as_of, cash, total_value, holdings={})
        for account_id, currency, as_of, cash, total_value in await cursor.fetchall()
    }
    if not found:
        return {}
    ids = list(found)
    cursor = await connection.execute(
        "SELECT account_id, instrument_id, sum(quantity) FROM analytics.holdings"
        " WHERE account_id = ANY(%s) GROUP BY account_id, instrument_id",
        [ids],
    )
    for account_id, instrument_id, quantity in await cursor.fetchall():
        found[account_id].holdings[instrument_id] = quantity
    cursor = await connection.execute(
        "SELECT account_id, instrument_id, filled_at, side, quantity, net_value, taxes"
        " FROM analytics.fills WHERE account_id = ANY(%s) ORDER BY filled_at, id",
        [ids],
    )
    for (
        account_id,
        instrument_id,
        filled_at,
        side,
        quantity,
        net_value,
        taxes,
    ) in await cursor.fetchall():
        found[account_id].fills.append(
            FillMove.of(instrument_id, filled_at, side, quantity, net_value, taxes)
        )
    cursor = await connection.execute(
        "SELECT account_id, occurred_on, amount FROM analytics.daily_movements"
        " WHERE account_id = ANY(%s)",
        [ids],
    )
    for account_id, on, amount in await cursor.fetchall():
        found[account_id].movements[on] = amount
    return found


async def investment_inputs(
    connection: Connection, months: Sequence[date]
) -> list[InvestmentInputs]:
    """What `load_investments` gives: the listed investment accounts, with their income over
    `months`. Holdings may come in another order; `compute_investments` sorts them."""
    cursor = await connection.execute(
        "SELECT id, name, currency FROM analytics.accounts"
        " WHERE is_investment AND NOT hidden ORDER BY institution, name"
    )
    accounts = {
        id_: InvestmentInputs(id_, name, currency)
        for id_, name, currency in await cursor.fetchall()
    }
    if not accounts:
        return []
    ids = list(accounts)
    for account_id, portfolio in (await portfolios(connection, ids)).items():
        accounts[account_id].portfolio = portfolio
    cursor = await connection.execute(
        "SELECT account_id, as_of, total_value, cash + cash_in_pies + cash_reserved,"
        " investments_value, investments_cost, realised_result, unrealised_result"
        " FROM analytics.portfolios WHERE account_id = ANY(%s)",
        [ids],
    )
    for account_id, *totals in await cursor.fetchall():
        accounts[account_id].totals = Totals(*totals)
    cursor = await connection.execute(
        "SELECT h.account_id, i.ticker, i.isin, i.name, i.type, i.currency, h.quantity,"
        " h.average_price, h.current_price, h.value, h.cost, h.unrealised_result"
        " FROM analytics.holdings h JOIN analytics.instruments i ON i.id = h.instrument_id"
        " WHERE h.account_id = ANY(%s)",
        [ids],
    )
    for account_id, *holding in await cursor.fetchall():
        accounts[account_id].holdings.append(Holding(*holding))
    if months:
        cursor = await connection.execute(
            "SELECT account_id, date_trunc('month', occurred_on)::date, bank_code, sum(amount)"
            " FROM analytics.transactions"
            " WHERE account_id = ANY(%s) AND status = 'booked' AND bank_code = ANY(%s)"
            " AND occurred_on >= %s AND occurred_on < %s"
            " GROUP BY 1, 2, 3",
            [
                ids,
                list(INCOME_CODES),
                month_start(months[0]),
                add_months(month_start(months[-1]), 1),
            ],
        )
        for account_id, on, code, total in await cursor.fetchall():
            sums = accounts[account_id].income
            key = (on, INCOME_CODES[code])
            sums[key] = sums.get(key, Decimal(0)) + total
    return list(accounts.values())


async def returns_inputs(
    connection: Connection, accounts: Sequence[InvestmentInputs]
) -> list[ReturnsInputs]:
    """What `load_returns` gives, for the accounts `investment_inputs` loaded."""
    found = {
        account.id: ReturnsInputs(account.id, account.name, account.currency, account.portfolio)
        for account in accounts
    }
    if not found:
        return []
    cursor = await connection.execute(
        "SELECT account_id, occurred_on, bank_code, amount > 0, sum(amount)"
        " FROM analytics.transactions WHERE account_id = ANY(%s) AND status = 'booked'"
        " GROUP BY 1, 2, 3, 4",
        [list(found)],
    )
    for account_id, on, code, money_in, amount in await cursor.fetchall():
        add_movement(found[account_id], on, code, money_in, amount)
    return list(found.values())


async def net_worth_accounts(connection: Connection, view: View) -> set[uuid.UUID]:
    """The accounts net worth counts in `view`, as `listed_counted_account_ids` and
    `include_in_net_worth` give them."""
    cursor = await connection.execute(
        "SELECT id FROM analytics.accounts WHERE NOT hidden AND include_in_net_worth"
        " AND (%s = 'household' OR (is_owner AND NOT is_pot))",
        [view],
    )
    return {id_ for (id_,) in await cursor.fetchall()}


async def rate_table(
    connection: Connection, currencies: Iterable[str], first: date, last: date
) -> RateTable:
    """What `RateTable.load` gives."""
    wanted = {rated_currency(c) for c in currencies} - {BASE_CURRENCY}
    rates: dict[str, list[tuple[date, Decimal]]] = {currency: [] for currency in wanted}
    if wanted:
        cursor = await connection.execute(
            "SELECT currency, rate_date, rate FROM analytics.fx_rates"
            " WHERE currency = ANY(%s) AND rate_date BETWEEN %s AND %s ORDER BY rate_date",
            [list(wanted), first - timedelta(days=MAX_RATE_AGE_DAYS), last],
        )
        for currency, on, rate in await cursor.fetchall():
            rates[currency].append((on, rate))
    return RateTable(rates)


async def price_table(
    connection: Connection, instrument_ids: Iterable[uuid.UUID], first: date, last: date
) -> PriceTable:
    """What `PriceTable.load` gives."""
    ids = list(instrument_ids)
    if not ids:
        return PriceTable({}, {})
    cursor = await connection.execute(
        "SELECT id, ticker, name, currency FROM analytics.instruments WHERE id = ANY(%s)", [ids]
    )
    instruments = {
        id_: InstrumentInfo(ticker, name, currency)
        for id_, ticker, name, currency in await cursor.fetchall()
    }
    prices: dict[uuid.UUID, list[tuple[date, Decimal]]] = {id_: [] for id_ in instruments}
    cursor = await connection.execute(
        "SELECT instrument_id, price_date, price FROM analytics.instrument_prices"
        " WHERE instrument_id = ANY(%s) AND price_date BETWEEN %s AND %s ORDER BY price_date",
        [ids, first - timedelta(days=MAX_PRICE_AGE_DAYS), last],
    )
    for instrument_id, on, price in await cursor.fetchall():
        prices[instrument_id].append((on, price))
    return PriceTable(instruments, prices)


# Health (ADR-0009, H9): the member's own rows only; the views filter on session_user as
# health/scoping.py filters on the principal.


def _float(value: Decimal | float | None) -> float | None:
    return None if value is None else float(value)


async def health_today(connection: Connection) -> date:
    """`today_in` the member's time zone at Garmin, as the Health pages take it."""
    cursor = await connection.execute(
        "SELECT time_zone FROM analytics.health_connection WHERE provider = 'garmin'"
    )
    row = await cursor.fetchone()
    return today_in(row[0] if row else None)


async def activity_rows(connection: Connection) -> list[ActivityRow]:
    """What `load_activity_rows` gives: the activities without multisport parents."""
    cursor = await connection.execute(
        "SELECT start_local, started_at, sport, duration_s, moving_s, distance_m,"
        " elevation_gain_m, hr_load, derived_hr_zone_s FROM analytics.health_activities"
        " WHERE NOT is_parent ORDER BY started_at"
    )
    rows: list[ActivityRow] = []
    for (
        start_local,
        started_at,
        sport,
        duration_s,
        moving_s,
        distance_m,
        climb_m,
        load,
        zones,
    ) in await cursor.fetchall():
        seconds = duration_s or moving_s or 0
        rows.append(
            ActivityRow(
                day=(start_local or started_at).date(),
                sport=sport,
                duration_s=float(seconds),
                distance_m=_float(distance_m),
                climb_m=_float(climb_m),
                load=load,
                zone_s=zones,
            )
        )
    return rows


async def recovery_facts(connection: Connection, today: date, days: int) -> list[DayFacts]:
    """What `load_recovery_facts` gives."""
    start = today - timedelta(days=days - 1 + RECOVERY_LOOKBACK)
    rows: dict[date, dict[str, float | None]] = {}

    def put(day: date, **values: float | None) -> None:
        rows.setdefault(day, {}).update(values)

    cursor = await connection.execute(
        "SELECT day, last_night_avg FROM analytics.health_hrv_nights WHERE day BETWEEN %s AND %s",
        [start, today],
    )
    for day, hrv in await cursor.fetchall():
        put(day, hrv=hrv)
    cursor = await connection.execute(
        "SELECT day, resting_hr, body_battery_charged, body_battery_drained, stress_avg,"
        " rest_stress_s, low_stress_s, medium_stress_s, high_stress_s"
        " FROM analytics.health_daily_summaries WHERE day BETWEEN %s AND %s",
        [start, today],
    )
    for day, resting, charged, drained, stress, rest, low, medium, high in await cursor.fetchall():
        put(
            day,
            resting_hr=resting,
            battery_charged=charged,
            battery_drained=drained,
            stress_avg=stress,
            rest_s=rest,
            low_s=low,
            medium_s=medium,
            high_s=high,
        )
    cursor = await connection.execute(
        "SELECT day, sleep_s, need_minutes FROM analytics.health_sleeps"
        " WHERE day BETWEEN %s AND %s",
        [start, today],
    )
    for day, sleep_s, need in await cursor.fetchall():
        put(day, sleep_s=sleep_s, sleep_need_min=need)
    cursor = await connection.execute(
        "SELECT day, body_battery FROM analytics.health_wake_battery WHERE day BETWEEN %s AND %s",
        [start, today],
    )
    for day, value in await cursor.fetchall():
        put(day, battery_wake=float(value))
    return [DayFacts(day=day, **values) for day, values in sorted(rows.items())]


async def night_days(connection: Connection) -> list[date]:
    """What `load_night_days` gives."""
    cursor = await connection.execute(
        "SELECT day FROM analytics.health_sleeps WHERE sleep_s > 0 ORDER BY day"
    )
    return [day for (day,) in await cursor.fetchall()]


async def nights(connection: Connection, start: date, end: date) -> list[NightRow]:
    """What `load_nights` gives."""
    cursor = await connection.execute(
        "SELECT day, started_at, ended_at, coalesce(utc_offset_minutes, 0), sleep_s, deep_s,"
        " light_s, rem_s, awake_s, awake_count, score, score_qualifier, need_minutes, avg_hr,"
        " avg_respiration, min_respiration, max_respiration, avg_spo2, min_spo2"
        " FROM analytics.health_sleeps WHERE day BETWEEN %s AND %s ORDER BY day",
        [start, end],
    )
    found: list[NightRow] = []
    for row in await cursor.fetchall():
        *head, avg_hr, avg_resp, min_resp, max_resp, avg_spo2, min_spo2 = row
        found.append(
            NightRow(
                *head,
                avg_hr=_float(avg_hr),
                avg_respiration=_float(avg_resp),
                min_respiration=_float(min_resp),
                max_respiration=_float(max_resp),
                avg_spo2=_float(avg_spo2),
                min_spo2=min_spo2,
            )
        )
    return found


async def hrv_nights(connection: Connection, start: date, end: date) -> dict[date, HrvRow]:
    """What `load_hrv_nights` gives."""
    cursor = await connection.execute(
        "SELECT day, last_night_avg, last_night_5min_high FROM analytics.health_hrv_nights"
        " WHERE day BETWEEN %s AND %s",
        [start, end],
    )
    return {day: HrvRow(day, avg, high) for day, avg, high in await cursor.fetchall()}


async def activity_facts(connection: Connection) -> list[ActivityFacts]:
    """What `load_activity_facts` gives."""
    cursor = await connection.execute(
        "SELECT activity_id, start_local, started_at, sport, name, distance_m, duration_s,"
        " elapsed_s, elevation_gain_m, avg_hr, is_parent, parent_id, has_derived,"
        " derived_moving_s, hr_threshold, power_curve, hr_curve, speed_curve, best_efforts,"
        " efficiency_factor, steady, vo2max, climbs"
        " FROM analytics.health_activities ORDER BY started_at"
    )
    out: list[ActivityFacts] = []
    for (
        activity_id,
        start_local,
        started_at,
        sport,
        name,
        distance_m,
        duration_s,
        elapsed_s,
        elevation_gain_m,
        avg_hr,
        is_parent,
        parent_id,
        derived,
        moving_s,
        hr_threshold,
        power_curve,
        hr_curve,
        speed_curve,
        best_efforts,
        efficiency_factor,
        steady,
        vo2max,
        climbs,
    ) in await cursor.fetchall():
        duration = duration_s if duration_s is not None else elapsed_s
        out.append(
            ActivityFacts(
                activity_id=activity_id,
                day=(start_local or started_at).date(),
                sport=sport,
                name=name,
                distance_m=_float(distance_m),
                duration_s=_float(duration),
                elevation_gain_m=_float(elevation_gain_m),
                avg_hr=_float(avg_hr),
                is_parent=is_parent,
                parent_id=parent_id,
                moving_s=moving_s if derived else None,
                hr_threshold=hr_threshold if derived else None,
                power_curve=power_curve if derived else None,
                hr_curve=hr_curve if derived else None,
                speed_curve=speed_curve if derived else None,
                best_efforts=(
                    {int(metres): float(s) for metres, s in best_efforts.items()}
                    if best_efforts
                    else None
                ),
                efficiency_factor=efficiency_factor if derived else None,
                steady=steady if derived else None,
                vo2max=vo2max if derived else None,
                climbs=[
                    ClimbFacts(
                        distance_m=float(c["distance_m"]),
                        gain_m=float(c["gain_m"]),
                        duration_s=float(c["duration_s"]),
                        grade=float(c["grade"]),
                        vam=float(c["vam"]),
                    )
                    for c in climbs or []
                ],
            )
        )
    return out


async def run_zone3_floor(connection: Connection) -> float | None:
    """What `load_run_zone3_floor` gives."""
    cursor = await connection.execute(
        "SELECT sport, zone3_floor FROM analytics.health_heart_rate_zones"
        " WHERE sport IN ('RUNNING', 'DEFAULT')"
    )
    floors = dict(await cursor.fetchall())
    for sport in ("RUNNING", "DEFAULT"):
        if floors.get(sport) is not None:
            return float(floors[sport])
    return None


async def latest_weight(connection: Connection, today: date) -> float | None:
    """What `load_weight` gives."""
    cursor = await connection.execute(
        "SELECT weight_kg FROM analytics.health_weights WHERE day <= %s"
        " ORDER BY measured_at DESC LIMIT 1",
        [today],
    )
    row = await cursor.fetchone()
    return _float(row[0]) if row else None


async def body_facts(
    connection: Connection,
) -> tuple[list[WeighIn], list[AgeReading], float | None]:
    """What `load_body_facts` gives."""
    cursor = await connection.execute(
        "SELECT measured_at, day, weight_kg, bmi, body_fat_pct FROM analytics.health_weights"
    )
    weigh_ins = [
        WeighIn(
            measured_at=measured_at,
            day=day,
            weight_kg=float(weight),
            bmi=_float(bmi),
            body_fat_pct=_float(fat),
        )
        for measured_at, day, weight, bmi, fat in await cursor.fetchall()
    ]
    cursor = await connection.execute(
        "SELECT day, fitness_age, chronological_age, resting_hr, bmi, vigorous_days_avg,"
        " vigorous_minutes_avg FROM analytics.health_fitness_ages"
    )
    readings = [
        AgeReading(
            day=day,
            fitness_age=_float(age),
            chronological_age=chronological,
            resting_hr=resting,
            bmi=_float(bmi),
            vigorous_days_avg=_float(days),
            vigorous_minutes_avg=_float(minutes),
        )
        for day, age, chronological, resting, bmi, days, minutes in await cursor.fetchall()
    ]
    cursor = await connection.execute("SELECT target_kg FROM analytics.health_weight_goal")
    goal = await cursor.fetchone()
    return weigh_ins, readings, _float(goal[0]) if goal else None
