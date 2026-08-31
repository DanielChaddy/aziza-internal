"""The edge: who gets in, and what a voice note becomes.

The two properties here are the ones nothing else can hold. An unregistered sender must be
refused BEFORE the Runner — a guard further in would already have cost a model call and a
session. And the transcriber must be ATTACHED: one written but never passed leaves every other
test green while every real voice note reaches `on_unsupported`.
"""

from types import SimpleNamespace

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
def owner(monkeypatch):
    """A registered OWNER, which is the only sender a photo reaches anything from (§15)."""
    who = {
        "id": 2,
        "specialist_ref": "esp-002",
        "full_name": "Zoila Dueña",
        "disciplines": [],
        "roles": ["owner"],
    }

    async def lookup(user_id):
        return who if user_id == SENDER else None

    monkeypatch.setattr(channel, "specialist_for", lookup)
    return who


@pytest.fixture
def turn(monkeypatch):
    """Record what reached the graph, without building one."""
    seen: list[tuple[str, str]] = []

    async def run(user_id, who, text, **carried):
        seen.append((user_id, text, carried))
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
    assert turn == [(SENDER, "le hice manicure a Laura", {})]


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
    """Silence would read as a broken bot to someone who is about to ask the administration. What
    she is TOLD is the assertion here; that no turn ran for her is the case above."""
    http = fake_http(bot_client, sent())
    body = _update(text="hola")
    body["message"]["from"]["id"] = 999999
    body["message"]["chat"]["id"] = 999999
    _post(client, body)
    assert http.requests[0]["json"]["text"] == channel.NOT_REGISTERED_TEXT


def test_the_app_as_it_ships_exposes_no_simulate_route(client):
    """`/simulate` authenticates nobody — `sender` is a field the caller types — so anybody who
    reaches it is any specialist whose Telegram id they know, and this repository is public.

    The Ingress not routing it is one layer (tests/test_chart.py); this is the other, because a
    port-forward and a second Ingress path both go straight past the first.
    """
    assert "/simulate" not in {getattr(route, "path", "") for route in channel.app.routes}
    assert client.post("/simulate", json={"sender": "999999", "text": "hola"}).status_code == 404


# --- [2] The transcriber is attached ------------------------------------------------------


def test_a_voice_note_is_transcribed_and_run_as_a_typed_turn(
    client, known, turn, fake_http, monkeypatch
):
    """It then takes the same path a typed message does, so it is screened by whatever screens
    text rather than arriving as a shape no guard reads."""
    heard = {}

    async def transcribe(audio, mime, *, model, language, on_failure=None):
        heard.update(mime=mime, bytes=audio, language=language)
        return "  le hice manicure a Laura  "

    monkeypatch.setattr(channel.transcription, "transcribe", transcribe)
    # ONE script for the whole turn: both channel modules hold the same `httpx`, so patching it
    # twice replaces the first patch rather than adding to it. In call order — the file lookup,
    # the bytes, then the reply.
    fake_http(media, file_found(), FakeResponse(200, content=b"opus-bytes"), sent())

    _post(client, _update(voice={"file_id": "AwAC", "mime_type": "audio/ogg", "duration": 3}))
    assert turn == [(SENDER, "le hice manicure a Laura", {})]
    assert heard["mime"] == "audio/ogg" and heard["bytes"] == b"opus-bytes"
    assert heard["language"] == "Spanish", "a hint about what to expect, never a translation"


def test_the_audio_is_fetched_with_an_audio_cap_not_an_image_one(
    client, known, turn, fake_http, monkeypatch
):
    """An image cap on an audio fetch refuses every note, and the refusal is a log line nobody
    reads rather than a failure."""

    async def transcribe(audio, mime, *, model, language, on_failure=None):
        return "hola"

    monkeypatch.setattr(channel.transcription, "transcribe", transcribe)
    fake_http(media, file_found(), FakeResponse(200, content=b"opus"), sent())
    _post(client, _update(voice={"file_id": "A", "mime_type": "audio/ogg"}))
    assert turn, "the voice note was refused before it reached the transcriber"


