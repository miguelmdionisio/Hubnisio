"""Enable Banking API client (https://enablebanking.com/docs/api/reference/).

Every call carries an RS256 JWT signed with the application's private key, with `kid` set to
the application ID. Payloads returned for storage never contain the session ID (a secret) or
the PSU headers (the user's IP address and browser details).
"""

import time
from collections.abc import AsyncIterator, Callable, Mapping
from datetime import date, datetime
from types import TracebackType
from typing import Any, Self
from urllib.parse import quote

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from hubnisio.core.settings import Settings
from hubnisio.finance.providers.base import Fetched
from hubnisio.finance.providers.enable_banking.errors import (
    EnableBankingError,
    PaginationError,
    error_for,
)
from hubnisio.finance.providers.enable_banking.schemas import (
    Aspsp,
    AspspList,
    AuthorizationStarted,
    BalanceList,
    Session,
    SessionStatus,
    TransactionsPage,
)

API_URL = "https://api.enablebanking.com"
TOKEN_LIFETIME = 3600  # seconds; Enable Banking rejects tokens valid for over 24 hours
TOKEN_REFRESH_MARGIN = 300
MAX_PAGES = 500
# Browser request headers and the PSU headers they become, for user-triggered fetches.
_PSU_HEADER_SOURCES = {
    "user-agent": "Psu-User-Agent",
    "referer": "Psu-Referer",
    "accept": "Psu-Accept",
    "accept-charset": "Psu-Accept-Charset",
    "accept-encoding": "Psu-Accept-Encoding",
    "accept-language": "Psu-Accept-language",
}


def psu_headers_from_request(ip_address: str, headers: Mapping[str, str]) -> dict[str, str]:
    """The PSU headers for a fetch the user triggered. Their presence lifts the bank's limit
    on unattended fetches; Enable Banking wants all of a bank's required headers or none."""
    psu = {"Psu-Ip-Address": ip_address}
    lowered = {name.lower(): value for name, value in headers.items()}
    for source, target in _PSU_HEADER_SOURCES.items():
        if value := lowered.get(source):
            psu[target] = value
    return psu


