"""The job queue, shared by the API (which defers jobs) and the worker (which runs them).

Modules define their tasks on a `procrastinate.Blueprint`; register each one here. A blueprint
can only be registered once, which is why both entrypoints import this one app.
"""

from typing import Any

import procrastinate
from procrastinate import builtin_tasks
from procrastinate.job_context import JobContext
from psycopg_pool import AsyncConnectionPool

from hubnisio.core.settings import get_settings
from hubnisio.finance import tasks as finance_tasks


def _pool(**kwargs: Any) -> AsyncConnectionPool:
    # Read the database URL when the queue opens, not at import, so importing the API
    # (e.g. to export its OpenAPI schema) needs no database configuration.
    return AsyncConnectionPool(conninfo=get_settings().database_url, **kwargs)


# The queue's tables live in their own "procrastinate" schema (see migration 0002).
app = procrastinate.App(
    connector=procrastinate.PsycopgConnector(
        pool_factory=_pool,
        kwargs={"options": "-c search_path=procrastinate"},
    ),
)
app.add_tasks_from(finance_tasks.blueprint, namespace="finance")


@app.periodic(cron="30 3 * * *")
@app.task(name="remove_old_jobs", pass_context=True)
async def remove_old_jobs(context: JobContext, timestamp: int) -> None:
    """Finished jobs keep their arguments; don't keep them longer than a week."""
    await builtin_tasks.remove_old_jobs(
        context,
        max_hours=7 * 24,
        remove_failed=True,
        remove_cancelled=True,
        remove_aborted=True,
    )
