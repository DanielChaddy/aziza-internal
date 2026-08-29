"""What the session remembers: who is talking, and which ticket they have actually been shown.

Two facts and nothing else. `tools.py` writes them, `guards.py` enforces them, and neither reads
the other. Values are plain strings because the served session store persists this state as JSON.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from conversation_core import state

SPECIALIST_KEY = "specialist"

#: The one role that widens authorization (docs/PROJECT_DEFINITION.md §3).
OWNER = "owner"
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


def roles(context: Any) -> frozenset[str]:
    """What this sender may do beyond her own work. Empty is an ordinary specialist."""
    return frozenset(specialist(context).get("roles") or ())


def remember_specialist(
    context: Any,
    *,
    specialist_id: int,
    specialist_ref: str,
    full_name: str,
    disciplines: tuple[str, ...],
    roles: tuple[str, ...] = (),
) -> None:
    _write(
        context,
        SPECIALIST_KEY,
        {
            "id": specialist_id,
            "specialist_ref": specialist_ref,
            "full_name": full_name,
            "disciplines": list(disciplines),
            "roles": list(roles),
        },
    )


def is_owner(context: Any) -> bool:
    """May this sender record work against another specialist, and act outside opening hours?

    Read off the row the edge resolved, never off anything said during the turn. Fails closed on
    a session that cannot be read.
    """
    return OWNER in roles(context)


def was_quoted(context: Any, sale_ref: str, total: Decimal) -> bool:
    """Has THIS ticket, at THIS total, been shown to the specialist in full?

    Keyed on the ticket rather than a flag, and that is the whole point: a flag set while quoting
    one ticket would authorize charging the next one, which is a different client and a different
    amount.

    Keyed on the TOTAL as well, so the gate cannot be satisfied by a figure that has since
    changed. Re-pricing a ticket for a different client moves it by as much as RD$550, and a gate
    that only knew the ticket's identity would have gone on authorizing the amount she saw before
    the correction. Every path that changes a total re-shows it; this is what makes that a
    property rather than a habit.

    Fails closed on anything it cannot read.
    """
    if not sale_ref:
        return False
    seen = state.mapping(context, QUOTED_KEY)
    return seen.get("sale_ref") == sale_ref and seen.get("total") == str(total)


def remember_quote(context: Any, sale_ref: str, total: Decimal) -> None:
    _write(context, QUOTED_KEY, {"sale_ref": sale_ref, "total": str(total)})


def _write(context: Any, key: str, value: dict) -> None:
    container = state.container(context)
    if container is not None:
        container[key] = value
