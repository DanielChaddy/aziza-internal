"""Environment-driven configuration.

Every model, URL and feature flag is an env var with a safe code default: a missing env var
degrades to *safe/local*, never crashes boot. Servers override only what differs.
"""

from __future__ import annotations

import os
from pathlib import Path

# Scripts, pytest and uvicorn invoke this module directly, unlike `adk web`, which loads .env
# itself. Load it here so every consumer sees the values `adk web` would. If python-dotenv is
# absent, or there is no .env, the os.getenv defaults below stand unchanged.
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:
    pass


from conversation_core import flag as _flag  # noqa: E402
from conversation_core import int_ as _int  # noqa: E402

# --- Models -----------------------------------------------------------------
AGENT_MODEL: str = os.getenv("AGENT_MODEL", "gemini-3.5-flash-lite")
# What reads a voice note. Its own variable rather than the agent's: reading audio is not
# reasoning, so downgrading one must never silently change what hears a specialist.
TRANSCRIBE_MODEL: str = os.getenv("TRANSCRIBE_MODEL", "gemini-3.5-flash-lite")

# --- Databases --------------------------------------------------------------
# Business DB uses a SYNC driver (psycopg 3); ADK's session DB uses an ASYNC one and lives in
# its own database (agent-platform docs/ADK_LESSONS_LEARNED.md §6a-6b). Never the same database.
DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://aziza:aziza@localhost:5434/aziza")
ADK_SESSION_DB_URL: str = os.getenv(
    "ADK_SESSION_DB_URL",
    "postgresql+psycopg://aziza:aziza@localhost:5434/aziza_sessions",
)

# --- App --------------------------------------------------------------------
# APP_NAME MUST equal the package directory name so `adk web` lists persisted sessions.
APP_NAME: str = os.getenv("APP_NAME", "aziza_adk")
SALON_NAME: str = os.getenv("SALON_NAME", "Salón Aziza")

# Dominican Republic (AST, UTC-4, no DST). What "today" means for a business date.
TIMEZONE: str = os.getenv("TIMEZONE", "America/Santo_Domingo")

# --- Money ------------------------------------------------------------------
# The specialist's share of a services subtotal, before tip. One value rather than a column: a
# per-person split is a schema change when a real one appears, not a guess made today.
COMMISSION_PCT: int = _int("COMMISSION_PCT", 40)

# --- What the salon buys ----------------------------------------------------
# How long a photographed invoice stays answerable. A photo taken and confirmed is one turn; a
# "sí" an hour later answers a question whose figures she has stopped looking at, so the draft is
# simply not found and she sends the photo again. See docs/PROJECT_DEFINITION.md §15.
EXPENSE_DRAFT_TTL_MINUTES: int = _int("EXPENSE_DRAFT_TTL_MINUTES", 15)

# --- Serving limits ---------------------------------------------------------
# Hard cap on ONE turn. The Gemini SSE stream has no timeout of its own — google-genai sets
# timeout=None — so a server that stops emitting chunks parks the turn forever and the
# specialist waits with no reply and no error. ONE value, TWO layers: the whole-turn ceiling in
# seconds here, and the per-model-call idle timeout in prompts/common.py, which wants milliseconds.
MODEL_TURN_TIMEOUT_SECONDS: int = _int("MODEL_TURN_TIMEOUT_SECONDS", 60)

# --- Telegram ---------------------------------------------------------------
# Read by `channel_telegram.settings`, not here — one concept gets one variable name in every
# runtime. Declared in .env.example, which is where the whole list lives.

# --- The code she scans -----------------------------------------------------
# Signs the join link the QR encodes. ITS OWN secret, never the webhook's and never the bot
# token: sharing one would mean rotating the webhook to rotate the links. Empty REFUSES every
# join, which is the safe direction for a service nobody has configured yet.
JOIN_LINK_SECRET: str = os.getenv("JOIN_LINK_SECRET", "")
JOIN_LINK_SECRET_PREVIOUS: str = os.getenv("JOIN_LINK_SECRET_PREVIOUS", "")

# Where the code points. Empty means the mini app mints nothing rather than minting a link to
# nowhere. Derived from the Ingress host on the cluster — deploy/helm/aziza/templates/_helpers.tpl.
JOIN_BASE_URL: str = os.getenv("JOIN_BASE_URL", "").rstrip("/")

# THREE numbers that are ONE design: rotate < ttl, and (ttl - rotate) + leeway is the grace a
# client still has after the code she photographed has left the screen. tests/test_join.py holds
# the relation, because two numbers that must agree are two numbers that drift.
#
# The ceiling is what a code is worth to somebody who photographs it, and the floor is a client
# typing her name: the join form is one POST for a client the salon knows and two for one it does
# not, and a token that dies mid-form sends her back to a code that has already rotated.
JOIN_TOKEN_TTL_SECONDS: int = _int("JOIN_TOKEN_TTL_SECONDS", 300)
JOIN_QR_ROTATE_SECONDS: int = _int("JOIN_QR_ROTATE_SECONDS", 120)
JOIN_TOKEN_LEEWAY_SECONDS: int = _int("JOIN_TOKEN_LEEWAY_SECONDS", 60)

# A DAY, not minutes. Telegram stamps `auth_date` when the mini app is LAUNCHED and never
# refreshes it while it stays open, so a short window signs a specialist out mid-shift with no
# signal but a stale code. To steal one an attacker is already inside her Telegram.
MINI_APP_INIT_DATA_MAX_AGE_SECONDS: int = _int("MINI_APP_INIT_DATA_MAX_AGE_SECONDS", 86400)


def join_secrets() -> list[str]:
    """The signing secrets, the live one first.

    `agent_webview.tokens.verify` accepts any of them and `mint` uses the first, which is what
    makes a rotation a rolling restart rather than an outage. Read through this function rather
    than the constants so a caller cannot pick up only one of the two.
    """
    return [s for s in (JOIN_LINK_SECRET, JOIN_LINK_SECRET_PREVIOUS) if s]


# --- End-of-day summary -----------------------------------------------------
# `simulate` logs what would be sent and WRITES NO CLAIM, so a dry run cannot mark a day as
# already reported. Only `live` sends and records. See scripts/daily_summary.py.
SUMMARY_SEND_MODE: str = os.getenv("SUMMARY_SEND_MODE", "simulate").strip().lower()

# --- Gates ------------------------------------------------------------------
# 1 turns an absent database from skips into failures. What CI sets.
REQUIRE_DB: bool = _flag("REQUIRE_DB", False)

# --- One turn without Telegram ----------------------------------------------
# `/simulate` runs a turn and returns the reply, and it AUTHENTICATES NOBODY: `sender` is a field
# the caller types, so anybody who reaches it is any specialist whose Telegram id they know.
# Off unless switched on, so reaching the pod is not enough — the Ingress not routing it is the
# other layer, and a port-forward goes straight past that one.
ENABLE_SIMULATE: bool = _flag("ENABLE_SIMULATE", False)