def test_a_voice_note_that_yields_no_words_says_so_rather_than_claiming_speech_is_unread(
    client, known, fake_http, monkeypatch
):
    async def transcribe(audio, mime, *, model, language, on_failure=None):
        return None

    monkeypatch.setattr(channel.transcription, "transcribe", transcribe)
    http = fake_http(media, file_found(), FakeResponse(200, content=b"opus"), sent())
    _post(client, _update(voice={"file_id": "A", "mime_type": "audio/ogg"}))
    assert http.requests[-1]["json"]["text"] == channel.VOICE_UNCLEAR_TEXT


# --- [3] Everything else the transport can hand over --------------------------------------


def test_a_photo_from_someone_who_is_not_an_owner_is_refused_at_the_edge(
    client, known, turn, fake_http
):
    """Refused before any fetch and before any model call. The input screen reads text parts only,
    so admitting only owners is what keeps the unscreened surface two people wide (§15)."""
    http = fake_http(bot_client, sent())
    _post(client, _update(photo=[{"file_id": "b"}]))
    assert turn == []
    assert http.requests[0]["json"]["text"] == channel.MEDIA_REFUSED_TEXT


def test_a_photo_from_a_stranger_is_refused_before_the_owner_check(client, turn, fake_http):
    """Identity first, always: an unregistered sender's picture reaches nothing."""
    http = fake_http(bot_client, sent())
    _post(client, _update(photo=[{"file_id": "b"}]))
    assert turn == []
    assert http.requests[0]["json"]["text"] == channel.NOT_REGISTERED_TEXT


def test_an_owners_photo_reaches_the_graph_with_its_bytes_and_its_handle(
    client, owner, turn, monkeypatch, fake_http
):
    """The caption is the turn's words and the handle is written to state, never passed as an
    argument — which is what stops a tool being called on a description of an invoice (§15)."""

    async def _bytes(msg):
        return b"jpeg", "image/jpeg"

    monkeypatch.setattr(channel.media, "image_bytes", _bytes)
    fake_http(bot_client, sent())
    _post(client, _update(photo=[{"file_id": "B7"}], caption="factura de materiales"))
    assert turn == [
        (
            SENDER,
            "factura de materiales",
            {"image": b"jpeg", "mime": "image/jpeg", "photo_file_id": "B7"},
        )
    ]


def test_a_photo_whose_bytes_never_arrive_says_so_rather_than_blaming_the_shape(
    client, owner, turn, monkeypatch, fake_http
):
    """Telling her photos are somebody else's job invites the wrong retry when the fetch is what
    failed — the same split as a voice note that yielded no words."""

    async def _bytes(msg):
        return None

    monkeypatch.setattr(channel.media, "image_bytes", _bytes)
    http = fake_http(bot_client, sent())
    _post(client, _update(photo=[{"file_id": "b"}]))
    assert turn == []
    assert http.requests[0]["json"]["text"] == channel.IMAGE_FAILED_TEXT


def test_a_failed_image_turn_logs_the_type_and_never_the_bytes(
    client, owner, monkeypatch, fake_http, caplog
):
    """A transport or model error can quote the request it choked on, and that request carries the
    picture."""

    async def _bytes(msg):
        return b"SECRETJPEGBYTES", "image/jpeg"

    async def _boom(*a, **kw):
        raise RuntimeError("failed sending SECRETJPEGBYTES")

    monkeypatch.setattr(channel.media, "image_bytes", _bytes)
    monkeypatch.setattr(channel, "run_turn", _boom)
    http = fake_http(bot_client, sent())
    with caplog.at_level("ERROR"):
        _post(client, _update(photo=[{"file_id": "b"}]))
    assert http.requests[0]["json"]["text"] == channel.IMAGE_FAILED_TEXT
    assert "SECRETJPEGBYTES" not in caplog.text
    assert "RuntimeError" in caplog.text


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


# --- a spent quota says so, rather than asking her to try again ---------------------------------


class _Wrapped(Exception):
    """Shaped like the SDK's error: the status is an attribute, not the message."""

    def __init__(self, code: int) -> None:
        super().__init__("boom")
        self.code = code


def test_a_spent_quota_is_recognized_off_the_status():
    assert channel._is_quota_exhausted(_Wrapped(429))


def test_a_spent_quota_is_recognized_through_ADKs_wrapping():
    """ADK re-raises the SDK's error inside its own, so the status is on the cause."""
    inner = _Wrapped(429)
    outer = Exception("adk")
    outer.__cause__ = inner
    assert channel._is_quota_exhausted(outer)


