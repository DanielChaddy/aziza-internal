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
GATED = [
    ("POST", "/mini-app/apps"),
    ("POST", "/mini-app/qr"),
    ("POST", "/mini-app/queue"),
    ("POST", "/mini-app/supplies"),
    ("POST", "/mini-app/supplies/bought"),
    ("POST", "/mini-app/supplies/photo"),
]

#: What only an owner may reach. Gated twice — the launcher decides what she is OFFERED, and the
#: route decides what she may READ (§16).
OWNER_ONLY = [
    ("POST", "/mini-app/supplies"),
    ("POST", "/mini-app/supplies/bought"),
    ("POST", "/mini-app/supplies/photo"),
]


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", GOLDEN_TOKEN)
    monkeypatch.setattr(config, "JOIN_LINK_SECRET", "a-test-signing-secret-nobody-uses")
    monkeypatch.setattr(config, "JOIN_LINK_SECRET_PREVIOUS", "")
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "https://example.test")
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


@pytest.fixture
def owner(make_specialist):
    """An owner: the one person the list of things to buy is for (§16)."""
    return make_specialist(roles=("owner",), full_name="Zoila Sentinel")


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
    # `blob:` is what a photograph fetched WITH the credential becomes: an <img src> carries no
    # header, so the bytes are read by `fetch` and handed to the document as an object URL.
    assert "img-src 'self' data: blob:" in policy


def test_the_join_page_and_the_mini_app_differ_on_framing_and_on_scripts(configured, client):
    """One test naming the difference, so neither policy can be copied onto the other by mistake."""
    from aziza_adk import queue_http

    assert "frame-ancestors 'none'" in queue_http.HEADERS["Content-Security-Policy"]
    assert "script-src" not in queue_http.HEADERS["Content-Security-Policy"]
    assert "form-action 'none'" in mini_app.HEADERS["Content-Security-Policy"]


# --- [5] One shell, and the apps her own row lets her open -----------------------------------


def test_a_specialist_is_offered_the_queue_app_and_nothing_else():
    """Showing a client the code is the one thing every specialist does. The list is an owner's,
    because she is the one who goes to the shop (§16)."""
    assert [app["key"] for app in mini_app.apps_for({"roles": []})] == [mini_app.QUEUE]


def test_an_owner_is_offered_both():
    offered = mini_app.apps_for({"roles": ["owner"]})
    assert [app["key"] for app in offered] == [mini_app.QUEUE, mini_app.SUPPLIES]


def test_a_row_with_no_roles_at_all_is_read_as_holding_none():
    """Fails closed on a row shaped differently than expected, rather than on a KeyError that
    would take the whole launch down."""
    assert [app["key"] for app in mini_app.apps_for({})] == [mini_app.QUEUE]


def test_every_offered_app_has_a_view_in_the_page(configured, client):
    """A key offered here with no section of that id in the shell is a tap into a blank screen —
    and nothing else would catch it, because the launcher renders whatever it is handed."""
    page = client.get("/mini-app").text
    for key in (mini_app.QUEUE, mini_app.SUPPLIES):
        assert f"<section id={key} hidden>" in page or f'<section id="{key}" hidden>' in page


def test_the_script_and_the_shell_agree_on_every_id(configured, client):
    """They are two files with no compiler between them, so a rename in one is a silent break in
    the other: the page loads, the console is clean, and nothing renders."""
    import re

    page = client.get("/mini-app").text
    script = client.get("/mini-app/app.js").text
    wanted = set(re.findall(r'getElementById\("([^"]+)"\)', script))
    assert wanted
    for name in wanted:
        assert re.search(rf'id=["\']?{name}\b', page), name


def test_the_launcher_names_the_apps_and_the_way_back(configured, client, monkeypatch, registered):
    _at_her_auth_date(monkeypatch)
    body = client.post("/mini-app/apps", headers=_launch(registered["telegram_user_id"])).json()
    assert [app["label"] for app in body["apps"]] == [mini_app.MINI_APP_HEADING_TEXT]
    assert body["choose_label"] == mini_app.LAUNCHER_HEADING_TEXT
    assert body["back_label"] == mini_app.BACK_TEXT


