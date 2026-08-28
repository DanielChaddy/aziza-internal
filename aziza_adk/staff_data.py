"""The salon's real people, as against the invented ones in `demo_data.py`.

Stdlib only, and read by BOTH the seeder and the tests — so a change here cannot leave the tests
asserting against someone who does not work here.

**A Telegram id is the credential**, not a label: `channel.py` matches it before the Runner runs
and an id that is not here reaches nothing (docs/PROJECT_DEFINITION.md §3). Adding a row is
therefore granting access, and `is_admin` on one is granting the right to record work against
somebody else.

Real rows live here rather than beside the invented specialists for the reason the catalog moved
out of that file: a dataset that is half true is one a reader has to check line by line. What is
in `demo_data.py` is invented, all of it, and a database seeded without it can still be used.

An administrator holds NO disciplines. She records other people's work and does none herself, so
there is nothing for her to be authorized to do — and every entry she makes names whose it is.
"""

from __future__ import annotations

STAFF: tuple[dict, ...] = (
    {
        "specialist_ref": "stf-001",
        "telegram_user_id": "1984550684",
        "full_name": "Daniel Chaddy",
        "disciplines": (),
        "is_admin": True,
    },
)
