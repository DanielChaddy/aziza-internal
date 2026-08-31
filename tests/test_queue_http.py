"""The two routes a client reaches, driven through a real app with no model anywhere.

THE property is [1]: this is the only entry the internet reaches with no credential of any kind, so
what it refuses and what it says while refusing are the whole of its security. A stale code says
so, because that is the failure a real client actually hits; every other reason says nothing,
because the difference would answer questions about the secret for whoever is asking.

**The clock is pinned in every case.** `hours.is_open` gates the join, so a suite left on the real
clock would exercise the closed path every Sunday and Monday and pass — which is a green run that
asserted nothing about the form.
"""

from __future__ import annotations

import datetime as dt
import time

import pytest
from agent_webview import tokens
from fastapi.testclient import TestClient

from aziza_adk import config, join, queue_http, queue_text, tools
from tests.conftest import KNOWN_CLIENTS

_SECRET = "a-test-signing-secret-nobody-uses"
_TZ = dt.timezone(dt.timedelta(hours=-4))
#: A Tuesday mid-afternoon: open, and nowhere near either edge of the schedule.
_OPEN = dt.datetime(2026, 9, 1, 14, 0, tzinfo=_TZ)
#: A Monday. The salon does not open at all — docs/PROJECT_DEFINITION.md §8.
_SHUT = dt.datetime(2026, 8, 31, 14, 0, tzinfo=_TZ)


@pytest.fixture
def open_salon(monkeypatch):
    """A configured service with the salon open and the clock still."""
    monkeypatch.setattr(config, "JOIN_LINK_SECRET", _SECRET)
    monkeypatch.setattr(config, "JOIN_LINK_SECRET_PREVIOUS", "")
    monkeypatch.setattr(config, "JOIN_BASE_URL", "https://example.test")
    monkeypatch.setattr(tools, "now", lambda: _OPEN)
    queue_http._SPENT.clear()
    yield
    queue_http._SPENT.clear()


@pytest.fixture
def client():
    from aziza_adk.channel import app

    return TestClient(app)


def _code() -> str:
    return join.link_for(1, now=time.time(), nonce=join.new_nonce()).rsplit("/", 1)[-1]


# --- [1] The only unauthenticated entry, and what it refuses ---------------------------------


def test_the_form_opens_for_a_live_code(open_salon, client):
    page = client.get(f"/j/{_code()}")
    assert page.status_code == 200
    assert "<form" in page.text
    assert page.text.count("type=checkbox") == len(queue_http.AREAS)


def test_a_stale_code_says_so_and_a_forged_one_says_nothing(open_salon, client):
    """The one distinction worth making, and the only one made."""
    stale = join.link_for(1, now=time.time() - 100_000, nonce=join.new_nonce()).rsplit("/", 1)[-1]
    said = client.get(f"/j/{stale}")
    assert said.status_code == 410
    assert queue_text.EXPIRED_CLIENT_COPY in said.text

    forged = client.get("/j/not-a-real-token")
    assert forged.status_code == 404
    assert queue_text.NOT_FOUND_CLIENT_COPY in forged.text


def test_a_code_signed_with_another_secret_is_a_404_like_any_other_forgery(open_salon, client):
    other = tokens.mint(
        "a-different-secret",
        audience=join.JOIN,
        claims={join.CLAIM_BY: 1},
        ttl_s=300,
        now=time.time(),
        nonce=join.new_nonce(),
    )
    assert client.get(f"/j/{other}").status_code == 404


def test_a_code_for_another_view_does_not_open_the_join_page(open_salon, client):
    elsewhere = tokens.mint(
        _SECRET,
        audience="mini-app",
        claims={join.CLAIM_BY: 1},
        ttl_s=300,
        now=time.time(),
        nonce=join.new_nonce(),
    )
    assert client.get(f"/j/{elsewhere}").status_code == 404


def test_nothing_can_be_joined_while_the_salon_is_closed(open_salon, client, monkeypatch):
    """The grace hour is a specialist's, for the client already in her chair. A client asking to be
    STARTED at 19:30 is asking for something the salon cannot do (§13)."""
    monkeypatch.setattr(tools, "now", lambda: _SHUT)
    code = _code()
    assert queue_text.CLOSED_CLIENT_COPY in client.get(f"/j/{code}").text
    posted = client.post(f"/j/{code}", data={"phone": "8090000002", "areas": "nails"})
    assert queue_text.CLOSED_CLIENT_COPY in posted.text


# --- [2] The headers are the rest of its security -------------------------------------------


