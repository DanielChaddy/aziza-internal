"""The specialist's mini app, driven through a real app with no model anywhere.

THE property is [2]: a valid Telegram signature is NOT a place in this salon. Telegram will sign
`initData` for anybody who opens the app, so the signature says the launch is real and the
`specialists` row says the salon knows her — and the second gate is the one §3 is about.

[3] is the attachment: every route with the salon behind it refuses without `initData`. Check by
hand that it goes red when the gate is removed from a route, because a gate test that cannot fail is
worse than none (aziza/CLAUDE.md).
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from fastapi.testclient import TestClient

from aziza_adk import config, mini_app, mini_app_page, tools
from tests.test_init_data import GOLDEN_AUTH_DATE, GOLDEN_TOKEN, _signed

_TZ = dt.timezone(dt.timedelta(hours=-4))
_OPEN = dt.datetime(2026, 9, 1, 14, 0, tzinfo=_TZ)

#: Every route with data behind it. The parametrize below is the attachment test.
GATED = [("POST", "/mini-app/qr"), ("POST", "/mini-app/queue")]


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", GOLDEN_TOKEN)
    monkeypatch.setattr(config, "JOIN_LINK_SECRET", "a-test-signing-secret-nobody-uses")
    monkeypatch.setattr(config, "JOIN_LINK_SECRET_PREVIOUS", "")
    monkeypatch.setattr(config, "JOIN_BASE_URL", "https://example.test")
    monkeypatch.setattr(config, "MINI_APP_INIT_DATA_MAX_AGE_SECONDS", 86400)
    monkeypatch.setattr(tools, "now", lambda: _OPEN)


@pytest.fixture
def client():
    from aziza_adk.channel import app

    return TestClient(app)


def _launch(telegram_user_id: str) -> dict:
    """The header a real open sends, for a specialist with that Telegram id."""
    init = _signed(user=json.dumps({"id": int(telegram_user_id)}, separators=(",", ":")))
    return {"Authorization": f"tma {init}"}


@pytest.fixture
def registered(make_specialist):
    """A specialist the salon knows, with a Telegram id the launch can carry."""
    return make_specialist("nails")


def _at_her_auth_date(monkeypatch):
    """The signed launch is stamped at the golden auth_date, so the clock has to sit near it."""
    monkeypatch.setattr(mini_app.time, "time", lambda: GOLDEN_AUTH_DATE + 5)


# --- [1] The shell is public, and carries nothing worth gating -------------------------------


def test_the_shell_opens_with_no_credential_at_all(configured, client):
    """It CANNOT be gated: `initData` reaches the page through `window.Telegram.WebApp`, so it is
    absent from the request that fetches it. That is only safe while the shell holds no data."""
    page = client.get("/mini-app")
    assert page.status_code == 200
    assert mini_app_page.SDK in page.text


def test_the_shell_carries_no_name_and_no_figure(configured, client, sentinel):
    """Everything about the salon arrives by a gated fetch. A name rendered into the shell would
    be salon data on a public route."""
    from tests.conftest import KNOWN_CLIENTS

    page = client.get("/mini-app").text
    for name in KNOWN_CLIENTS:
        assert name not in page
    for phone in KNOWN_CLIENTS.values():
        assert phone not in page


def test_the_script_is_served_with_a_type_nosniff_will_execute(configured, client):
    """With `nosniff` set, a wrong content type means the browser refuses to run it and the page
    silently does nothing — no error, no code, no line."""
    served = client.get("/mini-app/app.js")
    assert served.status_code == 200
    assert served.headers["content-type"].startswith("text/javascript")
    assert served.headers["x-content-type-options"] == "nosniff"


def test_the_page_and_its_script_are_two_files_so_no_inline_script_is_needed(configured, client):
    """`script-src` carries no `'unsafe-inline'`, which is only possible because the program is a
    served file rather than a block in the shell."""
    page = client.get("/mini-app").text
    assert "<script src=" in page
    assert (
        "unsafe-inline"
        not in client.get("/mini-app").headers["content-security-policy"].split("style-src")[0]
    )


# --- [2] A Telegram signature is not a place in this salon -----------------------------------


@pytest.mark.parametrize("method,path", GATED)
def test_every_route_with_the_salon_behind_it_refuses_without_init_data(
    configured, client, method, path
):
    assert client.request(method, path).status_code == 401


@pytest.mark.parametrize("method,path", GATED)
def test_a_forged_launch_is_refused(configured, client, method, path):
    forged = {"Authorization": "tma auth_date=1800000000&user=%7B%22id%22%3A1%7D&hash=" + "0" * 64}
    assert client.request(method, path, headers=forged).status_code == 401


def test_a_real_launch_from_somebody_the_salon_never_registered_reaches_nothing(
    configured, client, monkeypatch, sentinel
):
    """THE property. Telegram signs for anybody; the `specialists` row is the credential (§3)."""
    _at_her_auth_date(monkeypatch)
    answer = client.post("/mini-app/qr", headers=_launch("999000111"))
    assert answer.status_code == 403
    assert answer.json()["error"] == "not_registered"


def test_a_registered_specialist_gets_a_code(configured, client, monkeypatch, registered):
    _at_her_auth_date(monkeypatch)
    answer = client.post("/mini-app/qr", headers=_launch(registered["telegram_user_id"]))
    assert answer.status_code == 200
    body = answer.json()
    assert body["svg"].startswith("data:image/svg+xml;base64,")
    assert body["expires_at"] > 0
    assert body["rotate_seconds"] == config.JOIN_QR_ROTATE_SECONDS


def test_two_asks_are_two_different_codes(configured, client, monkeypatch, registered):
    """It rotates, which is the whole reason the mini app exists rather than a printed sign."""
    _at_her_auth_date(monkeypatch)
    headers = _launch(registered["telegram_user_id"])
    first = client.post("/mini-app/qr", headers=headers).json()["svg"]
    second = client.post("/mini-app/qr", headers=headers).json()["svg"]
    assert first != second


def test_no_signing_secret_means_no_code_rather_than_an_unsigned_one(
    configured, client, monkeypatch, registered
):
    _at_her_auth_date(monkeypatch)
    monkeypatch.setattr(config, "JOIN_LINK_SECRET", "")
    body = client.post("/mini-app/qr", headers=_launch(registered["telegram_user_id"])).json()
    assert body["svg"] == ""


def test_a_stale_launch_is_refused_so_a_stolen_init_data_does_not_last(
    configured, client, monkeypatch, registered
):
    monkeypatch.setattr(
        mini_app.time,
        "time",
        lambda: GOLDEN_AUTH_DATE + config.MINI_APP_INIT_DATA_MAX_AGE_SECONDS + 5,
    )
    answer = client.post("/mini-app/qr", headers=_launch(registered["telegram_user_id"]))
    assert answer.status_code == 401
    assert answer.json()["error"] == "expired"


# --- [3] What she reads, and what it must never carry ----------------------------------------


def test_the_line_she_reads_carries_no_telephone(configured, client, monkeypatch, registered):
    """Her number tells two clients apart and is not a thing a specialist reads
    (docs/BRAND_VOICE.md §7)."""
    from tests.conftest import KNOWN_CLIENTS

    _at_her_auth_date(monkeypatch)
    body = client.post("/mini-app/queue", headers=_launch(registered["telegram_user_id"])).text
    for phone in KNOWN_CLIENTS.values():
        assert phone not in body


def test_the_line_names_every_area_even_when_it_is_empty(
    configured, client, monkeypatch, registered
):
    _at_her_auth_date(monkeypatch)
    body = client.post("/mini-app/queue", headers=_launch(registered["telegram_user_id"])).json()
    assert [line["area"] for line in body["lines"]] == [
        name for _, name in mini_app.queue_http.AREAS
    ]
    assert body["empty_label"] == mini_app.MINI_APP_NOBODY_TEXT


# --- [4] The one policy in this service that must NOT deny framing ---------------------------


def test_the_mini_app_admits_telegram_as_a_frame_ancestor(configured, client):
    """A mini app IS framed by Telegram Web, so `'none'` here would break it outright — which is
    why this route's policy differs from every other page in the service."""
    policy = client.get("/mini-app").headers["content-security-policy"]
    assert "frame-ancestors https://web.telegram.org" in policy
    assert "frame-ancestors 'none'" not in policy


def test_the_mini_app_sets_no_x_frame_options_because_telegram_frames_it(configured, client):
    """It has no origin-list form, so ANY value breaks the mini app. Nothing sets it today; this
    is here so a later "security headers" sweep breaks a test instead of the salon."""
    assert "x-frame-options" not in {k.lower() for k in client.get("/mini-app").headers}


def test_the_policy_admits_telegrams_sdk_and_the_pages_own_script_and_no_third(configured, client):
    policy = client.get("/mini-app").headers["content-security-policy"]
    assert f"script-src 'self' {mini_app_page.SDK}" in policy
    assert "connect-src 'self'" in policy
    assert "img-src 'self' data:" in policy


def test_the_join_page_and_the_mini_app_differ_on_framing_and_on_scripts(configured, client):
    """One test naming the difference, so neither policy can be copied onto the other by mistake."""
    from aziza_adk import queue_http

    assert "frame-ancestors 'none'" in queue_http.HEADERS["Content-Security-Policy"]
    assert "script-src" not in queue_http.HEADERS["Content-Security-Policy"]
    assert "form-action 'none'" in mini_app.HEADERS["Content-Security-Policy"]
