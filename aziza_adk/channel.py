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
import logging

import agent_telemetry as telemetry
import agent_transcription as transcription
from channel_telegram.handler import TurnHandler
from channel_telegram.webhook import create_app
from google.adk.events import Event, EventActions
from google.genai import types

from aziza_adk import config, queries, runtime, session, tools

logger = logging.getLogger("aziza_adk.telegram")

# These four reach a specialist with NO model in the path, so the register is fixed at the
# literal. `tests/test_voice.py` gates them by their names — docs/BRAND_VOICE.md.
FALLBACK_TEXT = "Se me complicó procesar eso. Inténtalo de nuevo en un momento."
NOT_REGISTERED_TEXT = tools.NOT_REGISTERED_MSG
MEDIA_REFUSED_TEXT = (
    "No puedo leer fotos. Escríbeme o mándame una nota de voz con lo que le hiciste a la clienta."
)
UNSUPPORTED_TEXT = "Solo puedo leer mensajes de texto y notas de voz. ¿Me lo escribes?"
# A voice note that arrived but yielded no words. Separate from UNSUPPORTED_TEXT because telling
# someone who just spoke that speech is unread is false, and invites the same failed retry.
VOICE_UNCLEAR_TEXT = (
    "Recibí tu nota de voz pero no entendí lo que dijiste. ¿Me la repites o me lo escribes?"
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
        "is_admin": bool(who.get("is_admin")),
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


async def run_turn(user_id: str, who: dict, text: str) -> str:
    """Drive one specialist's turn through the production Runner."""
    runner = runtime.get_runner()
    await _session_for(runner, user_id, who)
    message = types.Content(role="user", parts=[types.Part(text=text)])
    chunks: list[str] = []
    async for event in runner.run_async(user_id=user_id, session_id=user_id, new_message=message):
        if event.is_final_response() and event.content and event.content.parts:
            if reply := event.content.parts[0].text:
                chunks.append(reply)
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
        return MEDIA_REFUSED_TEXT

    async def on_unsupported(self, msg) -> str | None:
        # The channel routes a voice note here only once transcription has produced nothing.
        if msg.msg_type == "audio":
            return VOICE_UNCLEAR_TEXT
        return UNSUPPORTED_TEXT


async def _transcribe(audio: bytes, mime: str) -> str | None:
    """The words in a voice note, for the channel to run as a typed turn.

    Spanish is a hint about what to expect, never an instruction to translate.
    """
    return await transcription.transcribe(
        audio, mime, model=config.TRANSCRIBE_MODEL, language="Spanish"
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
    # /simulate runs a turn and RETURNS the reply instead of sending it, so the assistant can be
    # exercised without Telegram. It authenticates nobody — `sender` is a field the caller types —
    # so it must never have a route in an Ingress.
    enable_simulate=True,
    transcriber=_transcribe,
    # The channel's only reporting seam, and it carries the delivery result: a failed send happens
    # after the dedupe claim is taken, so the retry is deduped away and the turn records as a
    # success while the specialist sits in silence.
    on_turn_end=telemetry.turn_observer,
)
telemetry.instrument_fastapi(app)
