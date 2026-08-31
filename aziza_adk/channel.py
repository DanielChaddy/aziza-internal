"""The Telegram channel, over `channel_telegram`.

The transport — the secret check, payload parsing, allowlist, inbound dedupe, per-sender turn
lock, staleness, splitting, sending — is the shared package's. What lives here is what only this
salon can answer: who a sender is, how a turn runs against the graph, and the four Spanish
strings a specialist reads when it cannot.

**Identity is resolved HERE, before the Runner.** A sender who is not a registered specialist is
answered with one fixed line and no session is created — no model call, nothing to talk past.
That is the opposite of what a customer-facing assistant does, and the reason is the opposite
too: a sale carries a commission, so the Telegram id matched against a pre-registered row IS the
credential (docs/PROJECT_DEFINITION.md §3).

Run:  uvicorn aziza_adk.channel:app --port 8080
"""

from __future__ import annotations

import asyncio
import contextvars
import logging

import agent_telemetry as telemetry
import agent_transcription as transcription
from agent_adk import user_turn
from channel_telegram import media
from channel_telegram.handler import TurnHandler
from channel_telegram.webhook import create_app
from google.adk.events import Event, EventActions

from aziza_adk import (
    config,
    mini_app,
    queries,
    queue_http,
    report_http,
    runtime,
    session,
    tools,
)

logger = logging.getLogger("aziza_adk.telegram")

# Telegram carries the bot token in the URL PATH, and httpx logs every request line at INFO — so
# left alone this writes a live credential into the logs on every single turn. Silenced rather
# than redacted: there is nothing in an httpx request line worth the risk of getting a filter
# slightly wrong. WARNING and above still reach the log.
# TODO: AB#5351 — belongs in channel-telegram, which owns the client that builds the URL.
logging.getLogger("httpx").setLevel(logging.WARNING)

# These four reach a specialist with NO model in the path, so the register is fixed at the
# literal. `tests/test_voice.py` gates them by their names — docs/BRAND_VOICE.md.
FALLBACK_TEXT = "Se me complicó procesar eso. Inténtalo de nuevo en un momento."
QUOTA_EXHAUSTED_TEXT = (
    "Llegué al límite de uso por hoy y no puedo registrar nada más. Avísale a la administración."
)
NOT_REGISTERED_TEXT = tools.NOT_REGISTERED_MSG
# Photos are the administration's path, so a specialist who is not an owner is told what the
# channel is for rather than that photos cannot be read — which stopped being true.
MEDIA_REFUSED_TEXT = (
    "Las fotos de facturas las registra la administración. Escríbeme o mándame una nota de voz "
    "con lo que le hiciste a la clienta."
)
# The photo arrived and its bytes did not. Separate from the line above for the reason a voice
# note that yielded no words is separate: telling her photos are somebody else's invites the
# wrong retry when the fetch is what failed.
IMAGE_FAILED_TEXT = "Recibí la foto pero no pude abrirla. ¿Me la mandas otra vez?"
UNSUPPORTED_TEXT = "Solo puedo leer mensajes de texto y notas de voz. ¿Me lo escribes?"
# A voice note that arrived but yielded no words. Separate from UNSUPPORTED_TEXT because telling
# someone who just spoke that speech is unread is false, and invites the same failed retry.
VOICE_UNCLEAR_TEXT = (
    "Recibí tu nota de voz pero no entendí lo que dijiste. ¿Me la repites o me lo escribes?"
)
VOICE_FAILED_TEXT = (
    "No pude procesar tu nota de voz ahora mismo. Inténtalo de nuevo o escríbeme lo que hiciste."
)


def _lookup(telegram_user_id: str) -> dict | None:
    with queries.connect() as conn:
        return queries.specialist_by_telegram_id(conn, telegram_user_id)


async def specialist_for(telegram_user_id: str) -> dict | None:
    """The specialist behind this sender, or None. Sync driver, so it runs off the event loop."""
    return await asyncio.to_thread(_lookup, telegram_user_id)


def _state_for(who: dict) -> dict:
    return {
        "id": who["id"],
        "specialist_ref": who["specialist_ref"],
        "full_name": who["full_name"],
        "disciplines": list(who["disciplines"]),
        "roles": list(who.get("roles") or ()),
    }


