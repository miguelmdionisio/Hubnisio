"""What every data source gives the sync (ADR-0003).

Linking differs too much between sources to share an interface (a bank redirect and consent
for Enable Banking, an API key for Trading 212), so each provider exposes its own. Fetching is
shared: a provider yields raw responses, the sync stores each one in
`finance.provider_payloads`, and a provider-specific normalizer turns them into rows.
"""

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class Fetched[T]:
    """One provider response: what was asked, the raw JSON, and its parsed form."""

    kind: str  # e.g. "balances", "transactions"
    request: dict[str, Any]
    raw: dict[str, Any]
    data: T


class Provider(Protocol):
    def fetch(
        self,
        account_uid: str,
        since: date | None,
        psu_headers: Mapping[str, str] | None = None,
    ) -> AsyncIterator[Fetched[Any]]:
        """Yield every response needed to bring one account up to date.

        `since=None` asks for the longest history the source offers (the first sync).
        `psu_headers` are given only when the user is present and triggered the fetch.
        """
        ...