def test_the_join_page_carries_the_policy_it_needs_and_nothing_more(open_salon, client):
    """Written out rather than compared to the module, so loosening the policy has to be done in
    two places and the second is a test somebody has to justify."""
    headers = client.get(f"/j/{_code()}").headers
    assert headers["content-security-policy"] == (
        "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
        "base-uri 'none'; frame-ancestors 'none'"
    )
    assert headers["referrer-policy"] == "no-referrer"
    assert headers["cache-control"] == "no-store, private"
    assert headers["x-robots-tag"] == "noindex, nofollow"


def test_the_token_cannot_leave_in_a_referer(open_salon, client):
    """It is in the PATH, so this header is the whole of what stops the credential walking out the
    moment the page links anywhere."""
    assert client.get(f"/j/{_code()}").headers["referrer-policy"] == "no-referrer"


def test_the_page_may_post_to_itself_and_may_not_be_framed(open_salon, client):
    policy = client.get(f"/j/{_code()}").headers["content-security-policy"]
    assert "form-action 'self'" in policy
    assert "frame-ancestors 'none'" in policy


def test_the_page_carries_no_script_at_all(open_salon, client):
    """No `script-src` in the policy is only honest while there is no script in the page."""
    page = client.get(f"/j/{_code()}")
    assert "<script" not in page.text
    assert "script-src" not in page.headers["content-security-policy"]


# --- [3] What she typed, refused before anything is written ----------------------------------


@pytest.mark.parametrize(
    "data,expected",
    [
        ({"phone": "80955", "areas": "nails"}, queue_text.BAD_PHONE_CLIENT_COPY),
        ({"phone": "8090000002"}, queue_text.NO_AREAS_CLIENT_COPY),
        ({"phone": "8090000002", "areas": "massage"}, queue_text.NO_AREAS_CLIENT_COPY),
    ],
)
def test_a_submission_that_cannot_be_acted_on_comes_back_saying_why(
    open_salon, client, sentinel, data, expected
):
    posted = client.post(f"/j/{_code()}", data=data)
    assert posted.status_code == 400
    assert expected in posted.text


def test_what_she_already_typed_survives_the_complaint(open_salon, client, sentinel):
    """A form that clears itself is one she fills in twice and abandons."""
    posted = client.post(f"/j/{_code()}", data={"phone": "80955", "areas": "nails"})
    assert 'value="nails" checked' in posted.text


def test_a_name_the_page_echoes_back_is_escaped(open_salon, client, sentinel):
    """She controls this string and the page renders it. `agent_webview.spec.esc` is the one
    escape; this asserts it is actually reached."""
    posted = client.post(
        f"/j/{_code()}",
        data={"phone": "80955", "areas": "nails", "name": "<script>alert(1)</script>"},
    )
    assert "<script>alert(1)</script>" not in posted.text
    assert "&lt;script&gt;" in posted.text


# --- [4] Joining, which is the only thing it writes -----------------------------------------


def test_a_client_the_salon_knows_reaches_the_line_in_one_post(open_salon, client, sentinel):
    """The whole point of a returning client scanning: her number is enough, and she is in."""
    posted = client.post(f"/j/{_code()}", data={"phone": KNOWN_CLIENTS["Carmen"], "areas": "nails"})
    assert posted.status_code == 200
    assert "Ya estás en la fila" in posted.text
    assert "Carmen" in posted.text


def test_a_client_the_salon_does_not_know_is_asked_her_name_and_then_joins(
    open_salon, client, sentinel
):
    code = _code()
    asked = client.post(f"/j/{code}", data={"phone": "8095550188", "areas": "nails"})
    assert asked.status_code == 400
    assert queue_text.ASK_NAME_CLIENT_COPY in asked.text

    joined = client.post(
        f"/j/{code}",
        data={"phone": "8095550188", "areas": "nails", "name": "Zoraida Prueba"},
    )
    assert joined.status_code == 200
    assert "Zoraida Prueba" in joined.text


def test_her_place_in_the_line_is_on_the_page(open_salon, client, sentinel):
    code = _code()
    client.post(f"/j/{code}", data={"phone": KNOWN_CLIENTS["Carmen"], "areas": "nails"})
    second = client.post(f"/j/{code}", data={"phone": KNOWN_CLIENTS["Ana"], "areas": "nails"})
    assert "número 2" in second.text


def test_scanning_again_keeps_the_place_she_already_had(open_salon, client, sentinel):
    """Idempotent by construction — `queries.record_arrival` reuses the arrival she is standing in,
    which is what stops a second scan putting one woman in the line twice (§12)."""
    code = _code()
    client.post(f"/j/{code}", data={"phone": KNOWN_CLIENTS["Carmen"], "areas": "nails"})
    again = client.post(f"/j/{code}", data={"phone": KNOWN_CLIENTS["Carmen"], "areas": "nails"})
    assert "Ya estabas en la fila" in again.text


