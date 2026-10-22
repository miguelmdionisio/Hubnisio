import json
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from hubnisio.core.settings import Settings
from hubnisio.finance.providers.base import Provider
from hubnisio.finance.providers.enable_banking.client import (
    EnableBankingClient,
    psu_headers_from_request,
)
from hubnisio.finance.providers.enable_banking.errors import (
    AlreadyAuthorized,
    EnableBankingError,
    PaginationError,
    RateLimited,
    SessionEnded,
    WrongPeriod,
)

pytestmark = pytest.mark.anyio

APP_ID = "app-123"
ACCOUNT_UID = "07cc67f4-45d6-494b-adac-09b5cbc7e2b5"


@pytest.fixture(scope="module")
def private_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeEnableBanking:
    """Answers requests from a queue of responses and records what was asked."""

    def __init__(self, *responses: httpx.Response) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.responses.pop(0)

    def params(self, index: int) -> dict[str, str]:
        return dict(self.requests[index].url.params)


def ok(body: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json=body)


def failure(status: int, code: str | None) -> httpx.Response:
    body: dict[str, Any] = {"message": "Something about account 123", "code": status}
    if code is not None:
        body["error"] = code
    return httpx.Response(status, json=body)


@asynccontextmanager
async def client_for(
    fake: FakeEnableBanking,
    private_key: rsa.RSAPrivateKey,
    clock: Callable[[], float] = time.time,
) -> AsyncIterator[EnableBankingClient]:
    transport = httpx.MockTransport(fake)
    async with httpx.AsyncClient(base_url="https://eb.test", transport=transport) as http:
        yield EnableBankingClient(APP_ID, private_key, http=http, clock=clock)


def bearer_token(request: httpx.Request) -> str:
    scheme, _, token = request.headers["Authorization"].partition(" ")
    assert scheme == "Bearer"
    return token


async def test_requests_carry_a_signed_jwt(private_key: rsa.RSAPrivateKey) -> None:
    fake = FakeEnableBanking(ok({"aspsps": []}))
    async with client_for(fake, private_key) as client:
        await client.get_aspsps()

    token = bearer_token(fake.requests[0])
    assert jwt.get_unverified_header(token) == {"alg": "RS256", "typ": "JWT", "kid": APP_ID}
    claims = jwt.decode(
        token,
        private_key.public_key(),
        algorithms=["RS256"],
        audience="api.enablebanking.com",
        issuer="enablebanking.com",
    )
    assert claims["exp"] - claims["iat"] == 3600


async def test_token_is_reused_until_close_to_expiry(private_key: rsa.RSAPrivateKey) -> None:
    now = [1_790_000_000.0]
    fake = FakeEnableBanking(*(ok({"aspsps": []}) for _ in range(3)))
    async with client_for(fake, private_key, clock=lambda: now[0]) as client:
        await client.get_aspsps()
        now[0] += 3000
        await client.get_aspsps()
        now[0] += 400  # within 5 minutes of expiry
        await client.get_aspsps()

    first, second, third = (bearer_token(request) for request in fake.requests)
    assert first == second
    assert third != second


async def test_get_aspsps_parses_banks(private_key: rsa.RSAPrivateKey) -> None:
    fake = FakeEnableBanking(
        ok(
            {
                "aspsps": [
                    {
                        "name": "Banco BPI",
                        "country": "PT",
                        "maximum_consent_validity": 15552000,
                        "psu_types": ["personal", "business"],
                        "required_psu_headers": ["Psu-Ip-Address"],
                        "auth_methods": [],
                    }
                ]
            }
        )
    )
    async with client_for(fake, private_key) as client:
        banks = await client.get_aspsps("PT")

    assert fake.params(0) == {"country": "PT"}
    assert [(bank.name, bank.maximum_consent_validity) for bank in banks] == [
        ("Banco BPI", 15552000)
    ]
    assert banks[0].required_psu_headers == ["Psu-Ip-Address"]


