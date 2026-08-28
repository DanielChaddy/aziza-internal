"""The edge: who gets in, and what a voice note becomes.

The two properties here are the ones nothing else can hold. An unregistered sender must be
refused BEFORE the Runner — a guard further in would already have cost a model call and a
session. And the transcriber must be ATTACHED: one written but never passed leaves every other
test green while every real voice note reaches `on_unsupported`.
"""

import pytest
from channel_telegram import bot_client, dedupe, media, security
from channel_telegram.testing import FakeResponse, file_found, sent
from fastapi.testclient import TestClient

from aziza_adk import channel

SECRET = "shh"
SENDER = "700000001"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "12345:tok")
    monkeypatch.setenv("TELEGRAM_TYPING_INDICATOR_ENABLED", "false")
    monkeypatch.delenv("TELEGRAM_ALLOWED_USER_IDS", raising=False)
    monkeypatch.delenv("TELEGRAM_MAX_DELIVERY_AGE_S", raising=False)
    dedupe.reset()
    yield
    dedupe.reset()


@pytest.fixture
def client():
    return TestClient(channel.app)


@pytest.fixture
def known(monkeypatch):
    """A registered specialist, without a database behind the lookup."""
    who = {
        "id": 1,
        "specialist_ref": "esp-001",
        "full_name": "Yamilé Reyes",
        "disciplines": ["nails"],
    }

    async def lookup(user_id):
        return who if user_id == SENDER else None

    monkeypatch.setattr(channel, "specialist_for", lookup)
    return who


@pytest.fixture
def turn(monkeypatch):
    """Record what reached the graph, without building one."""
    seen: list[tuple[str, str]] = []

    async def run(user_id, who, text):
        seen.append((user_id, text))
        return "listo"

    monkeypatch.setattr(channel, "run_turn", run)
    return seen


def _update(update_id=1, **message):
    import time

    return {
        "update_id": update_id,
        "message": {
            "message_id": 5,
            "from": {"id": int(SENDER)},
            "chat": {"id": int(SENDER)},
            "date": int(time.time()),
            **message,
        },
    }


def _post(client, body, secret=SECRET):
    return client.post("/webhook", json=body, headers={security.SECRET_HEADER: secret})


# --- [1] Identity is resolved at the edge -------------------------------------------------


def test_a_registered_specialist_reaches_the_graph(client, known, turn, fake_http):
    fake_http(bot_client, sent())
    _post(client, _update(text="le hice manicure a Laura"))
    assert turn == [(SENDER, "le hice manicure a Laura")]


def test_an_unregistered_sender_never_reaches_the_graph(client, known, turn, fake_http):
    """THE property. No model call, no session created, nothing to talk past — a commission
    booked under the wrong name is money."""
    http = fake_http(bot_client, sent())
    body = _update(text="le hice manicure a Laura")
    body["message"]["from"]["id"] = 999999
    body["message"]["chat"]["id"] = 999999
    _post(client, body)
    assert turn == [], "the turn ran for someone the salon does not know"
    assert http.requests[0]["json"]["text"] == channel.NOT_REGISTERED_TEXT


def test_an_unregistered_sender_is_told_why_rather_than_ignored(client, known, turn, fake_http):
    """Silence would read as a broken bot to someone who is about to ask the administration."""
    fake_http(bot_client, sent())
    body = _update(text="hola")
    body["message"]["from"]["id"] = 999999
    body["message"]["chat"]["id"] = 999999
    reply = client.post("/simulate", json={"sender": "999999", "text": "hola"}).json()
    assert reply["reply"] == channel.NOT_REGISTERED_TEXT


# --- [2] The transcriber is attached ------------------------------------------------------