class EnableBankingClient:
    def __init__(
        self,
        app_id: str,
        private_key: RSAPrivateKey,
        *,
        http: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._app_id = app_id
        self._private_key = private_key
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(base_url=API_URL, timeout=60, transport=transport)
        self._clock = clock
        self._token: str | None = None
        self._token_expires_at = 0.0

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        if not settings.enable_banking_app_id:
            raise RuntimeError("HUBNISIO_ENABLE_BANKING_APP_ID is not set.")
        key = load_pem_private_key(settings.enable_banking_key_file.read_bytes(), password=None)
        if not isinstance(key, RSAPrivateKey):
            raise RuntimeError(f"{settings.enable_banking_key_file} is not an RSA private key.")
        return cls(settings.enable_banking_app_id, key)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    # Linking

    async def get_aspsps(self, country: str | None = None) -> list[Aspsp]:
        raw = await self._request(
            "GET", "/aspsps", params={"country": country} if country else None
        )
        return AspspList.model_validate(raw).aspsps

    async def start_authorization(
        self,
        *,
        aspsp_name: str,
        country: str,
        redirect_url: str,
        state: str,
        valid_until: datetime,
        psu_type: str = "personal",
    ) -> AuthorizationStarted:
        body = {
            "access": {"valid_until": valid_until.isoformat()},
            "aspsp": {"name": aspsp_name, "country": country},
            "state": state,
            "redirect_url": redirect_url,
            "psu_type": psu_type,
        }
        return AuthorizationStarted.model_validate(await self._request("POST", "/auth", json=body))

    async def create_session(self, code: str) -> Fetched[Session]:
        """Turn the code from the bank's redirect into a session. The stored payload has the
        session ID redacted; `data.session_id` has it, for encrypting."""
        raw = await self._request("POST", "/sessions", json={"code": code})
        session = Session.model_validate(raw)
        redacted = {**raw, "session_id": "[redacted]"}
        return Fetched("session", {"method": "POST", "path": "/sessions"}, redacted, session)

    async def get_session(self, session_id: str) -> SessionStatus:
        raw = await self._request("GET", f"/sessions/{quote(session_id, safe='')}")
        return SessionStatus.model_validate(raw)

    async def delete_session(self, session_id: str) -> None:
        await self._request("DELETE", f"/sessions/{quote(session_id, safe='')}")

    # Data

    async def fetch(
        self,
        account_uid: str,
        since: date | None,
        psu_headers: Mapping[str, str] | None = None,
    ) -> AsyncIterator[Fetched[Any]]:
        """Balances, then transactions from `since`; `None` means the longest history."""
        yield await self.get_balances(account_uid, psu_headers)
        if since is None:
            pages = self.iter_transactions(account_uid, strategy="longest", psu_headers=psu_headers)
        else:
            pages = self.iter_transactions(account_uid, date_from=since, psu_headers=psu_headers)
        async for page in pages:
            yield page

    async def get_balances(
        self, account_uid: str, psu_headers: Mapping[str, str] | None = None
    ) -> Fetched[BalanceList]:
        path = f"/accounts/{quote(account_uid, safe='')}/balances"
        raw = await self._request("GET", path, psu_headers=psu_headers)
        return Fetched(
            "balances", {"method": "GET", "path": path}, raw, BalanceList.model_validate(raw)
        )

    async def iter_transactions(
        self,
        account_uid: str,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
        strategy: str = "default",
        psu_headers: Mapping[str, str] | None = None,
    ) -> AsyncIterator[Fetched[TransactionsPage]]:
        """Every page of transactions. Each follow-up request repeats all parameters unchanged,
        plus the continuation key; a page can be empty and still carry a key."""
        path = f"/accounts/{quote(account_uid, safe='')}/transactions"
        params = {"strategy": strategy}
        if date_from is not None:
            params["date_from"] = date_from.isoformat()
        if date_to is not None:
            params["date_to"] = date_to.isoformat()

        seen_keys: set[str] = set()
        key: str | None = None
        for _ in range(MAX_PAGES):
            page_params = params if key is None else {**params, "continuation_key": key}
            raw = await self._request("GET", path, params=page_params, psu_headers=psu_headers)
            page = TransactionsPage.model_validate(raw)
            yield Fetched(
                "transactions", {"method": "GET", "path": path, "params": page_params}, raw, page
            )
            key = page.continuation_key
            if not key:
                return
            if key in seen_keys:
                raise PaginationError("Enable Banking repeated a continuation key.")
            seen_keys.add(key)
        raise PaginationError(f"Transactions ran past {MAX_PAGES} pages.")

    # Plumbing

    def _authorization(self) -> str:
        now = self._clock()
        if self._token is None or now >= self._token_expires_at - TOKEN_REFRESH_MARGIN:
            issued_at = int(now)
            self._token = jwt.encode(
                {
                    "iss": "enablebanking.com",
                    "aud": "api.enablebanking.com",
                    "iat": issued_at,
                    "exp": issued_at + TOKEN_LIFETIME,
                },
                self._private_key,
                algorithm="RS256",
                headers={"kid": self._app_id},
            )
            self._token_expires_at = issued_at + TOKEN_LIFETIME
        return f"Bearer {self._token}"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        json: dict[str, Any] | None = None,
        psu_headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        headers = {"Authorization": self._authorization(), **(psu_headers or {})}
        response = await self._http.request(method, path, params=params, json=json, headers=headers)
        if response.is_error:
            raise _error_from(response)
        if not response.content:
            return {}
        body = response.json()
        if not isinstance(body, dict):
            raise EnableBankingError(response.status_code, None, "Expected a JSON object.")
        return body


def _error_from(response: httpx.Response) -> EnableBankingError:
    try:
        body = response.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        return error_for(response.status_code, None, response.reason_phrase)
    code = body.get("error")
    message = body.get("message")
    return error_for(
        response.status_code,
        code if isinstance(code, str) else None,
        message if isinstance(message, str) else response.reason_phrase,
    )