async def test_start_authorization_sends_the_consent_request(
    private_key: rsa.RSAPrivateKey,
) -> None:
    fake = FakeEnableBanking(
        ok({"url": "https://bank.test/auth", "authorization_id": "auth-1", "psu_id_hash": "h"})
    )
    async with client_for(fake, private_key) as client:
        started = await client.start_authorization(
            aspsp_name="Banco BPI",
            country="PT",
            redirect_url="http://localhost:5173/finance/connections/callback",
            state="state-1",
            valid_until=datetime(2027, 4, 20, 12, 0, tzinfo=UTC),
        )

    assert started.url == "https://bank.test/auth"
    assert fake.requests[0].method == "POST"
    assert json.loads(fake.requests[0].content) == {
        "access": {"valid_until": "2027-04-20T12:00:00+00:00"},
        "aspsp": {"name": "Banco BPI", "country": "PT"},
        "state": "state-1",
        "redirect_url": "http://localhost:5173/finance/connections/callback",
        "psu_type": "personal",
    }


async def test_create_session_keeps_the_session_id_out_of_the_payload(
    private_key: rsa.RSAPrivateKey,
) -> None:
    fake = FakeEnableBanking(
        ok(
            {
                "session_id": "secret-session",
                "accounts": [
                    {
                        "uid": ACCOUNT_UID,
                        "identification_hash": "hash-1",
                        "account_id": {"iban": "PT50000000000000000000000"},
                        "currency": "EUR",
                        "cash_account_type": "CACC",
                        "usage": "PRIV",
                    }
                ],
                "aspsp": {"name": "Banco BPI", "country": "PT"},
                "psu_type": "personal",
                "access": {"valid_until": "2027-04-20T12:00:00+00:00"},
            }
        )
    )
    async with client_for(fake, private_key) as client:
        fetched = await client.create_session("code-1")

    assert fetched.data.session_id == "secret-session"
    assert "secret-session" not in json.dumps(fetched.raw)
    assert "code-1" not in json.dumps(fetched.request)
    account = fetched.data.accounts[0]
    assert account.identification_hash == "hash-1"
    assert account.account_id is not None
    assert account.account_id.iban == "PT50000000000000000000000"
    assert fetched.raw["accounts"][0]["usage"] == "PRIV"  # unmodelled fields are kept


async def test_transactions_follow_continuation_keys(private_key: rsa.RSAPrivateKey) -> None:
    fake = FakeEnableBanking(
        ok(
            {
                "transactions": [{"entry_reference": "1"}, {"entry_reference": "2"}],
                "continuation_key": "k1",
            }
        ),
        ok({"transactions": [], "continuation_key": "k2"}),  # empty, but not the end
        ok({"transactions": [{"entry_reference": "3"}], "continuation_key": None}),
    )
    async with client_for(fake, private_key) as client:
        pages = [
            page
            async for page in client.iter_transactions(ACCOUNT_UID, date_from=date(2026, 10, 1))
        ]

    assert len(pages) == 3
    first = {"strategy": "default", "date_from": "2026-10-01"}
    assert fake.params(0) == first
    assert fake.params(1) == {**first, "continuation_key": "k1"}
    assert fake.params(2) == {**first, "continuation_key": "k2"}
    assert pages[1].request["params"]["continuation_key"] == "k1"
    assert fake.requests[0].url.path == f"/accounts/{ACCOUNT_UID}/transactions"


async def test_a_repeated_continuation_key_stops_paging(private_key: rsa.RSAPrivateKey) -> None:
    fake = FakeEnableBanking(
        ok({"transactions": [], "continuation_key": "k1"}),
        ok({"transactions": [], "continuation_key": "k1"}),
    )
    async with client_for(fake, private_key) as client:
        with pytest.raises(PaginationError):
            _ = [page async for page in client.iter_transactions(ACCOUNT_UID)]


async def test_first_fetch_asks_for_the_longest_history(private_key: rsa.RSAPrivateKey) -> None:
    fake = FakeEnableBanking(
        ok(
            {
                "balances": [
                    {
                        "balance_amount": {"currency": "EUR", "amount": "10.50"},
                        "balance_type": "CLBD",
                    }
                ]
            }
        ),
        ok({"transactions": [], "continuation_key": None}),
    )
    async with client_for(fake, private_key) as client:
        fetched = [item async for item in client.fetch(ACCOUNT_UID, since=None)]

    assert [item.kind for item in fetched] == ["balances", "transactions"]
    assert str(fetched[0].data.balances[0].balance_amount.amount) == "10.50"
    assert fake.params(1) == {"strategy": "longest"}