async def _session_for(runner, user_id: str, who: dict):
    """This specialist's session, seeded with who they are and kept current.

    Re-anchored rather than seeded once: what a specialist is allowed to record is read off this
    state by the guard, so a discipline added or removed in the salon's records has to reach an
    existing conversation. `EventActions(state_delta=...)` is the only way state persists —
    assigning to `session.state` mutates a copy the store then drops.

    Safe to append here: the channel holds this sender's turn lock around the whole dispatch.
    """
    service = runner.session_service
    wanted = _state_for(who)
    found = await service.get_session(app_name=config.APP_NAME, user_id=user_id, session_id=user_id)
    if found is None:
        return await service.create_session(
            app_name=config.APP_NAME,
            user_id=user_id,
            session_id=user_id,
            state={session.SPECIALIST_KEY: wanted},
        )
    if found.state.get(session.SPECIALIST_KEY) != wanted:
        await service.append_event(
            found,
            Event(
                author="system",
                invocation_id="specialist-refresh",
                actions=EventActions(state_delta={session.SPECIALIST_KEY: wanted}),
            ),
        )
    return found


#: HTTP status the model API answers a spent quota with.
_QUOTA_STATUS = 429


def _is_quota_exhausted(exc: BaseException) -> bool:
    """Whether this turn failed because the day's model quota is spent.

    Read off `code` rather than the message, which is the provider's prose and not ours. The chain
    is walked because ADK re-raises the SDK's error wrapped in its own, and both carry the status.
    """
    seen: BaseException | None = exc
    while seen is not None:
        if getattr(seen, "code", None) == _QUOTA_STATUS:
            return True
        seen = seen.__cause__
    return False


async def run_turn(
    user_id: str,
    who: dict,
    text: str,
    *,
    image: bytes | None = None,
    mime: str = "",
    photo_file_id: str = "",
) -> str:
    """Drive one specialist's turn through the production Runner.

    `photo_file_id` is written to session state BEFORE the Runner is invoked, which is the whole
    of why a tool can be sure it is real: there is no argument carrying a handle, so a model
    cannot invent one and no tool can be called on a description of an invoice (§15).
    """
    runner = runtime.get_runner()
    found = await _session_for(runner, user_id, who)
    if photo_file_id:
        await runner.session_service.append_event(
            found,
            Event(
                author="system",
                invocation_id="photo",
                actions=EventActions(state_delta={session.PHOTO_KEY: {"file_id": photo_file_id}}),
            ),
        )
    message = user_turn(text, image=image, mime=mime)
    chunks: list[str] = []
    try:
        async for event in runner.run_async(
            user_id=user_id, session_id=user_id, new_message=message
        ):
            if event.is_final_response() and event.content and event.content.parts:
                if reply := event.content.parts[0].text:
                    chunks.append(reply)
    except Exception as exc:
        # A spent quota does not recover in a moment, so FALLBACK_TEXT's "inténtalo de nuevo"
        # would send her round the same wall until the day rolls over.
        if not _is_quota_exhausted(exc):
            raise
        logger.warning("turn refused: model quota exhausted")
        return QUOTA_EXHAUSTED_TEXT
    return " ".join(chunks).strip()


