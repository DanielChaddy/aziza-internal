"""The specialist's mini app: the code she shows a client, and the line as it stands.

**The credential is the one §3 already names.** Telegram signs `initData`, and the id inside it is
matched against a registered `specialists` row before anything is minted or read — so a valid
Telegram signature from somebody the salon never registered reaches nothing, exactly as a message
from that person does. docs/PROJECT_DEFINITION.md §14.

`initData` arrives in a HEADER and never in a query string: it carries its own signature, and a
query string lands in an access log and in a Referer. That is the same reasoning that already pins
httpx to WARNING in `channel.py`.
"""

from __future__ import annotations

import asyncio
import logging
import time

from channel_telegram import settings
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from aziza_adk import (
    arrivals,
    config,
    init_data,
    join,
    mini_app_page,
    qr,
    queries,
    queue_http,
    tools,
)

log = logging.getLogger("aziza_adk.mini_app")

#: The scheme Telegram's own documentation uses for this header.
_SCHEME = "tma "

#: A mini app IS framed by Telegram Web, so `'none'` would break it outright (§14). The list cannot
#: be checked from a checkout: if Telegram serves from a host that is not here, the page renders
#: blank with a console error and nothing server-side to see.
_FRAME_ANCESTORS = "https://web.telegram.org https://webk.telegram.org https://webz.telegram.org"

#: No `'unsafe-inline'` in `script-src`: the page's program is a served file, so an injected one
#: has nothing to inherit. `img-src data:` is safe because an `<img>` renders SVG with scripting
#: disabled, and `tests/test_qr.py` asserts what segno actually emits rather than trusting it.
HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; "
        f"script-src 'self' {mini_app_page.SDK}; "
        "connect-src 'self'; img-src 'self' data:; style-src 'unsafe-inline'; "
        f"base-uri 'none'; form-action 'none'; frame-ancestors {_FRAME_ANCESTORS}"
    ),
    "Cache-Control": "no-store, private",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Robots-Tag": "noindex, nofollow",
}

# These four reach a specialist with NO model in the path, so the register is fixed at the literal
# — docs/BRAND_VOICE.md.
MINI_APP_HEADING_TEXT = "Código de la fila"
MINI_APP_NO_AUTH_TEXT = "Abre esto desde el chat del bot y te muestro el código."
MINI_APP_FAILED_TEXT = "No pude cargar el código. Ciérralo y ábrelo de nuevo."
MINI_APP_NOBODY_TEXT = "Nadie esperando."


def _offered(request: Request) -> str:
    supplied = request.headers.get("authorization", "")
    return supplied[len(_SCHEME) :] if supplied.startswith(_SCHEME) else ""


def _specialist(telegram_user_id: str) -> dict | None:
    with queries.connect() as conn:
        return queries.specialist_by_telegram_id(conn, telegram_user_id)


async def _who(request: Request) -> tuple[dict | None, JSONResponse | None]:
    """The specialist behind this request, or the refusal to return.

    Two gates, and they answer different questions: Telegram's signature says the launch is real,
    and the `specialists` row says the salon knows her. A launch that passes the first and fails
    the second is somebody with a Telegram account and no place here (§3).
    """
    checked = init_data.verify(
        _offered(request),
        bot_token=settings.bot_token(),
        now=time.time(),
        max_age_s=config.MINI_APP_INIT_DATA_MAX_AGE_SECONDS,
    )
    if isinstance(checked, init_data.Rejected):
        log.info("mini_app.refused reason=%s", checked.reason)
        return None, JSONResponse({"error": checked.reason}, 401, headers=HEADERS)
    who = await asyncio.to_thread(_specialist, checked.telegram_user_id)
    if who is None:
        log.info("mini_app.refused reason=not_registered")
        return None, JSONResponse({"error": "not_registered"}, 403, headers=HEADERS)
    return who, None


def _mint(specialist_id: int) -> dict:
    """A fresh code, and when it dies. "" when nothing is configured to open it."""
    url = join.link_for(specialist_id, now=time.time(), nonce=join.new_nonce())
    if not url:
        return {"svg": "", "expires_at": 0, "rotate_seconds": config.JOIN_QR_ROTATE_SECONDS}
    return {
        "svg": qr.data_url(url),
        "expires_at": int(time.time()) + config.JOIN_TOKEN_TTL_SECONDS,
        "rotate_seconds": config.JOIN_QR_ROTATE_SECONDS,
    }


def _line() -> dict:
    with queries.connect() as conn:
        roster = arrivals.line(queries.line_today(conn, tools.now().date()))
    return {
        # Names only. Her number tells two clients apart and is not a thing a specialist reads
        # (docs/BRAND_VOICE.md §7).
        "lines": [
            {
                "area": name,
                "waiting": [one.client_name for one in arrivals.waiting_in(roster, code)],
            }
            for code, name in queue_http.AREAS
        ],
        "being_attended": [one.client_name for one in roster if one.serving is not None],
        "empty_label": MINI_APP_NOBODY_TEXT,
    }


def create_router() -> APIRouter:
    """Mount the mini app: a public shell, a public script, and two gated reads.

    The shell CANNOT be gated and that is not a gap: `initData` reaches the page through
    `window.Telegram.WebApp`, so it is absent from the request that fetches it. The shell carries
    no name and no figure, and everything with the salon behind it is one of the two POSTs.
    """
    router = APIRouter()

    @router.get("/mini-app", response_class=HTMLResponse)
    async def shell() -> HTMLResponse:
        return HTMLResponse(
            mini_app_page.shell(
                heading=MINI_APP_HEADING_TEXT,
                no_auth=MINI_APP_NO_AUTH_TEXT,
                failed=MINI_APP_FAILED_TEXT,
            ),
            headers=HEADERS,
        )

    @router.get("/mini-app/app.js")
    async def program() -> PlainTextResponse:
        # The type matters: with `nosniff` set, a wrong one means the browser refuses to execute
        # it and the page silently does nothing at all.
        return PlainTextResponse(
            mini_app_page.script(),
            media_type="text/javascript; charset=utf-8",
            headers=HEADERS,
        )

    @router.post("/mini-app/qr")
    async def code(request: Request) -> JSONResponse:
        who, refused = await _who(request)
        if refused is not None:
            return refused
        return JSONResponse(_mint(who["id"]), headers=HEADERS)

    @router.post("/mini-app/queue")
    async def line(request: Request) -> JSONResponse:
        who, refused = await _who(request)
        if refused is not None:
            return refused
        return JSONResponse(await asyncio.to_thread(_line), headers=HEADERS)

    return router
