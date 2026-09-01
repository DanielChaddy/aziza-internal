"""The one route an owner's browser reaches: a month's 606, as a file.

A token here is a CAPABILITY, as the join page's is — it proves somebody was sent this link, and
says nothing about who they are. docs/PROJECT_DEFINITION.md §15.

NO SPEND COUNTER, deliberately. `queue_http.py` already records that link scanners and in-app
browsers fetch a URL before anybody taps it, so a single-use link would be spent by the chat's own
preview. A download is a read; the TTL is what bounds it.
"""

from __future__ import annotations

import asyncio
import calendar
import datetime as dt
import logging
import time

from agent_webview import tokens
from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from fiscal_do import report_606

from aziza_adk import config, queries, reports

log = logging.getLogger("aziza_adk.report_http")

#: No script at all, and never cached: the body is the salon's whole month of purchases.
HEADERS = {
    "Content-Security-Policy": "default-src 'none'; base-uri 'none'; frame-ancestors 'none'",
    "Cache-Control": "no-store, private",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Robots-Tag": "noindex, nofollow",
}

#: What a refusal says. English, because nothing behind this route is a specialist reading Spanish
#: — it is a browser, and the assistant already said everything worth saying in the chat.
_STALE = "This link has expired. Ask the assistant for a new one."
_NOT_FOUND = "Not found."


def _body(month: dt.date) -> str:
    first = month.replace(day=1)
    last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
    with queries.connect() as conn:
        rows = queries.expenses_for_period(conn, first, last)
    return report_606.render(config.SALON_RNC, first, rows)


def _refused(result: tokens.Rejected, token: str) -> PlainTextResponse:
    """A stale link says it is stale; every other reason says nothing.

    The reasoning is `queue_http._refused`'s: distinguishing forged from wrong-secret answers
    questions about the secret for whoever is asking.
    """
    log.info("report.refused reason=%s link=%s", result.reason, tokens.fingerprint(token))
    if result.reason == tokens.REASON_EXPIRED:
        return PlainTextResponse(_STALE, status_code=410, headers=HEADERS)
    return PlainTextResponse(_NOT_FOUND, status_code=404, headers=HEADERS)


def create_router() -> APIRouter:
    """Mount `GET /r/{token}`."""
    router = APIRouter()

    @router.get(f"/{reports.REPORT}/{{token}}")
    async def download(token: str) -> PlainTextResponse:
        result = reports.opened(token, now=time.time())
        if isinstance(result, tokens.Rejected):
            return _refused(result, token)
        month = reports.month_of(result.claims)
        if month is None:
            return PlainTextResponse(_NOT_FOUND, status_code=404, headers=HEADERS)
        # Sync driver, so it runs off the event loop.
        body = await asyncio.to_thread(_body, month)
        return PlainTextResponse(
            body,
            media_type="text/plain; charset=utf-8",
            headers={
                **HEADERS,
                "Content-Disposition": f'attachment; filename="606-{month:%Y%m}.txt"',
            },
        )

    return router