def test_a_voice_note_is_transcribed_and_run_as_a_typed_turn(
    client, known, turn, fake_http, monkeypatch
):
    """It then takes the same path a typed message does, so it is screened by whatever screens
    text rather than arriving as a shape no guard reads."""
    heard = {}

    async def transcribe(audio, mime, *, model, language):
        heard.update(mime=mime, bytes=audio, language=language)
        return "  le hice manicure a Laura  "

    monkeypatch.setattr(channel.transcription, "transcribe", transcribe)
    # ONE script for the whole turn: both channel modules hold the same `httpx`, so patching it
    # twice replaces the first patch rather than adding to it. In call order — the file lookup,
    # the bytes, then the reply.
    fake_http(media, file_found(), FakeResponse(200, content=b"opus-bytes"), sent())

    _post(client, _update(voice={"file_id": "AwAC", "mime_type": "audio/ogg", "duration": 3}))
    assert turn == [(SENDER, "le hice manicure a Laura")]
    assert heard["mime"] == "audio/ogg" and heard["bytes"] == b"opus-bytes"
    assert heard["language"] == "Spanish", "a hint about what to expect, never a translation"


def test_the_audio_is_fetched_with_an_audio_cap_not_an_image_one(
    client, known, turn, fake_http, monkeypatch
):
    """An image cap on an audio fetch refuses every note, and the refusal is a log line nobody
    reads rather than a failure."""

    async def transcribe(audio, mime, *, model, language):
        return "hola"

    monkeypatch.setattr(channel.transcription, "transcribe", transcribe)
    fake_http(media, file_found(), FakeResponse(200, content=b"opus"), sent())
    _post(client, _update(voice={"file_id": "A", "mime_type": "audio/ogg"}))
    assert turn, "the voice note was refused before it reached the transcriber"


def test_a_voice_note_that_yields_no_words_says_so_rather_than_claiming_speech_is_unread(
    client, known, fake_http, monkeypatch
):
    async def transcribe(audio, mime, *, model, language):
        return None

    monkeypatch.setattr(channel.transcription, "transcribe", transcribe)
    http = fake_http(media, file_found(), FakeResponse(200, content=b"opus"), sent())
    _post(client, _update(voice={"file_id": "A", "mime_type": "audio/ogg"}))
    assert http.requests[-1]["json"]["text"] == channel.VOICE_UNCLEAR_TEXT


# --- [3] Everything else the transport can hand over --------------------------------------


def test_a_photo_is_refused(client, known, turn, fake_http):
    """There is no flow here a photo belongs to."""
    http = fake_http(bot_client, sent())
    _post(client, _update(photo=[{"file_id": "b"}]))
    assert turn == []
    assert http.requests[0]["json"]["text"] == channel.MEDIA_REFUSED_TEXT


def test_a_sticker_gets_the_general_refusal(client, known, fake_http):
    http = fake_http(bot_client, sent())
    _post(client, _update(sticker={"file_id": "s"}))
    assert http.requests[0]["json"]["text"] == channel.UNSUPPORTED_TEXT


# --- [4] The wiring, asserted rather than assumed -----------------------------------------


def test_a_delivery_without_the_secret_is_refused(client, turn):
    assert client.post("/webhook", json=_update(text="hola")).status_code == 403
    assert turn == []


def test_the_health_check_reaches_the_database_rather_than_a_constant(client, monkeypatch):
    def broken():
        raise RuntimeError("database is gone")

    monkeypatch.setattr(channel, "_read_the_catalog", broken)
    assert client.get("/healthz").status_code == 503


def test_a_failed_turn_still_tells_the_specialist_something(client, known, fake_http, monkeypatch):
    """After the ACK, silence is not a log line they can see — it is the bot never answering."""

    async def explode(user_id, who, text):
        raise RuntimeError("boom")

    monkeypatch.setattr(channel, "run_turn", explode)
    http = fake_http(bot_client, sent())
    _post(client, _update(text="hola"))
    assert http.requests[0]["json"]["text"] == channel.FALLBACK_TEXT


def test_the_bot_token_cannot_reach_the_log():
    """Telegram puts the token in the URL path and httpx logs request lines at INFO, so an
    unconfigured logger writes a live credential on every turn. Asserted on the level rather than
    on a captured line: what matters is that INFO from that logger never gets emitted at all."""
    import logging

    assert logging.getLogger("httpx").level >= logging.WARNING
