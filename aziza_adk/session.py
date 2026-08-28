"""What the session remembers: who is talking, and which ticket they have actually been shown.

Two facts and nothing else. `tools.py` writes them, `guards.py` enforces them, and neither reads
the other. Values are plain strings because the served session store persists this state as JSON.
"""

from __future__ import annotations

from typing import Any

from conversation_core import state

SPECIALIST_KEY = "specialist"
QUOTED_KEY = "quoted"


def specialist(context: Any) -> dict:
    """Who this session is, as the channel resolved them — never an argument the model supplied.

    Empty when the sender is not a registered specialist, which the channel refuses before the
    model runs. The tools re-check it anyway: a tool reached some other way must not answer.
    """
    return dict(state.mapping(context, SPECIALIST_KEY))


def specialist_id(context: Any) -> int:
    raw = specialist(context).get("id")
    return int(raw) if raw is not None else 0


def disciplines(context: Any) -> frozenset[str]:
    """What this specialist is allowed to record. Empty is allowed to do nothing."""
    return frozenset(specialist(context).get("disciplines") or ())


def remember_specialist(
    context: Any,
    *,
    specialist_id: int,
    specialist_ref: str,
    full_name: str,
    disciplines: tuple[str, ...],
) -> None:
    _write(
        context,
        SPECIALIST_KEY,
        {
            "id": specialist_id,
            "specialist_ref": specialist_ref,
            "full_name": full_name,
            "disciplines": list(disciplines),
        },
    )


def was_quoted(context: Any, sale_ref: str) -> bool:
    """Has THIS ticket been shown to the specialist, in full, with its total?

    Keyed on the ticket rather than a flag, and that is the whole point: a flag set while quoting
    one ticket would authorize charging the next one, which is a different client and a different
    amount. Fails closed on anything it cannot read.
    """
    return bool(sale_ref) and state.mapping(context, QUOTED_KEY).get("sale_ref") == sale_ref


def remember_quote(context: Any, sale_ref: str) -> None:
    _write(context, QUOTED_KEY, {"sale_ref": sale_ref})


def _write(context: Any, key: str, value: dict) -> None:
    container = state.container(context)
    if container is not None:
        container[key] = value
