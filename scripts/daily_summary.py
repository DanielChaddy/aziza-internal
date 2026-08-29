#!/usr/bin/env python3
"""Send each specialist what they made today. Run once a day, after the salon closes.

Idempotent by CONSTRUCTION rather than by care: `daily_summaries` carries a unique key on
(specialist, day), the row is claimed before the message goes out, and the claim is committed only
once the send has succeeded. A failed send rolls back and the next run retries it; a second run
after a good one claims nothing and sends nothing.

**A simulated run writes no claim.** The sibling assistant learned this the expensive way — a dry
run that marks the work as done permanently silences the people it was rehearsing for. Only
SUMMARY_SEND_MODE=live records anything.

    python scripts/daily_summary.py                 # today, in the salon's timezone
    python scripts/daily_summary.py --date 2026-08-26
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import logging
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from channel_telegram import bot_client  # noqa: E402

from aziza_adk import config, money, queries, receipts, tools  # noqa: E402

log = logging.getLogger("aziza_adk.daily_summary")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="business date as YYYY-MM-DD. Defaults to today.")
    return parser.parse_args(argv)


def _send(telegram_user_id: str, text: str) -> bool:
    """True when the specialist actually received it.

    In `simulate` this logs and returns True WITHOUT the caller committing a claim — the mode is
    checked again at the call site, so a future edit here cannot quietly make a dry run count.
    """
    if config.SUMMARY_SEND_MODE != "live":
        log.info("summary.send mode=simulate to=%s\n%s", telegram_user_id, text)
        return True
    result = asyncio.run(bot_client.send_text(telegram_user_id, text))
    if not result.ok:
        log.error("summary.send_failed to=%s code=%s", telegram_user_id, result.error_code)
    return result.ok


def run(day: dt.date) -> dict[str, int]:
    counts = {"sent": 0, "already_sent": 0, "send_failed": 0, "no_channel": 0, "asked": 0}
    live = config.SUMMARY_SEND_MODE == "live"

    with queries.connect() as conn:
        for person in queries.specialists_billed_on(conn, day):
            # Her work is recorded by an owner and she has no way to receive this. Skipped BEFORE
            # the claim, so the day stays unclaimed and reaches her the moment she has an id.
            if not person["telegram_user_id"]:
                counts["no_channel"] += 1
                continue
            totals = tools.day_figures(conn, person["id"], day)
            services_total = totals["services_total"]
            # On services alone. Products are reported to her and pay her nothing (§7).
            earned = money.commission(services_total, config.COMMISSION_PCT)

            claimed = queries.claim_summary(
                conn,
                person["id"],
                day,
                services_total=services_total,
                commission=earned,
                tips=totals["tips"],
                products_total=totals["products_total"],
                owed_products=totals["owed_products"],
                owed_loans=totals["owed_loans"],
                period_commission=totals["period_commission"],
            )
            if not claimed:
                conn.rollback()
                counts["already_sent"] += 1
                continue

            text = tools.summary_text(person["full_name"], day, totals)
            if not _send(person["telegram_user_id"], text):
                conn.rollback()  # the claim goes back; the next run retries this person
                counts["send_failed"] += 1
                continue

            # The one place the claim becomes permanent, and only on the live path.
            conn.commit() if live else conn.rollback()
            counts["sent"] += 1

        counts["asked"] = _ask_to_close_the_register(conn, day)

    return counts


def _ask_to_close_the_register(conn, day: dt.date) -> int:
    """Ask every owner to count the register, unless one of them already has.

    The already-closed check IS the idempotence here, and it is better than a claim would be: it
    is the real state rather than a record of having asked, so a retry after a failed send still
    asks, and nothing asks again once the count is in.
    """
    if queries.register_close_for(conn, day) is not None:
        return 0
    text = receipts.render_register_prompt(
        day,
        queries.expected_register(conn, day),
        [(t["full_name"], t["tips"]) for t in queries.tips_owed(conn, day)],
    )
    return sum(
        _send(owner["telegram_user_id"], text) for owner in queries.owners_with_a_channel(conn)
    )


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    day = (
        dt.date.fromisoformat(args.date)
        if args.date
        else dt.datetime.now(ZoneInfo(config.TIMEZONE)).date()
    )

    counts = run(day)
    log.info(
        "summary.done date=%s mode=%s sent=%s already_sent=%s send_failed=%s "
        "no_channel=%s asked=%s",
        day,
        config.SUMMARY_SEND_MODE,
        counts["sent"],
        counts["already_sent"],
        counts["send_failed"],
        counts["no_channel"],
        counts["asked"],
    )
    # A failed send is not a failed run: the claim went back and the next run retries it. The
    # exit code is for the scheduler, and a non-zero one here would retry the whole day.
    return 0


if __name__ == "__main__":
    sys.exit(main())
