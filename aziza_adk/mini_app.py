"""The specialist's mini app: one shell, and the apps her own row lets her open.

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

from channel_telegram import media, settings
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response

from aziza_adk import (
    arrivals,
    config,
    init_data,
    join,
    mini_app_page,
    qr,
    queries,
    queue_http,
    session,
    supplies,
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
#: `blob:` is what a photograph fetched WITH the credential becomes — an `<img src>` carries no
#: header, so the bytes are read by `fetch` and handed to the document as an object URL (§16).
HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; "
        f"script-src 'self' {mini_app_page.SDK}; "
        "connect-src 'self'; img-src 'self' data: blob:; style-src 'unsafe-inline'; "
        f"base-uri 'none'; form-action 'none'; frame-ancestors {_FRAME_ANCESTORS}"
    ),
    "Cache-Control": "no-store, private",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Robots-Tag": "noindex, nofollow",
}

# Everything below reaches a specialist with NO model in the path, so the register is fixed at the
# literal — docs/BRAND_VOICE.md.
MINI_APP_HEADING_TEXT = "Código de la fila"
MINI_APP_NO_AUTH_TEXT = "Abre esto desde el chat del bot y te muestro el código."
MINI_APP_FAILED_TEXT = "No pude cargar el código. Ciérralo y ábrelo de nuevo."
MINI_APP_NOBODY_TEXT = "Nadie esperando."
LAUNCHER_HEADING_TEXT = "¿Qué vas a abrir?"
BACK_TEXT = "Volver"
SUPPLIES_HEADING_TEXT = "Lo que hace falta"
SUPPLIES_EMPTY_TEXT = "No hay nada pendiente por comprar."
SUPPLIES_BOUGHT_TEXT = "Comprado"
SUPPLIES_PHOTO_TEXT = "Ver foto"
SUPPLIES_UNLISTED_TEXT = "no está en la lista del salón"

#: What each app is called where she taps it. The keys are what `mini_app_page`'s script switches
#: on, so a key added here without a view there renders an empty screen.
QUEUE = "queue"
SUPPLIES = "supplies"


def apps_for(who: dict) -> tuple[dict, ...]:
    """Which apps this specialist may open, in the order the launcher lists them.

    Off the row the edge resolved rather than anything the page said, exactly as
    `guards.before_tool_guard` reads a role (§3). Which app goes to whom is §14.
    """
    found = [{"key": QUEUE, "label": MINI_APP_HEADING_TEXT}]
    if session.OWNER in (who.get("roles") or ()):
        found.append({"key": SUPPLIES, "label": SUPPLIES_HEADING_TEXT})
    return tuple(found)


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


async def _owner(request: Request) -> tuple[dict | None, JSONResponse | None]:
    """As `_who`, and holding the role the list is an owner's by.

    The launcher decides what she is OFFERED and this decides what she may reach — §14.
    """
    who, refused = await _who(request)
    if refused is not None:
        return None, refused
    if session.OWNER not in (who or {}).get("roles", ()):
        log.info("mini_app.refused reason=not_an_owner")
        return None, JSONResponse({"error": "not_an_owner"}, 403, headers=HEADERS)
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


def _needed() -> dict:
    """The list to buy, and every label on it.

    The copy travels WITH the data so that every Spanish literal in this app is a module constant
    the sweep can find — docs/BRAND_VOICE.md §6.
    """
    now = tools.now()
    with queries.connect() as conn:
        found = supplies.needed(queries.pending_supplies(conn))
    return {
        "empty_label": SUPPLIES_EMPTY_TEXT,
        "bought_label": SUPPLIES_BOUGHT_TEXT,
        "photo_label": SUPPLIES_PHOTO_TEXT,
        "unlisted_label": SUPPLIES_UNLISTED_TEXT,
        "items": [
            {
                "label": one.label,
                "listed": one.listed,
                "waited": supplies.waited(one.since, now),
                "ids": list(one.request_ids),
                "reports": [
                    {
                        "who": supplies.first_name(report.reported_by),
                        "waited": supplies.waited(report.reported_at, now),
                        "note": report.note,
                        # 0 rather than absent: the script asks for a number, and a photo route
                        # that answered on a falsy id would serve whatever row 0 resolved to.
                        "photo_id": report.request_id if report.has_photo else 0,
                    }
                    for report in one.reports
                ],
            }
            for one in found
        ],
    }


def _tick(request_ids: list[int], specialist_id: int) -> dict:
    with queries.connect() as conn:
        queries.mark_bought(conn, request_ids, specialist_id)
    return _needed()


def _photo_handle(request_id: int) -> dict | None:
    with queries.connect() as conn:
        return queries.supply_photo(conn, request_id)


def _wanted_ids(body: object) -> list[int]:
    """The rows a tick names, or nothing. A body that is not a list of whole numbers marks none.

    Read defensively because it is the one thing on these routes the PAGE supplies: everything
    else comes off the signed launch or out of the database.
    """
    if not isinstance(body, dict) or not isinstance(body.get("ids"), list):
        return []
    return [one for one in body["ids"] if isinstance(one, int) and not isinstance(one, bool)]


def create_router() -> APIRouter:
    """Mount the mini app: a public shell, a public script, and gated reads behind it.

    The shell CANNOT be gated and that is not a gap: `initData` reaches the page through
    `window.Telegram.WebApp`, so it is absent from the request that fetches it. The shell carries
    no name and no figure — WHICH apps exist for her is itself a gated read, because the answer
    names her role.
    """
    router = APIRouter()

    @router.get("/mini-app", response_class=HTMLResponse)
    async def shell() -> HTMLResponse:
        return HTMLResponse(
            mini_app_page.shell(
                # The salon's name rather than a view's heading: the shell is one document and
                # the heading is whichever app she is in.
                title=config.SALON_NAME,
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

    @router.post("/mini-app/apps")
    async def apps(request: Request) -> JSONResponse:
        who, refused = await _who(request)
        if refused is not None:
            return refused
        return JSONResponse(
            {
                "apps": list(apps_for(who or {})),
                "choose_label": LAUNCHER_HEADING_TEXT,
                "back_label": BACK_TEXT,
            },
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

    @router.post("/mini-app/supplies")
    async def needed(request: Request) -> JSONResponse:
        who, refused = await _owner(request)
        if refused is not None:
            return refused
        return JSONResponse(await asyncio.to_thread(_needed), headers=HEADERS)

    @router.post("/mini-app/supplies/bought")
    async def bought(request: Request) -> JSONResponse:
        who, refused = await _owner(request)
        if refused is not None:
            return refused
        wanted = _wanted_ids(await request.json())
        if not wanted:
            return JSONResponse(await asyncio.to_thread(_needed), headers=HEADERS)
        return JSONResponse(await asyncio.to_thread(_tick, wanted, who["id"]), headers=HEADERS)

    @router.post("/mini-app/supplies/photo")
    async def photo(request: Request) -> Response:
        """One report's picture, fetched from the transport with the salon's own credential.

        By row and never by handle, for the reason §16 gives.
        """
        who, refused = await _owner(request)
        if refused is not None:
            return refused
        wanted = _wanted_ids(await request.json())
        found = await asyncio.to_thread(_photo_handle, wanted[0]) if wanted else None
        if found is None:
            return JSONResponse({"error": "no_photo"}, 404, headers=HEADERS)
        fetched = await media.download(found["photo_file_id"], found["photo_mime"])
        if fetched is None:
            return JSONResponse({"error": "photo_unavailable"}, 502, headers=HEADERS)
        data, mime = fetched
        return Response(data, media_type=mime, headers=HEADERS)

    return router
