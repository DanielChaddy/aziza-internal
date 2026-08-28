"""The invented people the demo runs on: who works here and what each of them may record.

Stdlib only, and read by BOTH the seeder and the tests — so a change to the dataset cannot leave
the tests asserting against people who no longer work here.

The people and the Telegram ids are invented, all of them. What the salon sells and charges is
real and lives in `catalog_data.py`; the salon's real people live in `staff_data.py`. Nothing
here can drive the assistant, because no Telegram account holds any of these ids.

Seeded only when `scripts/seed_catalog.py --with-demo-specialists` asks for it, so a real
database does not carry four people who do not exist.
"""

from __future__ import annotations

SPECIALISTS: tuple[dict, ...] = (
    {
        "specialist_ref": "esp-001",
        "telegram_user_id": "700000001",
        "full_name": "Yamilé Reyes",
        "disciplines": ("nails",),
    },
    {
        "specialist_ref": "esp-002",
        "telegram_user_id": "700000002",
        "full_name": "Carla Peña",
        "disciplines": ("wax",),
    },
    # Holds both, which is why a specialist's disciplines are a set rather than a column.
    {
        "specialist_ref": "esp-003",
        "telegram_user_id": "700000003",
        "full_name": "Rosa Almánzar",
        "disciplines": ("nails", "wax"),
    },
)
