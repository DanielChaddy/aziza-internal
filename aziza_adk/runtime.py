"""The served runtime, with a session store that survives a restart.

`adk web` builds its own in-memory session service and needs nothing here. This is the path the
channel runs on: one Runner over a `DatabaseSessionService` backed by the ADK session database —
its OWN database, async URL. Constructing it opens no connection; ADK creates its tables on the
first session call.
"""

from __future__ import annotations

from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService

from aziza_adk import config
from aziza_adk.agent import root_agent

_runner: Runner | None = None


def get_runner() -> Runner:
    """The process-wide Runner, built once. `app_name` must equal the package directory name so
    `adk web` and the served Runner agree on session identity."""
    global _runner
    if _runner is None:
        _runner = Runner(
            app_name=config.APP_NAME,
            agent=root_agent,
            session_service=DatabaseSessionService(db_url=config.ADK_SESSION_DB_URL),
        )
    return _runner
