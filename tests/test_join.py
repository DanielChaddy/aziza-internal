"""The code a client scans, asserted from values.

No database, no model and no network. THE property is [2]: the three numbers are one design, and
the one that matters is the grace a client still has AFTER the code she raised her phone at has
left the screen. Get it wrong and there is a window every rotation in which a real scan fails and
nobody can reproduce it.

[3] is the other half of what a token is for — it authorizes a VIEW and carries no credential, so
one minted for the join page cannot be replayed anywhere else and a client's browser history holds
nothing worth having.
"""

from __future__ import annotations

import pytest
from agent_webview import tokens

from aziza_adk import config, join

_SECRET = "a-test-signing-secret-nobody-uses"
_NOW = 1_800_000_000.0


@pytest.fixture(autouse=True)
def signing(monkeypatch):
    """A secret and a base URL, so the module under test is configured rather than disabled."""
    monkeypatch.setattr(config, "JOIN_LINK_SECRET", _SECRET)
    monkeypatch.setattr(config, "JOIN_LINK_SECRET_PREVIOUS", "")
    monkeypatch.setattr(config, "JOIN_BASE_URL", "https://example.test")


def _token(*, now: float = _NOW, nonce: str = "nonce-one") -> str:
    return join.link_for(7, now=now, nonce=nonce).rsplit("/", 1)[-1]


# --- [1] The link is a URL, and only a configured service makes one -------------------------


def test_the_link_points_at_the_join_view():
    assert join.link_for(7, now=_NOW, nonce="n").startswith("https://example.test/j/")


def test_no_secret_means_no_code_rather_than_an_unsigned_one(monkeypatch):
    """An unset secret disables the code. The alternative is a link that verifies for anybody,
    which is worse than a mini app showing nothing."""
    monkeypatch.setattr(config, "JOIN_LINK_SECRET", "")
    assert join.link_for(7, now=_NOW, nonce="n") == ""


def test_no_base_url_means_no_code_either(monkeypatch):
    monkeypatch.setattr(config, "JOIN_BASE_URL", "")
    assert join.link_for(7, now=_NOW, nonce="n") == ""


def test_two_mints_in_the_same_second_are_two_different_codes():
    """The nonce is what makes them differ, and the ceiling on joins is keyed per code — so two
    codes that collided would share one allowance."""
    assert _token(nonce="one") != _token(nonce="two")


# --- [2] Three numbers, one design ----------------------------------------------------------


def test_the_code_rotates_before_it_expires():
    """If rotation were the longer of the two there would be a dead code on the screen, and a
    client would scan something that cannot work however fast she is."""
    assert config.JOIN_QR_ROTATE_SECONDS < config.JOIN_TOKEN_TTL_SECONDS


def test_a_code_photographed_the_instant_before_it_rotated_still_opens():
    """THE property. She raised her phone at a code with one second left on screen, walked to a
    bench and typed: the grace is (ttl - rotate) + leeway, and it has to cover that walk."""
    grace = (
        config.JOIN_TOKEN_TTL_SECONDS - config.JOIN_QR_ROTATE_SECONDS
    ) + config.JOIN_TOKEN_LEEWAY_SECONDS
    late = _NOW + config.JOIN_QR_ROTATE_SECONDS + grace
    assert isinstance(join.opened(_token(), now=late), tokens.Verified)


def test_a_code_past_its_life_and_its_leeway_is_expired():
    dead = _NOW + config.JOIN_TOKEN_TTL_SECONDS + config.JOIN_TOKEN_LEEWAY_SECONDS + 1
    result = join.opened(_token(), now=dead)
    assert isinstance(result, tokens.Rejected)
    assert result.reason == tokens.REASON_EXPIRED


def test_the_grace_is_long_enough_to_type_a_name_into_the_form():
    """A client the salon does not know posts twice: once with her number, once with her name.
    A grace shorter than that sends her back to a code that has already changed."""
    assert config.JOIN_TOKEN_TTL_SECONDS >= 240


# --- [3] A token opens one view and carries no credential -----------------------------------


def test_a_join_code_opens_only_the_join_view():
    """Audience-bound, so a code cannot be replayed against a view it was not minted for."""
    result = tokens.verify(_token(), secrets=[_SECRET], audience="mini-app", now=_NOW + 1)
    assert isinstance(result, tokens.Rejected)
    assert result.reason == tokens.REASON_WRONG_AUDIENCE


def test_a_code_signed_with_another_secret_does_not_open_it(monkeypatch):
    forged = tokens.mint(
        "a-different-secret",
        audience=join.JOIN,
        claims={join.CLAIM_BY: 7},
        ttl_s=300,
        now=_NOW,
        nonce="n",
    )
    result = join.opened(forged, now=_NOW + 1)
    assert isinstance(result, tokens.Rejected)
    assert result.reason == tokens.REASON_BAD_SIGNATURE


def test_the_previous_secret_still_opens_a_code_so_a_rotation_is_not_an_outage(monkeypatch):
    older = tokens.mint(
        "the-previous-secret",
        audience=join.JOIN,
        claims={join.CLAIM_BY: 7},
        ttl_s=300,
        now=_NOW,
        nonce="n",
    )
    monkeypatch.setattr(config, "JOIN_LINK_SECRET_PREVIOUS", "the-previous-secret")
    assert isinstance(join.opened(older, now=_NOW + 1), tokens.Verified)


def test_the_link_names_no_telegram_id_and_no_telephone():
    """A URL lands in a client's browser history and in anything she shares. The Telegram id IS
    the credential (§3), and a telephone is half of an identity (§3) — neither belongs in one."""
    from aziza_adk import staff_data

    link = join.link_for(7, now=_NOW, nonce="n")
    for person in staff_data.STAFF:
        if person["telegram_user_id"]:
            assert person["telegram_user_id"] not in link


def test_what_the_code_carries_is_the_row_id_and_nothing_else():
    result = join.opened(_token(), now=_NOW + 1)
    assert result.claims == {join.CLAIM_BY: 7}