class SalonHandler(TurnHandler):
    """One turn, by shape. The channel owns everything before and after these methods."""

    async def on_text(self, msg) -> str | None:
        who = await specialist_for(msg.sender)
        if who is None:
            logger.info("turn refused: sender %s is not a registered specialist", msg.sender)
            return NOT_REGISTERED_TEXT
        return await run_turn(msg.sender, who, msg.text or "")

    async def on_media(self, msg) -> str | None:
        """A photographed supplier invoice, which is an owner's path and nobody else's.

        Refused HERE rather than by the guard, and before any fetch or model call: the input
        screen reads text parts only, so what is written inside a picture is unscreened by code.
        Admitting only owners is what keeps that surface two people wide (§15).
        """
        # TODO: `agent_adk.latest_user_text` reads text parts, so text inside an image reaches the
        # model unscreened. Contained structurally rather than by a guard — see §15.
        who = await specialist_for(msg.sender)
        if who is None:
            logger.info("turn refused: sender %s is not a registered specialist", msg.sender)
            return NOT_REGISTERED_TEXT
        if session.OWNER not in (who.get("roles") or ()):
            logger.info("photo refused: sender %s is not an owner", msg.sender)
            return MEDIA_REFUSED_TEXT

        fetched = await media.image_bytes(msg)
        if fetched is None:
            return IMAGE_FAILED_TEXT
        data, mime = fetched
        try:
            return await run_turn(
                msg.sender,
                who,
                msg.caption or "",
                image=data,
                mime=mime,
                photo_file_id=msg.media_id or "",
            )
        except Exception as exc:  # noqa: BLE001 - the type only, never the exception
            # A transport or model error can quote the request it choked on, and that request
            # carries the picture.
            logger.error("image turn failed: %s", type(exc).__name__)
            return IMAGE_FAILED_TEXT

    async def on_unsupported(self, msg) -> str | None:
        # The channel routes a voice note here only once transcription has produced nothing, and
        # the three kinds of nothing need three different things said about them.
        if msg.msg_type == "audio":
            because = _NO_WORDS_BECAUSE.get()
            if because == transcription.QUOTA:
                return QUOTA_EXHAUSTED_TEXT
            return VOICE_UNCLEAR_TEXT if because is None else VOICE_FAILED_TEXT
        return UNSUPPORTED_TEXT


#: Why the last voice note on THIS turn produced no words, or None when nothing was said. A
#: context variable rather than a module one: two turns interleave on one event loop, and a
#: shared slot would answer one specialist with the other's reason.
_NO_WORDS_BECAUSE: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "no_words_because", default=None
)


async def _transcribe(audio: bytes, mime: str) -> str | None:
    """The words in a voice note, for the channel to run as a typed turn.

    Spanish is a hint about what to expect, never an instruction to translate. The reason for
    silence is kept for `on_unsupported`, which is where the channel lands when there are no
    words and is the only place that can say which kind of silence it was.
    """
    _NO_WORDS_BECAUSE.set(None)
    return await transcription.transcribe(
        audio,
        mime,
        model=config.TRANSCRIBE_MODEL,
        language="Spanish",
        on_failure=_NO_WORDS_BECAUSE.set,
    )


def _read_the_catalog() -> None:
    """A liveness check that exercises the database rather than a constant.

    Reading the catalog is the cheapest call that reaches what the tools reach, so a health
    endpoint cannot report 200 with nothing behind it.
    """
    with queries.connect() as conn:
        queries.service_catalog(conn)


async def _health() -> None:
    # Sync driver, so it runs off the event loop.
    await asyncio.to_thread(_read_the_catalog)


# Installed before the app exists so nothing this process builds is missed. ADK emits a span per
# turn, per model call and per tool call and discards every one unless a provider is registered;
# with OTEL_EXPORTER_OTLP_ENDPOINT unset this installs nothing and returns False.
telemetry.install("web", namespace="aziza")

app = create_app(
    SalonHandler(),
    health_check=_health,
    turn_timeout_s=config.MODEL_TURN_TIMEOUT_SECONDS,
    fallback_reply=FALLBACK_TEXT,
    title="Salón Aziza — Telegram webhook",
    # Off unless ENABLE_SIMULATE says otherwise, because it authenticates nobody — config.py.
    enable_simulate=config.ENABLE_SIMULATE,
    transcriber=_transcribe,
    # The channel's only reporting seam, and it carries the delivery result: a failed send happens
    # after the dedupe claim is taken, so the retry is deduped away and the turn records as a
    # success while the specialist sits in silence.
    on_turn_end=telemetry.turn_observer,
)
# The client's join page rides on THIS app rather than a second workload. A separate one would
# need the bot token too (the mini app verifies Telegram's initData with a key derived from it), so
# splitting would put the credential in two pods instead of one — the opposite of what the split is
# for. It also inherits the httpx silencing above, which a second process would need a copy of.
app.include_router(queue_http.create_router())
app.include_router(mini_app.create_router())
# The owner's report rides on the same app for the same reason the join page does.
app.include_router(report_http.create_router())

telemetry.instrument_fastapi(app)
