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

# --- Serving limits ---------------------------------------------------------
# Hard cap on ONE turn. The Gemini SSE stream has no timeout of its own — google-genai sets
# timeout=None — so a server that stops emitting chunks parks the turn forever and the
# specialist waits with no reply and no error. ONE value, TWO layers: the whole-turn ceiling in
# seconds here, and the per-model-call idle timeout in prompts/common.py, which wants milliseconds.
MODEL_TURN_TIMEOUT_SECONDS: int = _int("MODEL_TURN_TIMEOUT_SECONDS", 60)

# --- Telegram ---------------------------------------------------------------
# Read by `channel_telegram.settings`, not here — one concept gets one variable name in every
# runtime. Declared in .env.example, which is where the whole list lives.

# --- End-of-day summary -----------------------------------------------------
# `simulate` logs what would be sent and WRITES NO CLAIM, so a dry run cannot mark a day as
# already reported. Only `live` sends and records. See scripts/daily_summary.py.
SUMMARY_SEND_MODE: str = os.getenv("SUMMARY_SEND_MODE", "simulate").strip().lower()

# --- Gates ------------------------------------------------------------------
# 1 turns an absent database from skips into failures. What CI sets.
REQUIRE_DB: bool = _flag("REQUIRE_DB", False)