async def test_later_fetches_start_from_since(private_key: rsa.RSAPrivateKey) -> None:
    fake = FakeEnableBanking(
        ok({"balances": []}),
        ok({"transactions": [], "continuation_key": None}),
    )
    async with client_for(fake, private_key) as client:
        _ = [item async for item in client.fetch(ACCOUNT_UID, since=date(2026, 10, 8))]

    assert fake.params(1) == {"strategy": "default", "date_from": "2026-10-08"}


@pytest.mark.parametrize(
    ("status", "code", "expected"),
    [
        (401, "EXPIRED_SESSION", SessionEnded),
        (400, "REVOKED_SESSION", SessionEnded),
        (400, "CLOSED_SESSION", SessionEnded),
        (429, "ASPSP_RATE_LIMIT_EXCEEDED", RateLimited),
        (429, None, RateLimited),
        (422, "WRONG_TRANSACTIONS_PERIOD", WrongPeriod),
        (400, "ALREADY_AUTHORIZED", AlreadyAuthorized),
        (500, "ASPSP_ERROR", EnableBankingError),
    ],
)
async def test_errors_are_mapped_from_their_code(
    private_key: rsa.RSAPrivateKey,
    status: int,
    code: str | None,
    expected: type[EnableBankingError],
) -> None:
    fake = FakeEnableBanking(failure(status, code))
    async with client_for(fake, private_key) as client:
        with pytest.raises(EnableBankingError) as raised:
            await client.get_balances(ACCOUNT_UID)

    assert type(raised.value) is expected
    assert raised.value.status == status
    assert raised.value.code == code
    assert "account 123" not in str(raised.value)


async def test_a_non_json_error_still_raises(private_key: rsa.RSAPrivateKey) -> None:
    fake = FakeEnableBanking(httpx.Response(502, text="Bad gateway"))
    async with client_for(fake, private_key) as client:
        with pytest.raises(EnableBankingError) as raised:
            await client.get_balances(ACCOUNT_UID)

    assert raised.value.code is None
    assert raised.value.status == 502


async def test_psu_headers_are_sent_only_when_given(private_key: rsa.RSAPrivateKey) -> None:
    fake = FakeEnableBanking(ok({"balances": []}), ok({"balances": []}))
    psu = psu_headers_from_request(
        "203.0.113.5", {"User-Agent": "Firefox", "Accept-Language": "pt-PT", "Cookie": "x"}
    )
    async with client_for(fake, private_key) as client:
        await client.get_balances(ACCOUNT_UID)
        fetched = await client.get_balances(ACCOUNT_UID, psu_headers=psu)

    assert psu == {
        "Psu-Ip-Address": "203.0.113.5",
        "Psu-User-Agent": "Firefox",
        "Psu-Accept-language": "pt-PT",
    }
    assert not any(name.lower().startswith("psu-") for name in fake.requests[0].headers)
    assert fake.requests[1].headers["Psu-Ip-Address"] == "203.0.113.5"
    assert "203.0.113.5" not in json.dumps(fetched.request)


def test_from_settings_loads_the_key(tmp_path: Path, private_key: rsa.RSAPrivateKey) -> None:
    key_file = tmp_path / "enable-banking.pem"
    key_file.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    settings = Settings(
        database_url="postgresql://unused",
        enable_banking_app_id=APP_ID,
        enable_banking_key_file=key_file,
    )

    assert isinstance(EnableBankingClient.from_settings(settings), EnableBankingClient)


def test_from_settings_rejects_missing_app_id_and_non_rsa_keys(tmp_path: Path) -> None:
    key_file = tmp_path / "ec.pem"
    key_file.write_bytes(
        ec.generate_private_key(ec.SECP256R1()).private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )

    with pytest.raises(RuntimeError, match="APP_ID is not set"):
        EnableBankingClient.from_settings(
            Settings(database_url="postgresql://unused", enable_banking_app_id="")
        )
    with pytest.raises(RuntimeError, match="not an RSA private key"):
        EnableBankingClient.from_settings(
            Settings(
                database_url="postgresql://unused",
                enable_banking_app_id=APP_ID,
                enable_banking_key_file=key_file,
            )
        )


def test_client_is_a_provider() -> None:
    def as_provider(client: EnableBankingClient) -> Provider:
        return client  # pyright fails here if the client stops matching the protocol

    assert as_provider