def test_two_scans_in_one_instant_cannot_each_write_an_arrival(open_salon, client, sentinel, conn):
    """The reuse above is a read-then-write, so it holds only while the two are serialized — and a
    double-tapped form is two requests at this entry, which has no turn lock in front of it.

    Asserted by holding the lock the write takes and giving the writer a deadline: with the
    serialization gone the writer does not wait at all and this goes red, which is what makes it a
    gate rather than a description.
    """
    import psycopg

    from aziza_adk import queries

    carmen = queries.clients_on_phone(conn, KNOWN_CLIENTS["Carmen"])[0]["id"]
    day = tools.now().date()
    holder, writer = queries.connect(), queries.connect()
    try:
        with holder.cursor() as cur:
            # The PAIR is the contract. A lock keyed on anything else serializes the wrong thing.
            cur.execute("SELECT pg_advisory_xact_lock(%s, %s)", (carmen, day.toordinal()))
        with writer.cursor() as cur:
            cur.execute("SET lock_timeout = '500ms'")
        with pytest.raises(psycopg.errors.LockNotAvailable):
            queries.record_arrival(writer, carmen, day, ("nails",))
    finally:
        for connection in (writer, holder):
            connection.rollback()
            connection.close()


def test_two_clients_on_one_number_are_asked_which_she_is(open_salon, client, sentinel, conn):
    """A number reaches a mother and her daughter, and the pair is the identity (§3). Offered
    rather than typed, because the half she is missing is a name the salon already holds."""
    from aziza_adk import queries

    queries.create_client(conn, "Hija Prueba", KNOWN_CLIENTS["Carmen"])
    asked = client.post(f"/j/{_code()}", data={"phone": KNOWN_CLIENTS["Carmen"], "areas": "nails"})
    assert asked.status_code == 200
    assert queue_text.WHICH_ONE_CLIENT_COPY in asked.text
    assert "Hija Prueba" in asked.text and "Carmen" in asked.text
    assert "type=radio" in asked.text


def test_a_client_id_for_somebody_on_another_number_is_ignored(open_salon, client, sentinel, conn):
    """An id in the body is a value anybody with a live code can type. It selects between the
    candidates THIS number reaches or it selects nothing."""
    from aziza_adk import queries

    ana = queries.clients_on_phone(conn, KNOWN_CLIENTS["Ana"])[0]["id"]
    posted = client.post(
        f"/j/{_code()}",
        data={"phone": KNOWN_CLIENTS["Carmen"], "areas": "nails", "client_id": str(ana)},
    )
    assert posted.status_code == 200
    assert "Carmen" in posted.text


def test_a_get_never_writes(open_salon, client, sentinel, conn):
    """Link scanners and in-app browsers fetch a URL before anybody taps it, so a side effect here
    runs with no reader — `agent_webview.router` is built on the same rule."""
    from aziza_adk import queries

    before = queries.fetchall(conn, "SELECT count(*) AS n FROM arrivals")[0]["n"]
    client.get(f"/j/{_code()}")
    assert queries.fetchall(conn, "SELECT count(*) AS n FROM arrivals")[0]["n"] == before


# --- [5] One code is not one join, and is not unlimited either -------------------------------


def test_several_clients_may_scan_the_same_displayed_code(open_salon, client, sentinel):
    """A code sits on a screen for two minutes and whoever walks up scans it. Single-use would
    refuse the second real client of the afternoon, which is why the ceiling is a ceiling."""
    code = _code()
    first = client.post(f"/j/{code}", data={"phone": KNOWN_CLIENTS["Carmen"], "areas": "nails"})
    second = client.post(f"/j/{code}", data={"phone": KNOWN_CLIENTS["Ana"], "areas": "nails"})
    assert first.status_code == 200 and second.status_code == 200
    assert "Ana" in second.text


def test_one_code_stops_admitting_once_it_has_had_its_fill(open_salon, client, sentinel):
    """The ceiling bounds a script rather than a salon: reaching it takes more scans of one code
    than a rotation window could ever carry."""
    code = _code()
    for _ in range(queue_http.MAX_JOINS_PER_CODE):
        client.post(f"/j/{code}", data={"phone": "80955", "areas": "nails"})
    spent = client.post(f"/j/{code}", data={"phone": KNOWN_CLIENTS["Carmen"], "areas": "nails"})
    assert spent.status_code == 429
    assert queue_text.EXPIRED_CLIENT_COPY in spent.text


def test_a_fresh_code_has_its_own_allowance(open_salon, client, sentinel):
    code = _code()
    for _ in range(queue_http.MAX_JOINS_PER_CODE):
        client.post(f"/j/{code}", data={"phone": "80955", "areas": "nails"})
    assert (
        client.post(
            f"/j/{_code()}", data={"phone": KNOWN_CLIENTS["Carmen"], "areas": "nails"}
        ).status_code
        == 200
    )
