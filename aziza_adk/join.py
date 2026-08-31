"""The link a QR encodes: what authorizes a join, and the only thing that does.

The signing is `agent_webview.tokens`, which is stdlib-only and takes the clock and the nonce as
arguments — so the exact string is a golden vector. Nothing is reimplemented here; this module
decides only what the claims mean and how long a code lives.
docs/PROJECT_DEFINITION.md §13.

**A token is a capability, not a person.** It proves somebody was standing where the code was
displayed within the last few minutes. It says nothing about who she is, and the page asks.
"""

from __future__ import annotations

import secrets

from agent_webview import tokens

from aziza_adk import config

#: The view the token opens, and a URL segment. Short on purpose: every character is QR modules,
#: and a code that scans across a counter is one a client does not have to lean in for.
JOIN = "j"

#: Which specialist's screen the code was on. Carried for the salon's own reading only — the line
#: is salon-wide, so nothing about placement reads it (§12). Never a Telegram id: that is the
#: credential (§3) and it does not belong in a URL a client's browser history keeps.
CLAIM_BY = "by"


#: Bytes of randomness per code. 16 is 22 url-safe characters, and the length is load-bearing in
#: both directions: it is what makes two codes minted in the same second different, and every
#: character of it is modules in the symbol a client has to scan.
NONCE_BYTES = 16


def new_nonce() -> str:
    """A fresh nonce for one mint. The one place this is generated, so the symbol size the tests
    bound is the symbol size the salon shows."""
    return secrets.token_urlsafe(NONCE_BYTES)


def link_for(specialist_id: int, *, now: float, nonce: str) -> str:
    """The URL to put in a QR, or "" when there is nothing deployed to open.

    Pure: `now` and `nonce` are the caller's, as `tokens.mint` requires. An empty secret or base
    URL yields "" rather than an unsigned link — the mini app then shows no code at all, which is
    the honest failure.
    """
    signing = config.join_secrets()
    if not signing or not config.PUBLIC_BASE_URL:
        return ""
    token = tokens.mint(
        signing[0],
        audience=JOIN,
        claims={CLAIM_BY: int(specialist_id)},
        ttl_s=config.JOIN_TOKEN_TTL_SECONDS,
        now=now,
        nonce=nonce,
    )
    return f"{config.PUBLIC_BASE_URL}/{JOIN}/{token}"


def opened(token: str, *, now: float) -> tokens.Verified | tokens.Rejected:
    """Whether this code still opens the join page, and its claims if it does.

    The leeway is what stops a scan that was in flight when the code rotated from failing on a
    stranger's screen: she raised her phone while the old one was still up, and by the time she
    taps the notification it has gone (§13).
    """
    return tokens.verify(
        token,
        secrets=config.join_secrets(),
        audience=JOIN,
        now=now,
        leeway_s=config.JOIN_TOKEN_LEEWAY_SECONDS,
    )
