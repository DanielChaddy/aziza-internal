#!/usr/bin/env python3
"""Apply the schema, load the salon's catalog, and register the demo specialists. Idempotent.

Two datasets, and the split is the point: `aziza_adk/catalog_data.py` is what the salon really
sells and charges, while `aziza_adk/demo_data.py` is three invented people with invented Telegram
ids. Both are read by the tests too, so seeding and asserting cannot disagree.

Until the salon's own specialists are registered, this leaves a database nobody can drive: an
unregistered sender is refused at the edge before the model runs.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aziza_adk import catalog_data, demo_data, queries  # noqa: E402


def main() -> int:
    with queries.connect() as conn:
        queries.apply_schema(conn)
        with conn.cursor() as cur:
            for row in catalog_data.DISCIPLINES:
                cur.execute(
                    "INSERT INTO disciplines (code, name) VALUES (%(code)s, %(name)s) "
                    "ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name",
                    row,
                )
            for row in catalog_data.SERVICES:
                cur.execute(
                    "INSERT INTO services "
                    "  (service_ref, name, discipline_id, price_female, price_male, aliases) "
                    "SELECT %(service_ref)s, %(name)s, d.id, %(price_female)s, %(price_male)s, "
                    "       %(aliases)s "
                    "FROM disciplines d WHERE d.code = %(discipline)s "
                    "ON CONFLICT (service_ref) DO UPDATE SET "
                    "  name = EXCLUDED.name, discipline_id = EXCLUDED.discipline_id, "
                    "  price_female = EXCLUDED.price_female, price_male = EXCLUDED.price_male, "
                    "  aliases = EXCLUDED.aliases, active = TRUE",
                    row,
                )
            for row in catalog_data.PRODUCTS:
                cur.execute(
                    "INSERT INTO products "
                    "  (product_ref, name, price_client, price_specialist, aliases) "
                    "VALUES (%(product_ref)s, %(name)s, %(price_client)s, "
                    "        %(price_specialist)s, %(aliases)s) "
                    "ON CONFLICT (product_ref) DO UPDATE SET "
                    "  name = EXCLUDED.name, price_client = EXCLUDED.price_client, "
                    "  price_specialist = EXCLUDED.price_specialist, "
                    "  aliases = EXCLUDED.aliases, active = TRUE",
                    row,
                )
            for person in demo_data.SPECIALISTS:
                cur.execute(
                    "INSERT INTO specialists (specialist_ref, telegram_user_id, full_name) "
                    "VALUES (%(specialist_ref)s, %(telegram_user_id)s, %(full_name)s) "
                    "ON CONFLICT (specialist_ref) DO UPDATE SET "
                    "  telegram_user_id = EXCLUDED.telegram_user_id, "
                    "  full_name = EXCLUDED.full_name, active = TRUE "
                    "RETURNING id",
                    person,
                )
                specialist_id = cur.fetchone()["id"]
                # Replaced wholesale rather than added to: a discipline removed from the dataset
                # has to be removed from the person, or a re-seed can only ever widen what they
                # are allowed to record.
                cur.execute(
                    "DELETE FROM specialist_disciplines WHERE specialist_id = %(sid)s",
                    {"sid": specialist_id},
                )
                for code in person["disciplines"]:
                    cur.execute(
                        "INSERT INTO specialist_disciplines (specialist_id, discipline_id) "
                        "SELECT %(sid)s, d.id FROM disciplines d WHERE d.code = %(code)s",
                        {"sid": specialist_id, "code": code},
                    )
        conn.commit()

    print(
        f"seeded {len(catalog_data.SERVICES)} services, {len(catalog_data.PRODUCTS)} products, "
        f"{len(catalog_data.DISCIPLINES)} disciplines, "
        f"{len(demo_data.SPECIALISTS)} demo specialists"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
