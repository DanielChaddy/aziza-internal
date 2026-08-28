#!/usr/bin/env python3
"""Apply the schema, load the salon's catalog, and register its people. Idempotent.

Three datasets, and the split is the point. `aziza_adk/catalog_data.py` is what the salon really
sells and charges. `aziza_adk/staff_data.py` is the people who really work here — and a Telegram
id there is a credential, since an id the database does not hold reaches nothing. Only
`aziza_adk/demo_data.py` is invented, and it is seeded ONLY when asked for: a real database has no
business carrying three people who do not exist.

All three are read by the tests too, so seeding and asserting cannot disagree.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aziza_adk import catalog_data, demo_data, queries, staff_data  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--with-demo-specialists",
        action="store_true",
        help="also register the three invented specialists, for driving a demo locally",
    )
    args = parser.parse_args(argv)
    people = staff_data.STAFF + (demo_data.SPECIALISTS if args.with_demo_specialists else ())
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
            for person in people:
                cur.execute(
                    "INSERT INTO specialists "
                    "  (specialist_ref, telegram_user_id, full_name, is_admin) "
                    "VALUES (%(specialist_ref)s, %(telegram_user_id)s, %(full_name)s, "
                    "        %(is_admin)s) "
                    "ON CONFLICT (specialist_ref) DO UPDATE SET "
                    "  telegram_user_id = EXCLUDED.telegram_user_id, "
                    "  full_name = EXCLUDED.full_name, is_admin = EXCLUDED.is_admin, "
                    "  active = TRUE "
                    "RETURNING id",
                    {**person, "is_admin": person.get("is_admin", False)},
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
        # The dataset is the source of truth for who may talk to this assistant, and for what the
        # salon sells — queries.py holds why.
        stood_down = queries.stand_down_absent(
            conn, [person["specialist_ref"] for person in people]
        )
        retired = queries.retire_absent(
            conn,
            [row["product_ref"] for row in catalog_data.PRODUCTS],
            [row["service_ref"] for row in catalog_data.SERVICES],
        )
        conn.commit()

    demo = len(people) - len(staff_data.STAFF)
    print(
        f"seeded {len(catalog_data.SERVICES)} services, {len(catalog_data.PRODUCTS)} products, "
        f"{len(catalog_data.DISCIPLINES)} disciplines, {len(staff_data.STAFF)} staff"
        + (f", {demo} demo specialists" if demo else "")
        + (f"; stood down {stood_down} no longer in the dataset" if stood_down else "")
        + (f"; retired {retired} no longer sold" if retired else "")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
