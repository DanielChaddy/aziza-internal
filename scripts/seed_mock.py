#!/usr/bin/env python3
"""Apply the schema and load the fictitious salon. Idempotent and re-runnable.

The dataset is `aziza_adk/demo_data.py`, which the tests read too — so seeding and asserting
cannot disagree about who works here.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aziza_adk import demo_data, queries  # noqa: E402


def main() -> int:
    with queries.connect() as conn:
        queries.apply_schema(conn)
        with conn.cursor() as cur:
            for row in demo_data.DISCIPLINES:
                cur.execute(
                    "INSERT INTO disciplines (code, name) VALUES (%(code)s, %(name)s) "
                    "ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name",
                    row,
                )
            for row in demo_data.SERVICES:
                cur.execute(
                    "INSERT INTO services "
                    "  (service_ref, name, discipline_id, price, aliases) "
                    "SELECT %(service_ref)s, %(name)s, d.id, %(price)s, %(aliases)s "
                    "FROM disciplines d WHERE d.code = %(discipline)s "
                    "ON CONFLICT (service_ref) DO UPDATE SET "
                    "  name = EXCLUDED.name, discipline_id = EXCLUDED.discipline_id, "
                    "  price = EXCLUDED.price, aliases = EXCLUDED.aliases, active = TRUE",
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
        f"seeded {len(demo_data.SPECIALISTS)} specialists, "
        f"{len(demo_data.SERVICES)} services, {len(demo_data.DISCIPLINES)} disciplines"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
