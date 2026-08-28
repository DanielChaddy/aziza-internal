"""The deterministic layer: what the model is not allowed to be talked into.

Two callbacks, each with a precise ADK return contract:

  * `before_model_safety(callback_context, llm_request)` — the input screen, attached by
    `agent_adk.build_graph` to every agent that can own a turn. `None` lets the model run; an
    `LlmResponse` short-circuits the turn with a fixed reply.
  * `before_tool_guard(tool, args, tool_context)` — authorization. `None` runs the tool; a dict
    blocks it and gives the model something to say.

Where the security of this assistant lives. The prompts are advisory; this file is not.

**The confirm-first gate is NOT here.** A payment may only be taken against a ticket the
specialist has actually been shown, and which ticket that is comes from the database — so it is
enforced in `tools.record_payment`, where the open sale's reference is in hand. A copy here could
only ask the weaker question, and a weaker copy of a gate is what gets read as the gate.

The Spanish here reaches a specialist with no model in the path, so the register is fixed at the
literal — docs/BRAND_VOICE.md.
"""

from __future__ import annotations

import logging
from typing import Any

from agent_adk import latest_user_text, text_response
from conversation_core import fold

from aziza_adk import session, tools

logger = logging.getLogger("aziza_adk.guards")

INJECTION_MSG = (
    "Con eso no puedo ayudarte. ¿Abrimos una cuenta, le agregamos un servicio, o cobramos?"
)

#: Accent-folded, because a screen a specialist evades by typing without accents is not a screen.
#: Specific phrases rather than single words: "sistema" and "instrucciones" are ordinary Spanish
#: in a salon conversation, and a screen that fires on an ordinary turn gets switched off.
_INJECTION_PHRASES: tuple[str, ...] = (
    "ignora tus instrucciones",
    "ignora las instrucciones",
    "olvida tus instrucciones",
    "ignore your instructions",
    "ignore previous instructions",
    "system prompt",
    "prompt del sistema",
    "revela tus instrucciones",
    "muestra tus instrucciones",
    "cual es tu prompt",
    "developer mode",
    "modo desarrollador",
    "jailbreak",
    "actua como si no tuvieras",
    "sin restricciones",
)


def before_model_safety(callback_context: Any, llm_request: Any) -> Any:
    """Screen one turn before the model sees it.

    Runs on every agent, so the same message is screened more than once per turn — a tool round
    trip re-enters the model. Harmless by construction: this is pure and returns the same reply
    for the same text.
    """
    text = latest_user_text(llm_request)
    if not text:
        return None
    if any(phrase in fold(text) for phrase in _INJECTION_PHRASES):
        logger.info("input screen: injection attempt")
        return text_response(INJECTION_MSG)
    return None


def before_tool_guard(tool: Any, args: dict, tool_context: Any) -> dict | None:
    """Authorize a tool call. Identity only, and identity is the whole of it here.

    Every tool writes or reads against ONE specialist, and that specialist is what a commission
    is paid to — so the questions this layer answers are whether the session has one at all, and
    whether it may name a different one. Both are decidable from session state, which is why they
    are here rather than in a query.

    `on_behalf_of` is the one argument that can move money to a person the sender is not. It is
    refused here, off the row the edge resolved, so no wording in a turn can reach it — the prompt
    is advisory and this is not.
    """
    name = getattr(tool, "name", "") or getattr(tool, "__name__", "")
    if name not in tools.SPECIALIST_TOOL_NAMES:
        return None
    if not session.specialist_id(tool_context):
        return _blocked("not_registered", tools.NOT_REGISTERED_MSG, name)
    if str((args or {}).get("on_behalf_of") or "").strip() and not session.is_admin(tool_context):
        return _blocked("not_an_admin", tools.NOT_AN_ADMIN_MSG, name)
    return None


def log_before_agent(callback_context: Any) -> None:
    logger.info("agent %s took the turn", getattr(callback_context, "agent_name", "?"))
    return None


def log_after_tool(tool: Any, args: dict, tool_context: Any, tool_response: Any) -> None:
    """Record which tool ran and whether it answered — never what it answered.

    A response carries a client's name and what she paid, and a log line is the one place those
    would persist outside the turn.
    """
    name = getattr(tool, "name", "?")
    failed = isinstance(tool_response, dict) and "error" in tool_response
    logger.info("tool %s %s", name, "returned an error" if failed else "ok")
    return None


def _blocked(reason: str, message: str, tool_name: str) -> dict:
    logger.info("tool %s blocked: %s", tool_name, reason)
    # `blocked_by_guard` is the sentinel the eval reads to tell a refusal from a model that
    # simply chose not to call the tool.
    return {"blocked_by_guard": True, "error": reason, "message": message}
