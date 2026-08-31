"""Telegram's proof of who opened the mini app, asserted from values.

No network, no model, no clock. THE property is [1]: a FROZEN string, signed once outside this file
and pasted in. The algorithm is not recomputed here, because a test that recomputes it agrees with
its own bug — and the bug this function invites is silent and total.

[2] is that one bug. Telegram keys the secret with the literal `"WebAppData"` and passes the bot
token as the MESSAGE. Swapped, every real launch is refused and nothing else is wrong, so the case
that swaps them deliberately is the highest-value assertion in the file.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from urllib.parse import urlencode

import pytest

from aziza_adk import init_data

#: Generated once against the throwaway token below and pasted, never recomputed. A change to the
#: signing chain has to make this literal fail rather than move with it.
GOLDEN_TOKEN = "123456:THIS-IS-A-THROWAWAY-BOT-TOKEN"
GOLDEN_INIT_DATA = (
    "auth_date=1800000000&chat_instance=-1234567890123456789&chat_type=private"
    "&user=%7B%22id%22%3A700000001%2C%22first_name%22%3A%22Yamil%C3%A9%22%2C"
    "%22language_code%22%3A%22es%22%7D"
    "&hash=00a21cdcf86f52bcb2e54e4546ec47995209e1ef702068a9382023e6af3e683a"
)
GOLDEN_AUTH_DATE = 1_800_000_000
GOLDEN_USER_ID = "700000001"

_DAY = 86400


def _signed(bot_token: str = GOLDEN_TOKEN, **overrides) -> str:
    """A signed launch for the CASES THAT EXPECT A REFUSAL, and for freshness.

    Correctness is the golden literal's job. This exists so a case can vary one field without
    hand-signing, and every case built on it asserts a rejection or a clock, never the signature.
    """
    fields = {
        "auth_date": str(GOLDEN_AUTH_DATE),
        "chat_type": "private",
        "user": json.dumps({"id": 700000001}, separators=(",", ":")),
    }
    fields.update({k: str(v) for k, v in overrides.items()})
    checked = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    signed = hmac.new(secret, checked.encode(), hashlib.sha256).hexdigest()
    return urlencode({**fields, "hash": signed})


def _verify(init: str, *, token: str = GOLDEN_TOKEN, at: float | None = None, age: int = _DAY):
    return init_data.verify(
        init, bot_token=token, now=GOLDEN_AUTH_DATE + 1 if at is None else at, max_age_s=age
    )


# --- [1] The golden vector --------------------------------------------------------------------


def test_a_launch_signed_the_way_telegram_signs_one_verifies():
    result = _verify(GOLDEN_INIT_DATA)
    assert isinstance(result, init_data.Verified), getattr(result, "reason", result)
    assert result.telegram_user_id == GOLDEN_USER_ID
    assert result.auth_date == GOLDEN_AUTH_DATE


def test_the_user_id_comes_back_as_the_string_the_specialists_table_keys_on():
    """An int here refuses EVERY registered specialist, because `specialists.telegram_user_id` is
    TEXT and the edge matches by equality (§3). Silent, and total."""
    result = _verify(GOLDEN_INIT_DATA)
    assert isinstance(result.telegram_user_id, str)


# --- [2] The one bug this function invites ----------------------------------------------------


def test_the_secret_is_keyed_with_the_literal_and_not_with_the_bot_token():
    """THE case. Keyed the other way round — token as key, `"WebAppData"` as message — the digest
    differs, so a launch signed that way must be refused. If it were accepted, the production
    chain and this one are the same wrong chain."""
    fields = {
        "auth_date": str(GOLDEN_AUTH_DATE),
        "user": json.dumps({"id": 700000001}, separators=(",", ":")),
    }
    checked = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    inverted_secret = hmac.new(GOLDEN_TOKEN.encode(), b"WebAppData", hashlib.sha256).digest()
    signed = hmac.new(inverted_secret, checked.encode(), hashlib.sha256).hexdigest()
    result = _verify(urlencode({**fields, "hash": signed}))
    assert isinstance(result, init_data.Rejected)
    assert result.reason == init_data.REASON_BAD_SIGNATURE


def test_another_bots_token_does_not_open_this_bots_app():
    result = _verify(GOLDEN_INIT_DATA, token="999999:SOME-OTHER-BOT")
    assert isinstance(result, init_data.Rejected)
    assert result.reason == init_data.REASON_BAD_SIGNATURE


@pytest.mark.parametrize("field", ["auth_date", "chat_type", "user"])
def test_a_field_changed_after_signing_fails_on_the_signature(field):
    signed = _signed()
    tampered = signed.replace(f"{field}=", f"{field}=x", 1)
    result = _verify(tampered, at=GOLDEN_AUTH_DATE + 1)
    assert isinstance(result, init_data.Rejected)
    assert result.reason == init_data.REASON_BAD_SIGNATURE


def test_a_wrong_hash_over_unparseable_user_json_fails_on_the_signature_first():
    """The ORDERING property: untrusted JSON is never handed to a parser on the strength of a
    string anybody can post. Reason must be the signature, not malformed."""
    result = _verify("auth_date=1800000000&user=NOT-JSON&hash=" + "0" * 64)
    assert isinstance(result, init_data.Rejected)
    assert result.reason == init_data.REASON_BAD_SIGNATURE


def test_an_empty_bot_token_refuses_rather_than_passing():
    """The direction an unset credential must fail in — the same one `tokens.verify` takes on an
    empty secret list, and the same one the webhook takes with no secret configured."""
    result = _verify(GOLDEN_INIT_DATA, token="")
    assert isinstance(result, init_data.Rejected)
    assert result.reason == init_data.REASON_NO_TOKEN


def test_a_launch_carrying_the_signature_field_verifies():
    """THE regression. Telegram signs "all received fields, sorted alphabetically" minus `hash` —
    and `signature`, which belongs to the separate third-party method, is a received field like any
    other. Excluding it too rejected every real launch, with nothing to see but `bad_signature`."""
    fields = {
        "auth_date": str(GOLDEN_AUTH_DATE),
        "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
        "signature": "3PW1cVEbTFRvzXMFTZ3nMWyMV0MzWZeBhhcSDWqL0BM",
        "user": json.dumps({"id": 700000001}, separators=(",", ":")),
    }
    checked = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", GOLDEN_TOKEN.encode(), hashlib.sha256).digest()
    signed = hmac.new(secret, checked.encode(), hashlib.sha256).hexdigest()
    result = _verify(urlencode({**fields, "hash": signed}))
    assert isinstance(result, init_data.Verified), getattr(result, "reason", result)
    assert result.telegram_user_id == GOLDEN_USER_ID


def test_only_the_hash_is_left_out_of_what_is_checked():
    """Stated as a property rather than left to the chain above: any second exclusion silently
    un-signs a field, and the symptom is indistinguishable from a wrong bot token."""
    assert init_data._NOT_SIGNED == ("hash",)


# --- [3] Malformed input is a reason, never an exception --------------------------------------


@pytest.mark.parametrize("raw", ["", "hash=", "nothash=x", "&&&", "auth_date=1800000000", "%%%"])
def test_a_launch_nobody_could_have_sent_is_refused_rather_than_raising(raw):
    """This runs on a route, so anything that raises is a 500 anybody can produce at will."""
    assert isinstance(_verify(raw), init_data.Rejected)


def test_a_signed_launch_with_no_user_is_malformed_rather_than_verified():
    result = _verify(_signed(user=""), at=GOLDEN_AUTH_DATE + 1)
    assert isinstance(result, init_data.Rejected)
    assert result.reason == init_data.REASON_MALFORMED


# --- [4] Freshness is a value, because the clock is an argument -------------------------------


def test_a_launch_inside_the_window_is_fresh():
    assert isinstance(_verify(_signed(), at=GOLDEN_AUTH_DATE + _DAY, age=_DAY), init_data.Verified)


def test_a_launch_one_second_past_the_window_is_expired():
    result = _verify(_signed(), at=GOLDEN_AUTH_DATE + _DAY + 1, age=_DAY)
    assert isinstance(result, init_data.Rejected)
    assert result.reason == init_data.REASON_EXPIRED


def test_a_launch_from_the_future_is_its_own_reason():
    """Clock skew between the pod and Telegram is a different operational problem from a stale
    open, and one reason for both sends whoever reads the log to the wrong one."""
    result = _verify(_signed(), at=GOLDEN_AUTH_DATE - 3600, age=_DAY)
    assert isinstance(result, init_data.Rejected)
    assert result.reason == init_data.REASON_FROM_THE_FUTURE


# --- [5] Nothing it returns can leak the credential -------------------------------------------


def test_nothing_returned_carries_the_bot_token_or_the_signature():
    """Asserted rather than promised: a `Rejected` that carried its input would put the signed
    string into every traceback that formats it."""
    for result in (_verify(GOLDEN_INIT_DATA), _verify(GOLDEN_INIT_DATA, token="wrong")):
        rendered = repr(result)
        assert GOLDEN_TOKEN not in rendered
        assert "THROWAWAY" not in rendered
        assert "hash=" not in rendered
