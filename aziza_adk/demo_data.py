"""The fictitious salon the demo runs on: who works here, what they do, and what it costs.

Stdlib only, and read by BOTH the seeder and the tests — so a change to the dataset cannot leave
the tests asserting against people who no longer work here.

The people and the Telegram ids are invented. The service names and the prices are placeholders
until the salon gives us its own; that is an Impediment on the board, not a decision taken here.
"""

from __future__ import annotations

DISCIPLINES: tuple[dict, ...] = (
    {"code": "nails", "name": "Uñas"},
    {"code": "wax", "name": "Depilación"},
)

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

SERVICES: tuple[dict, ...] = (
    {
        "service_ref": "svc-001",
        "name": "Manicure clásico",
        "discipline": "nails",
        "price": "800.00",
        "aliases": "manicure|manicura|mani",
    },
    {
        "service_ref": "svc-002",
        "name": "Manicure en gel",
        "discipline": "nails",
        "price": "1400.00",
        "aliases": "gel|manicure gel|unas en gel",
    },
    {
        "service_ref": "svc-003",
        "name": "Pedicure spa",
        "discipline": "nails",
        "price": "1200.00",
        "aliases": "pedicure|pedicura|pedi",
    },
    {
        "service_ref": "svc-004",
        "name": "Uñas acrílicas",
        "discipline": "nails",
        "price": "2500.00",
        "aliases": "acrilicas|acrilico",
    },
    {
        "service_ref": "svc-005",
        "name": "Depilación de piernas",
        "discipline": "wax",
        "price": "1500.00",
        "aliases": "piernas|cera piernas",
    },
    {
        "service_ref": "svc-006",
        "name": "Depilación de axilas",
        "discipline": "wax",
        "price": "600.00",
        "aliases": "axilas",
    },
    {
        "service_ref": "svc-007",
        "name": "Depilación de cejas",
        "discipline": "wax",
        "price": "500.00",
        "aliases": "cejas",
    },
    {
        "service_ref": "svc-008",
        "name": "Depilación bikini",
        "discipline": "wax",
        "price": "1800.00",
        "aliases": "bikini",
    },
)
