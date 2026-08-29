"""The salon's real people, as against the invented ones in `demo_data.py`.

Stdlib only, and read by BOTH the seeder and the tests — so a change here cannot leave the tests
asserting against someone who does not work here.

**A Telegram id is the credential**, not a label: `channel.py` matches it before the Runner runs
and an id that is not here reaches nothing (docs/PROJECT_DEFINITION.md §3). Adding a row with one
is therefore granting access. `None` is the other case — someone whose work the salon records and
who cannot yet talk to the assistant, so an owner enters it on her behalf.

**Roles and disciplines are independent, and both are additive.** A discipline is what she may
record; a role is what she may do beyond her own work. Someone can hold either, both or neither:
an owner with no disciplines does no salon work, and a specialist with no roles records only her
own.

Real rows live here rather than beside the invented specialists for the reason the catalog moved
out of that file: a dataset that is half true is one a reader has to check line by line. What is
in `demo_data.py` is invented, all of it, and a database seeded without it can still be used.
"""

from __future__ import annotations

#: A role exists when it grants something a discipline does not. Being a specialist is not one of
#: them — that is holding a discipline, and a second spelling of it could only ever disagree.
ROLES: tuple[dict, ...] = ({"code": "owner", "name": "Dueña"},)

STAFF: tuple[dict, ...] = (
    {
        "specialist_ref": "stf-001",
        "telegram_user_id": "1984550684",
        "full_name": "Daniel Chaddy",
        "disciplines": (),
        "roles": ("owner",),
    },
    {
        "specialist_ref": "stf-002",
        "telegram_user_id": "7676141148",
        "full_name": "Mariana Pernía",
        "disciplines": ("wax",),
        "roles": ("owner",),
    },
    {
        "specialist_ref": "stf-003",
        "telegram_user_id": None,
        "full_name": "Johanna",
        "disciplines": ("nails",),
        "roles": (),
    },
    {
        "specialist_ref": "stf-004",
        "telegram_user_id": None,
        "full_name": "Kathy",
        "disciplines": ("nails",),
        "roles": (),
    },
)
