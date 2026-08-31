"""What a client actually submitted, read out of a urlencoded body without a framework.

Stdlib only and pure, so "a number one digit short", "no area ticked" and "an area the salon does
not have" are all assertable with no HTTP behind them.
docs/PROJECT_DEFINITION.md §13.

**Nothing here trusts a field.** Every value arrives from a form anybody with a live code can post,
so an unknown area is dropped rather than passed on, and `client_id` is carried as a number for the
caller to check against the candidates that number actually reaches — never as an authorization.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qsl

from aziza_adk import catalog_data, clients

#: The area codes the salon has. A code outside this is dropped on the way in rather than reaching
#: a query, which is what keeps the codes a page offers and the codes it accepts one list.
CODES = frozenset(row["code"] for row in catalog_data.DISCIPLINES)


@dataclass(frozen=True)
class Submitted:
    """One submission, already keyed and filtered.

    `phone` is None for something that was meant to be a number and is not one — the same refusal
    `clients.phone_key` makes, carried through rather than repaired (§3). `client_id` is 0 when she
    was not choosing between candidates.
    """

    phone: str | None
    name: str
    areas: tuple[str, ...]
    client_id: int


def read(body: bytes) -> Submitted:
    """Parse a urlencoded body. Never raises: every malformed field becomes an absent one."""
    fields: dict[str, list[str]] = {}
    for key, value in parse_qsl(body.decode("utf-8", "replace"), keep_blank_values=True):
        fields.setdefault(key, []).append(value)

    said = (fields.get("phone") or [""])[0].strip()
    picked = (fields.get("client_id") or [""])[0].strip()
    areas: list[str] = []
    for code in fields.get("areas") or ():
        if code in CODES and code not in areas:
            areas.append(code)

    return Submitted(
        # An empty box and a typo are different: nothing typed is None here too, because the page
        # marks the field required and a blank one is not a number either.
        phone=clients.phone_key(said) if said else None,
        name=(fields.get("name") or [""])[0].strip(),
        areas=tuple(areas),
        client_id=int(picked) if picked.isdigit() else 0,
    )
