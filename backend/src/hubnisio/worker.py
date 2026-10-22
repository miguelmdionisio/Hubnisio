"""Background worker entrypoint: `procrastinate --app=hubnisio.worker.app worker`.

The app and its tasks are defined in hubnisio/jobs.py.
"""

from hubnisio.jobs import app

__all__ = ["app"]
