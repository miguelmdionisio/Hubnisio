"""Run the MCP server on stdio: `python -m hubnisio.ai` (ADR-0006).

It starts only with HUBNISIO_AI_ENABLED=true, and connects as the member login whose connection
string is in HUBNISIO_AI_DSN_FILE (a file `cli ai-login` wrote). Stdout carries the protocol, so
messages go to stderr.
"""

import asyncio
import sys

import anyio
import psycopg

from hubnisio.ai.server import build_server
from hubnisio.core.settings import get_settings


def main() -> int:
    settings = get_settings()
    if not settings.ai_enabled:
        print("AI access is off: set HUBNISIO_AI_ENABLED=true to turn it on.", file=sys.stderr)
        return 1
    if settings.ai_dsn_file is None or not settings.ai_dsn_file.is_file():
        print(
            "Set HUBNISIO_AI_DSN_FILE to a member's AI login file (see `cli ai-login`).",
            file=sys.stderr,
        )
        return 1
    dsn = settings.ai_dsn_file.read_text(encoding="utf-8").strip()
    # psycopg's async mode can't run on the Proactor event loop that Windows uses by default.
    return anyio.run(serve, dsn, backend_options={"loop_factory": asyncio.SelectorEventLoop})


async def serve(dsn: str) -> int:
    # Every view is empty for a login that isn't a member's: say so rather than serve nothing.
    try:
        async with await psycopg.AsyncConnection.connect(dsn) as connection:
            cursor = await connection.execute("SELECT 1 FROM analytics.me")
            member = await cursor.fetchone()
    except psycopg.Error as error:
        print(f"Can't connect as the AI login: {error}", file=sys.stderr)
        return 1
    if member is None:
        print("That login isn't a member's AI login.", file=sys.stderr)
        return 1
    await build_server(dsn).run_stdio_async()
    return 0


if __name__ == "__main__":
    sys.exit(main())
