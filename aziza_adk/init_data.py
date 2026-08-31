"""Telegram's own proof of who opened the mini app, checked without a network and without a clock.

Stdlib only and pure — `now` is a parameter — so the whole chain is a golden vector rather than a
thing that happens to work today. docs/PROJECT_DEFINITION.md §14.

**This does not invent a credential; it reads the one §3 already names.** `initData.user.id` is the
Telegram id the `specialists` table keys on, so a mini app request is authorized exactly as a
message is: by a row the salon registered in advance. What Telegram adds is a signature, which a
webhook delivery does not have.

Nothing here logs, and nothing here raises. Every failure is a returned reason, so no traceback and
no log line can carry the bot token or the signed string that was checked against it.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from urllib.parse import parse_qsl

REASON_NO_TOKEN = "no_token"
REASON_MALFORMED = "malformed"
REASON_BAD_SIGNATURE = "bad_signature"
REASON_EXPIRED = "expired"
REASON_FROM_THE_FUTURE = "from_the_future"

#: The literal Telegram keys the secret with. It is the KEY and the bot token is the MESSAGE, which
#: is inverted from the intuition — and getting it the wrong way round produces a function that
#: rejects every real open with no other symptom.
_KEYING = b"WebAppData"

#: Fields excluded from the checked string. `hash` is the signature itself; `signature` is
#: Telegram's separate third-party Ed25519 field and is not part of this HMAC.
_NOT_SIGNED = ("hash", "signature")

#: How far ahead of us a launch may claim to be before it is clock skew rather than staleness. The
#: two are different operational problems and collapsing them sends whoever reads the log to the
#: wrong one.
_FUTURE_TOLERANCE_S = 60


@dataclass(frozen=True)
class Verified:
    """A launch that held. `telegram_user_id` is a str, which is what `specialists` keys on."""

    telegram_user_id: str
    auth_date: int


@dataclass(frozen=True)
class Rejected:
    """A launch that did not hold, and the one REASON_* it failed on. Carries no input."""

    reason: str


def verify(init_data: str, *, bot_token: str, now: float, max_age_s: int) -> Verified | Rejected:
    """Check Telegram's `initData` and return who opened the app, or the one reason it failed.

    The ORDER is the design. The signature is checked before `user` is parsed as JSON, so untrusted
    JSON is never handed to a parser on the strength of a string anybody can post — the same
    ordering `agent_webview.tokens.verify` takes, for the same reason.

    An empty `bot_token` refuses rather than passes, as an unset webhook secret does.
    """
    if not bot_token:
        return Rejected(REASON_NO_TOKEN)
    try:
        # `keep_blank_values` is REQUIRED: a present-but-empty field still appears in the string
        # Telegram signed, and dropping it fails the HMAC on a perfectly good launch.
        fields = dict(parse_qsl(init_data, strict_parsing=True, keep_blank_values=True))
    except ValueError:
        return Rejected(REASON_MALFORMED)

    supplied = fields.get("hash", "")
    if not supplied:
        return Rejected(REASON_MALFORMED)

    checked = "\n".join(
        f"{key}={value}" for key, value in sorted(fields.items()) if key not in _NOT_SIGNED
    )
    secret = hmac.new(_KEYING, bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, checked.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, supplied):
        return Rejected(REASON_BAD_SIGNATURE)

    try:
        auth_date = int(fields["auth_date"])
        user_id = json.loads(fields["user"])["id"]
    except (KeyError, ValueError, TypeError):
        return Rejected(REASON_MALFORMED)
    if not isinstance(user_id, int):
        return Rejected(REASON_MALFORMED)

    if auth_date > now + _FUTURE_TOLERANCE_S:
        return Rejected(REASON_FROM_THE_FUTURE)
    if now - auth_date > max_age_s:
        return Rejected(REASON_EXPIRED)
    return Verified(telegram_user_id=str(user_id), auth_date=auth_date)
