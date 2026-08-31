"""The one route an owner's browser reaches, driven through a real app with no model anywhere.

THE property is that the link is a CAPABILITY and nothing else: it carries the salon's whole month
of purchases, so what it refuses and what it says while refusing are the whole of its security.
A stale link says so; every other reason says nothing — docs/PROJECT_DEFINITION.md §15.
"""

from __future__ import annotations

import datetime as dt
import time

import pytest
from fastapi.testclient import TestClient

from aziza_adk import config, join, reports

_SECRET = "a-report-signing-secret-nobody-uses"
_JOIN_SECRET = "a-join-signing-secret-nobody-uses"
AUGUST = dt.date(2026, 8, 1)


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(config, "REPORT_LINK_SECRET", _SECRET)
    monkeypatch.setattr(config, "REPORT_LINK_SECRET_PREVIOUS", "")
    monkeypatch.setattr(config, "JOIN_LINK_SECRET", _JOIN_SECRET)
    monkeypatch.setattr(config, "JOIN_LINK_SECRET_PREVIOUS", "")
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "https://example.test")
    monkeypatch.setattr(config, "SALON_RNC", "131999888")


@pytest.fixture
def client():
    from aziza_adk.channel import app

    return TestClient(app)


def _token(month=AUGUST, now=None) -> str:
    return reports.link_for(
        month, now=now if now is not None else time.time(), nonce=reports.new_nonce()
    ).rsplit("/", 1)[-1]


# --- [1] What the link is, and what it refuses ---------------------------------------------


def test_a_live_link_downloads_the_month_as_a_file(client, configured, conn, sentinel):
    """It arrives as an attachment rather than as a page: an accountant opens it in a spreadsheet,
    and a browser that rendered it inline would be the wrong tool."""
    answer = client.get(f"/r/{_token()}")
    assert answer.status_code == 200
    assert answer.headers["content-disposition"] == 'attachment; filename="606-202608.txt"'
    assert answer.text.startswith("131999888|202608|")


def test_the_body_is_never_cached_and_never_indexed(client, configured, conn, sentinel):
    """The body is the salon's whole month of purchases."""
    answer = client.get(f"/r/{_token()}")
    assert answer.headers["cache-control"] == "no-store, private"
    assert answer.headers["x-robots-tag"] == "noindex, nofollow"
    assert answer.headers["referrer-policy"] == "no-referrer"


def test_a_stale_link_says_it_is_stale(client, configured):
    """The one failure a real owner actually hits, so it is the one that is explained."""
    old = time.time() - config.REPORT_TOKEN_TTL_SECONDS - 60
    answer = client.get(f"/r/{_token(now=old)}")
    assert answer.status_code == 410


def test_a_forged_link_explains_nothing(client, configured):
    """Distinguishing forged from wrong-secret would answer questions about the secret for
    whoever is asking — `queue_http`'s reasoning, and the same here."""
    answer = client.get("/r/not-a-token-at-all")
    assert answer.status_code == 404
    assert "expired" not in answer.text.lower()


def test_a_join_token_does_not_open_the_report(client, configured):
    """Two audiences and two secrets. A code a client scanned off a counter must not download the
    salon's purchases, and the audience is what makes that structural (§15)."""
    code = join.link_for(1, now=time.time(), nonce=join.new_nonce()).rsplit("/", 1)[-1]
    assert client.get(f"/r/{code}").status_code == 404


def test_with_no_secret_configured_nothing_is_minted(monkeypatch):
    """Empty REFUSES rather than minting an unsigned link, which is the safe direction."""
    monkeypatch.setattr(config, "REPORT_LINK_SECRET", "")
    monkeypatch.setattr(config, "REPORT_LINK_SECRET_PREVIOUS", "")
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "https://example.test")
    assert reports.link_for(AUGUST, now=time.time(), nonce="n") == ""


def test_the_month_travels_in_the_token_rather_than_the_path(client, configured):
    """So it cannot be changed by editing the URL: one link, one month."""
    token = _token(dt.date(2026, 7, 1))
    answer = client.get(f"/r/{token}")
    assert answer.headers["content-disposition"].endswith('606-202607.txt"')