def test_another_failure_is_not_mistaken_for_a_spent_quota():
    """A 500 recovers in a moment and FALLBACK_TEXT is the right answer to it; a 429 does not."""
    assert not channel._is_quota_exhausted(_Wrapped(500))
    assert not channel._is_quota_exhausted(ValueError("nothing to do with quota"))


class _Runner:
    """A Runner that fails the way the real one does, without building a graph."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc
        self.session_service = self

    async def get_session(self, **_):
        return None

    async def create_session(self, **_):
        return None

    def run_async(self, **_):
        async def agen():
            raise self._exc
            yield  # pragma: no cover - unreachable, makes this an async generator

        return agen()


@pytest.mark.anyio
async def test_a_spent_quota_tells_her_so_instead_of_the_fallback(monkeypatch):
    monkeypatch.setattr(channel.runtime, "get_runner", lambda: _Runner(_Wrapped(429)))
    reply = await channel.run_turn(
        SENDER,
        {
            "id": 1,
            "specialist_ref": "esp-001",
            "full_name": "Yamilé Reyes",
            "disciplines": ["nails"],
        },
        "hola",
    )
    assert reply == channel.QUOTA_EXHAUSTED_TEXT


@pytest.mark.anyio
async def test_any_other_failure_still_reaches_the_channels_fallback(monkeypatch):
    """It must RAISE: the fallback lives in the channel, and swallowing here would silence it."""
    monkeypatch.setattr(channel.runtime, "get_runner", lambda: _Runner(_Wrapped(500)))
    with pytest.raises(Exception, match="boom"):
        await channel.run_turn(
            SENDER,
            {
                "id": 1,
                "specialist_ref": "esp-001",
                "full_name": "Yamilé Reyes",
                "disciplines": ["nails"],
            },
            "hola",
        )


# --- a voice note that produced no words, and the three reasons it might not have --------------
# The package classifies; this asserts the wiring between it and what the specialist reads. The
# real `transcribe` runs, with only its client replaced — a stub of it here would assert nothing
# about the two halves agreeing.


class _Status(Exception):
    def __init__(self, code: int) -> None:
        super().__init__("upstream")
        self.code = code


@pytest.fixture
def transcription_answers(monkeypatch):
    """Script what the model client does, and run one voice note through the real path."""
    from agent_transcription import gemini

    async def go(answer) -> str | None:
        class Models:
            async def generate_content(self, **_):
                if isinstance(answer, Exception):
                    raise answer
                return SimpleNamespace(text=answer)

        monkeypatch.setattr(
            gemini, "_client", lambda: SimpleNamespace(aio=SimpleNamespace(models=Models()))
        )
        words = await channel._transcribe(b"opus", "audio/ogg")
        if words:
            return words
        return await channel.SalonHandler().on_unsupported(
            SimpleNamespace(msg_type="audio", sender=SENDER)
        )

    return go


@pytest.mark.anyio
async def test_a_spent_quota_says_so_instead_of_blaming_her_voice(transcription_answers):
    """THE case: she records it again, and again, and it is never her audio that is the problem."""
    assert await transcription_answers(_Status(429)) == channel.QUOTA_EXHAUSTED_TEXT


@pytest.mark.anyio
async def test_another_failure_says_it_could_not_be_processed(transcription_answers):
    """Not her fault either, but it may work in a moment — which a quota will not."""
    assert await transcription_answers(_Status(503)) == channel.VOICE_FAILED_TEXT


@pytest.mark.anyio
async def test_silence_is_still_her_audio(transcription_answers):
    """No words is the one case where "I did not understand you" is the true thing to say."""
    assert await transcription_answers("   ") == channel.VOICE_UNCLEAR_TEXT


@pytest.mark.anyio
async def test_a_reason_does_not_survive_into_the_next_voice_note(transcription_answers):
    """The reason is cleared at the start of each transcription, so a quota this morning does not
    still be the answer to a genuinely unclear note this afternoon."""
    assert await transcription_answers(_Status(429)) == channel.QUOTA_EXHAUSTED_TEXT
    assert await transcription_answers("   ") == channel.VOICE_UNCLEAR_TEXT
