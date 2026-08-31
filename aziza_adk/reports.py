"""The link an owner taps to download a month's 606: what authorizes it, and for how long.

The signing is `agent_webview.tokens`, as `join.py`'s is. docs/PROJECT_DEFINITION.md §15.

ITS OWN SECRET, never the join page's. Sharing one would mean rotating the code a client scans in
order to rotate the link an owner holds, which is the argument `config.py` already makes about not
sharing with the webhook.
"""

from __future__ import annotations

import datetime as dt
import secrets

from agent_webview import tokens

from aziza_adk import config

#: The view the token opens, and a URL segment.
REPORT = "r"

#: Which month the link is for, as AAAA-MM. Carried in the token rather than in the path so the
#: month cannot be changed by editing the URL.
CLAIM_MONTH = "m"

NONCE_BYTES = 16


def new_nonce() -> str:
    return secrets.token_urlsafe(NONCE_BYTES)


def link_for(month: dt.date, *, now: float, nonce: str) -> str:
    """The URL to send her, or "" when there is nothing deployed to open.

    Pure: `now` and `nonce` are the caller's, as `tokens.mint` requires.
    """
    signing = config.report_secrets()
    if not signing or not config.PUBLIC_BASE_URL:
        return ""
    token = tokens.mint(
        signing[0],
        audience=REPORT,
        claims={CLAIM_MONTH: month.strftime("%Y-%m")},
        ttl_s=config.REPORT_TOKEN_TTL_SECONDS,
        now=now,
        nonce=nonce,
    )
    return f"{config.PUBLIC_BASE_URL}/{REPORT}/{token}"


def opened(token: str, *, now: float) -> tokens.Verified | tokens.Rejected:
    """Whether this link still downloads, and which month it is for if it does."""
    return tokens.verify(
        token,
        secrets=config.report_secrets(),
        audience=REPORT,
        now=now,
    )


def month_of(claims: dict) -> dt.date | None:
    """The first of the month the token names, or None when it names nothing readable."""
    said = str(claims.get(CLAIM_MONTH) or "")
    try:
        return dt.date.fromisoformat(f"{said}-01")
    except ValueError:
        return None
