"""The two routes a client's browser reaches, and the only ones the internet reaches unauthorized.

A join token is a CAPABILITY, not a person: it proves somebody was standing where the code was
shown in the last few minutes, and the form asks who she is. Nothing here trusts it for identity —
it trusts it for presence, which is all it can carry. docs/PROJECT_DEFINITION.md §13.

The body is parsed with `urllib.parse.parse_qsl` rather than `Form(...)`, which would put a
transitive `python-multipart` on a public path this service declares no dependency on.
"""

from __future__ import annotations

import asyncio
import logging
import time

from agent_webview import tokens
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from aziza_adk import (
    arrivals,
    catalog_data,
    clients,
    config,
    hours,
    join,
    queries,
    queue_form,
    queue_pages,
    queue_text,
    tools,
)

log = logging.getLogger("aziza_adk.queue_http")

#: No `script-src` at all, which is what makes this absolute rather than aspirational: the pages
#: carry no script, so an injected one has nothing to inherit. `Referrer-Policy` earns its place
#: here more than anywhere else in the service — the token is in the PATH, so without it the
#: credential leaves in a Referer the moment the page links anywhere.
HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
        "base-uri 'none'; frame-ancestors 'none'"
    ),
    "Cache-Control": "no-store, private",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Robots-Tag": "noindex, nofollow",
}

#: (code, Spanish name) per area, from the dataset the seeder writes `disciplines` from — so the
#: boxes she ticks cannot drift from the rows the line is grouped by.
AREAS: tuple[tuple[str, str], ...] = tuple(
    (row["code"], row["name"]) for row in catalog_data.DISCIPLINES
)

#: How many people one code may put in the line before it stops working. NOT one: a code sits on a
#: screen and several clients legitimately scan the same one inside a rotation window, so
#: single-use would refuse the second real client of the afternoon. A ceiling on a script, not a
#: rate limit on a salon.
MAX_JOINS_PER_CODE = 25

#: code fingerprint -> (joins so far, when the token stops verifying). In-process, which is only
#: viable because the pod is replicas: 1 — deploy/helm/aziza/templates/statefulset.yaml.
# TODO: issue #31 — lost on restart, so a code minted before one gets its allowance again.
_SPENT: dict[str, tuple[int, int]] = {}


def _spend(fingerprint: str, expires_at: int, *, now: float) -> bool:
    """Count one join against a code. False once it has admitted its ceiling.

    Swept on write, and an entry cannot outlive its token because `tokens.verify` refuses an
    expired one first — so the bound is codes in flight rather than the day's traffic.
    """
    for seen, (_, expiry) in list(_SPENT.items()):
        if now > expiry + config.JOIN_TOKEN_LEEWAY_SECONDS:
            del _SPENT[seen]
    used, _ = _SPENT.get(fingerprint, (0, expires_at))
    if used >= MAX_JOINS_PER_CODE:
        return False
    _SPENT[fingerprint] = (used + 1, expires_at)
    return True