def test_an_owner_is_offered_two_apps_over_the_wire(configured, client, monkeypatch, owner):
    _at_her_auth_date(monkeypatch)
    body = client.post("/mini-app/apps", headers=_launch(owner["telegram_user_id"])).json()
    assert [app["key"] for app in body["apps"]] == [mini_app.QUEUE, mini_app.SUPPLIES]


# --- [6] What the salon needs, and who may read it --------------------------------------------


@pytest.mark.parametrize("method,path", OWNER_ONLY)
def test_a_specialist_who_is_not_an_owner_reaches_none_of_the_list(
    configured, client, monkeypatch, registered, method, path
):
    """Gated twice on purpose: the launcher decides what she is OFFERED, and this decides what
    she may reach. A launcher trusted to be the gate is a gate in the page."""
    _at_her_auth_date(monkeypatch)
    answer = client.request(
        method, path, headers=_launch(registered["telegram_user_id"]), json={"ids": [1]}
    )
    assert answer.status_code == 403
    assert answer.json()["error"] == "not_an_owner"


def test_an_owner_reads_the_list_with_every_label_on_it(configured, client, monkeypatch, owner):
    """The copy travels WITH the data, so every Spanish literal in this app is a constant
    `tests/test_voice.py` can find — docs/BRAND_VOICE.md §6."""
    _at_her_auth_date(monkeypatch)
    body = client.post("/mini-app/supplies", headers=_launch(owner["telegram_user_id"])).json()
    assert body["empty_label"] == mini_app.SUPPLIES_EMPTY_TEXT
    assert body["bought_label"] == mini_app.SUPPLIES_BOUGHT_TEXT
    assert body["photo_label"] == mini_app.SUPPLIES_PHOTO_TEXT
    assert body["unlisted_label"] == mini_app.SUPPLIES_UNLISTED_TEXT
    assert isinstance(body["items"], list)


def test_what_one_owner_reports_the_other_can_tick_off(
    configured, client, monkeypatch, owner, make_specialist, conn
):
    """The round trip: somebody says it, an owner sees it with her name on it, ticks it, and it
    is gone. The tick answers with the list as it now stands rather than with a bare ok."""
    from aziza_adk import queries

    kathy = make_specialist("nails", full_name="Kathy Sentinel")
    queries.record_shortage(
        conn,
        supply_ref="",
        said="papel de camilla",
        note="queda un rollo",
        reported_by=kathy["id"],
    )
    _at_her_auth_date(monkeypatch)
    headers = _launch(owner["telegram_user_id"])
    listed = client.post("/mini-app/supplies", headers=headers).json()["items"]
    mine = [one for one in listed if one["label"] == "papel de camilla"]
    assert len(mine) == 1
    assert mine[0]["listed"] is False
    assert mine[0]["reports"][0]["who"] == "Kathy"
    assert mine[0]["reports"][0]["note"] == "queda un rollo"

    left = client.post("/mini-app/supplies/bought", headers=headers, json={"ids": mine[0]["ids"]})
    assert left.status_code == 200
    assert "papel de camilla" not in [one["label"] for one in left.json()["items"]]


def test_a_tick_naming_nothing_buys_nothing(configured, client, monkeypatch, owner, conn):
    """A body that is not a list of whole numbers is the one thing on these routes the PAGE
    supplies, so it marks none rather than being trusted into a query."""
    from aziza_adk import queries

    queries.record_shortage(conn, supply_ref="", said="algodón", note="", reported_by=owner["id"])
    _at_her_auth_date(monkeypatch)
    headers = _launch(owner["telegram_user_id"])
    left = client.post("/mini-app/supplies/bought", headers=headers, json={"ids": ["all", True]})
    assert "algodón" in [one["label"] for one in left.json()["items"]]


def test_a_report_with_no_picture_has_none_to_open(configured, client, monkeypatch, owner, conn):
    """By ROW rather than by handle: a `file_id` accepted here would let anybody holding one read
    any picture the bot can reach, which is every invoice the salon has photographed."""
    from aziza_adk import queries

    made = queries.record_shortage(
        conn, supply_ref="", said="guantes", note="", reported_by=owner["id"]
    )
    _at_her_auth_date(monkeypatch)
    answer = client.post(
        "/mini-app/supplies/photo",
        headers=_launch(owner["telegram_user_id"]),
        json={"ids": [made["id"]]},
    )
    assert answer.status_code == 404
    assert answer.json()["error"] == "no_photo"
