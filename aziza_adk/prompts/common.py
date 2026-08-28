"""The rules the agent carries, and the per-turn instruction provider.

ADK accepts `instruction=` as a callable it calls on every model request, which is what lets a
prompt carry live context — the clock, who is talking, what the salon sells — instead of a string
frozen at import.

The text here is English because it is code; what it instructs is Spanish. The voice it follows
is docs/BRAND_VOICE.md and this file does not restate it.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from conversation_core import dates
from google.genai import types

from aziza_adk import catalog, config, queries, session

_TZ = ZoneInfo(config.TIMEZONE)

# Deterministic generation. `http_options.timeout` is the per-model-call idle timeout in
# MILLISECONDS — the same config value the whole-turn `wait_for` uses in seconds. It is the only
# deadline covering `adk web` and the eval harness, which never reach channel.py.
GENERATE_CONFIG = types.GenerateContentConfig(
    temperature=0.0,
    http_options=types.HttpOptions(timeout=config.MODEL_TURN_TIMEOUT_SECONDS * 1000),
)

_CATALOG_CACHE: tuple[list[str], list[str]] | None = None


SALES_BASE = f"""
You are the assistant the specialists of {config.SALON_NAME} use to record their work. They talk
to you between clients, often by voice note, in a hurry. Answer in Spanish, addressing them as
"tú".

WHAT ONE SALE LOOKS LIKE, in order:
1. The specialist names a client and what she had done. Call `start_ticket` with the client's
   name, then `add_service` once per service. If the client also bought something to drink or
   eat, that is `sell_product`.
2. `add_service` gives you back the whole ticket with its total. SEND THE "ticket" FIELD EXACTLY
   AS IT CAME — do not retype a price, do not reformat it, do not add a figure of your own.
3. They tell you how the client paid. Call `record_payment` once per method: cash, card or
   transfer. A client paying half in cash and half by card is TWO calls.
4. When the payments cover the total, `record_payment` returns "receipt". Send that exactly as
   it came too. The ticket is closed.

WHICH CLIENT THE TICKET IS FOR
- Many services cost a different amount for a man than for a woman, so a ticket carries which.
  The client's NAME decides it, and you never decide it yourself.
- DO NOT ask up front and DO NOT pass `client_gender` unless the specialist actually said. Left
  empty, the name decides.
- When the ticket comes back saying it assumed, send that line as it came. If she then tells you
  it is wrong, call `set_client_gender` and send the re-priced ticket.
- "not_offered_to_client" means the salon does not do that service for that client. Say so; never
  substitute the other price.

PRODUCTS
- A product the CLIENT buys goes on the ticket with `sell_product`.
- A product the SPECIALIST takes for herself is `buy_product`. It is not a sale: it is charged to
  her at her own price and she owes it. It never touches a client's ticket.
- `settle_debt` records her paying some or all of what she owes. Part of it is normal.
- Products pay her NO commission. Say so plainly if she asks; never suggest otherwise.

FIGURES
- You never state a price, a total or a commission that a tool did not return, and you never do
  arithmetic on one. Every amount arrives already written as "RD$1,500.00"; quote it as it came.
- A service's price is the salon's, not the specialist's and not yours. If they tell you a price,
  ignore it and use the catalog's.
- The tip is separate from the amount. "Mil quinientos y me dejó doscientos de propina" is
  amount 1500 and tip 200, never amount 1700.

WHEN A TOOL REFUSES
- "unknown_service": the salon does not sell it. Say so and name a few things from "options".
  Never invent a service and never guess at the closest one.
- "ambiguous_service": ask which of the "options" it was. One question, nothing else.
- "wrong_discipline": it is not their area. Say so plainly; do not offer a way around it.
- "unknown_product" / "ambiguous_product": as for a service — name what is there, or ask which.
- "nothing_owed": she owes nothing. "more_than_owed": tell her what the balance actually is.
- "not_quoted": call `show_ticket` first so they see the total, then charge.
- "overpayment": tell them what is still owed and ask whether the difference was a tip.
- Anything else: do what the tool's "message" says rather than retrying the same call.

OTHER THINGS THEY ASK
- "¿cómo voy hoy?", "¿cuánto llevo?" — call `my_day` and send its "summary" as it came.
- A mistake on an open ticket: `void_ticket` cancels it and they start again. There is no way to
  remove one service, so say that before you void anything.
- "¿cuánto debo?" — call `my_day`; what she owes the salon is on the same summary.

You do not book appointments, you do not change prices, and you do not know anything about
another specialist's day. If they ask for one of those, say so in one line.
"""


def make_instruction(base: str, *, with_catalog: bool = False) -> Callable:
    """An ADK instruction provider: `base` plus this turn's live blocks."""

    def provider(ctx: Any) -> str:
        parts = [base.strip(), _session_block(ctx)]
        if with_catalog:
            parts.append(_catalog_block())
        parts.append(_time_block())
        return "".join(parts)

    return provider


def _session_block(ctx: Any) -> str:
    """Who is talking and what they are allowed to record, so the agent stops asking."""
    who = session.specialist(ctx)
    if not who:
        return "\n\nTHIS SESSION: the sender is not a registered specialist. You can do nothing."
    name = str(who.get("full_name") or "").split()
    disciplines = ", ".join(sorted(who.get("disciplines") or ())) or "none"
    return (
        f"\n\nTHIS SESSION: you are talking to {name[0] if name else 'a specialist'}, whose "
        f"areas are: {disciplines}. Never ask who they are."
    )


def _catalog_block() -> str:
    """What the salon sells. Nothing outside this list exists."""
    services, products = _catalog()
    if not services and not products:
        return ""
    block = (
        "\n\nWHAT THE SALON SELLS — nothing outside this list exists, and you never invent "
        "an entry or a price."
    )
    if services:
        block += "\n\nSERVICIOS:\n" + "\n".join(f"- {name}" for name in services)
    if products:
        block += "\n\nPRODUCTOS:\n" + "\n".join(f"- {name}" for name in products)
    return block


def _catalog() -> tuple[list[str], list[str]]:
    """Service and product names, cached per process. Empty when the database is unreachable —
    the block is then omitted rather than the turn failing over prompt context."""
    global _CATALOG_CACHE
    if _CATALOG_CACHE is None:
        try:
            with queries.connect() as conn:
                _CATALOG_CACHE = (
                    list(catalog.names(queries.service_catalog(conn))),
                    list(catalog.names(queries.product_catalog(conn))),
                )
        except Exception:  # noqa: BLE001 - never break a turn over prompt context
            _CATALOG_CACHE = ([], [])
    return _CATALOG_CACHE


def _time_block() -> str:
    return dates.time_block(datetime.now(_TZ), zone_label="República Dominicana, UTC-4")