def _page(html: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(html, status_code=status, headers=HEADERS)


def _refused(result: tokens.Rejected, token: str) -> HTMLResponse:
    """A stale code says so; every other reason says nothing.

    The reasoning is `agent_webview.router`'s, reproduced rather than cited because this route does
    not use it: distinguishing the others answers questions about the secret for whoever is asking,
    while the one thing a real client needs to know is that the code went stale.
    """
    log.info("join.refused reason=%s code=%s", result.reason, tokens.fingerprint(token))
    if result.reason == tokens.REASON_EXPIRED:
        return _page(queue_pages.notice(queue_text.EXPIRED_CLIENT_COPY), 410)
    return _page(queue_pages.notice(queue_text.NOT_FOUND_CLIENT_COPY), 404)


def _turns(conn, arrival_id: int, chosen: tuple[str, ...]) -> tuple[tuple[str, int | None], ...]:
    """Where she stands in each line she just joined, read back rather than assumed."""
    roster = arrivals.line(queries.line_today(conn, tools.now().date()))
    names = dict(AREAS)
    return tuple(
        (names.get(code, code), arrivals.position(roster, code, arrival_id)) for code in chosen
    )


def _do_join(action: str, submitted: queue_form.Submitted) -> tuple[str, int]:
    """Resolve who she is and put her in the line. Returns the page and its status.

    Sync, one connection, and the order is the design: her number is keyed BEFORE anything is
    written, so a typo can never create a client (§3).
    """
    if submitted.phone is None:
        return queue_pages.join_form(
            action,
            AREAS,
            chosen=submitted.areas,
            name=submitted.name,
            problem=queue_text.BAD_PHONE_CLIENT_COPY,
            ask_name=bool(submitted.name),
        ), 400
    if not submitted.areas:
        return queue_pages.join_form(
            action,
            AREAS,
            phone=submitted.phone,
            name=submitted.name,
            problem=queue_text.NO_AREAS_CLIENT_COPY,
            ask_name=bool(submitted.name),
        ), 400

    with queries.connect() as conn:
        roster = clients.roster(queries.clients_on_phone(conn, submitted.phone))
        held = {one.client_id: one.name for one in roster}
        if submitted.client_id in held:
            # Only ever one of the candidates THIS number reaches. An id in the body is a value a
            # caller types, so it authorizes nothing on its own.
            client_id = submitted.client_id
        elif len(roster) > 1:
            return queue_pages.which_one(
                action,
                tuple((one.client_id, one.name) for one in roster),
                phone=submitted.phone,
                chosen=submitted.areas,
            ), 200
        elif len(roster) == 1:
            client_id = roster[0].client_id
        elif not submitted.name:
            return queue_pages.join_form(
                action,
                AREAS,
                phone=submitted.phone,
                chosen=submitted.areas,
                problem=queue_text.NO_NAME_CLIENT_COPY,
                ask_name=True,
            ), 400
        else:
            client_id = queries.create_client(conn, submitted.name, submitted.phone)["id"]

        arrival = queries.record_arrival(conn, client_id, tools.now().date(), submitted.areas)
        turns = _turns(conn, arrival["id"], submitted.areas)
    return (
        queue_pages.joined(
            held.get(client_id, submitted.name), turns, already=not arrival["created"]
        ),
        200,
    )


def create_router() -> APIRouter:
    """Mount `GET /j/{token}` and `POST /j/{token}`.

    The GET never writes, for the reason `agent_webview.router` gives: link scanners and in-app
    browsers fetch a URL before anybody taps it, so a side effect there runs with no reader.
    """
    router = APIRouter()

    def _shut() -> HTMLResponse | None:
        if hours.is_open(tools.now()):
            return None
        return _page(queue_pages.notice(queue_text.CLOSED_CLIENT_COPY))

    @router.get(f"/{join.JOIN}/{{token}}", response_class=HTMLResponse)
    async def show_form(token: str) -> HTMLResponse:
        result = join.opened(token, now=time.time())
        if isinstance(result, tokens.Rejected):
            return _refused(result, token)
        return _shut() or _page(queue_pages.join_form(f"/{join.JOIN}/{token}", AREAS))

    @router.post(f"/{join.JOIN}/{{token}}", response_class=HTMLResponse)
    async def submit(token: str, request: Request) -> HTMLResponse:
        now = time.time()
        result = join.opened(token, now=now)
        if isinstance(result, tokens.Rejected):
            return _refused(result, token)
        if (shut := _shut()) is not None:
            return shut
        if not _spend(tokens.fingerprint(token), result.expires_at, now=now):
            log.warning("join.code_spent code=%s", tokens.fingerprint(token))
            # Her code is used up rather than forged, and asking for a new one is the way out.
            return _page(queue_pages.notice(queue_text.EXPIRED_CLIENT_COPY), 429)

        submitted = queue_form.read(await request.body())
        html, status = await asyncio.to_thread(_do_join, f"/{join.JOIN}/{token}", submitted)
        return _page(html, status)

    return router
