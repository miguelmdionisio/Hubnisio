"""Background worker entrypoint: `procrastinate --app=hubnisio.worker.app worker`.

Modules define their tasks on a `procrastinate.Blueprint` in their `jobs.py`; register each
one here with `app.add_tasks_from(blueprint, namespace="<module>")`.
"""

import procrastinate

from hubnisio.core.settings import get_settings

# The queue's tables live in their own "procrastinate" schema (see migration 0002).
app = procrastinate.App(
    connector=procrastinate.PsycopgConnector(
        conninfo=get_settings().database_url,
        kwargs={"options": "-c search_path=procrastinate"},
    ),
)
