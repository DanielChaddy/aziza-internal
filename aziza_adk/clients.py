"""Which client a name and a number mean, decided without a database and without a model.

Stdlib plus `conversation_core`, and the list arrives as an argument — so "two people called
María" and "a number one digit short" are both assertable with no driver behind them, the way
`staff.py` makes naming a specialist assertable. docs/PROJECT_DEFINITION.md §3.

**The number is half of an identity, not a contact detail.** Nothing here dials it, and the only
place it is ever shown is a report an owner asked for.

The Dominican SHAPE lives here rather than on the platform because this repository is its only
consumer, and the tier rule is two consumers rather than one and an argument. The move, when a
second one wants it, is beside `conversation_core.identity` — whose docstring already argues that
a country's conventions belong down there. `normalize_phone` itself is NOT reimplemented.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from conversation_core import normalize_phone

from aziza_adk.catalog import Resolution

#: Ten, which is a Dominican telephone. `conversation_core.identity.DIGITS` is eleven and is a
#: cédula — a different eleven, deliberately not reused: a cédula typed here is not a long phone.
PHONE_DIGITS = 10
#: Stripped rather than stored. The same person written `1809…` and `809…` must not become two
#: rows, which is the split this whole module exists to prevent.
COUNTRY_CODE = "1"


@dataclass(frozen=True)
class Client:
    """One person the salon carries a balance for, and the number that says which one she is.

    No aliases, deliberately. Client names are matched exact-on-folded and never through
    `catalog.resolve`'s overlap pass, which reads "Ana" out of "Mariana" — a fuzzy hit here
    attaches a real balance to the wrong person.
    """

    client_id: int
    name: str
    phone: str


def roster(rows: Iterable[dict]) -> tuple[Client, ...]:
    """The clients one spoken name reaches, built from `queries.clients_named`."""
    return tuple(
        Client(client_id=row["id"], name=row["name"], phone=str(row["phone"] or "")) for row in rows
    )


def phone_key(raw: str) -> str | None:
    """The ten digits the salon stores, or None for anything that is not one of its numbers.

    None rather than a best effort, exactly as `conversation_core.identity.normalize` refuses: a
    digit missing is a typo, and a typo resolved to whoever it happens to match is a stranger's
    balance. The area code is NOT checked — a visitor's number would be refused by a rule the
    salon never asked for, and refusing a client outright is the worse mistake.
    """
    digits = normalize_phone(raw)
    if len(digits) == PHONE_DIGITS + 1 and digits.startswith(COUNTRY_CODE):
        digits = digits[1:]
    return digits if len(digits) == PHONE_DIGITS else None


def pick(roster: Sequence[Client], phone: str = "") -> Resolution[Client]:
    """Which of the clients sharing one name this is.

    With a number the pair is exact and at most one row can hold it — `UNIQUE (folded, phone)`
    says so. Without one, a single client IS the answer and several are a QUESTION rather than a
    pick: charging the first of two Marías is how one of them pays the other's balance.
    """
    if phone:
        held = [client for client in roster if client.phone == phone]
        return Resolution(match=held[0]) if held else Resolution()
    if len(roster) == 1:
        return Resolution(match=roster[0])
    return Resolution(candidates=tuple(roster)) if roster else Resolution()
