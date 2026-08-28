#!/usr/bin/env python
"""Drive the real agent graph over the cases, N times, and report both bands.

A SIGNAL, not a gate. An individual case flips run-to-run even at temperature 0, which is why
this is never wired into `pytest` and why the reduction has no printable scalar — the aggregate
lives in `agent_evalkit` and prints two bands or nothing.

Needs a model key AND the seeded database: the tools query the catalog, so an eval with no
database behind it would measure nothing. Each case runs as its own throwaway specialist, created
and deleted around it, so one conversation's ticket cannot reach the next.

    python eval/eval_runner.py --runs 5
    python eval/eval_runner.py --list
    python eval/eval_runner.py --cases a_sale_is_priced_from_the_catalog
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from agent_adk import build_graph
from agent_evalkit import aggregate
from cases import Case, by_name
from google.adk.runners import InMemoryRunner
from google.genai import types

import voice_checks
from aziza_adk import channel, config, guards, queries, session
from aziza_adk.agents.sales import SALES_SPEC
from aziza_adk.prompts.common import GENERATE_CONFIG

HISTORY = pathlib.Path(__file__).resolve().parent / "history"

#: Eval specialists live under this Telegram id prefix, so cleanup can find them. Well outside
#: both the demo dataset's range and the test suite's.
EVAL_PREFIX = "8888"


def _make_specialist(name: str) -> dict:
    """A throwaway specialist for one case, holding nails only — which is what makes the
    wrong-discipline case a real refusal rather than an accident."""
    telegram_user_id = f"{EVAL_PREFIX}{abs(hash(name)) % 10_000:04d}"
    with queries.connect() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM sales WHERE specialist_id IN "
            "  (SELECT id FROM specialists WHERE telegram_user_id = %s)",
            (telegram_user_id,),
        )
        cur.execute("DELETE FROM specialists WHERE telegram_user_id = %s", (telegram_user_id,))
        cur.execute(
            "INSERT INTO specialists (specialist_ref, telegram_user_id, full_name) "
            "VALUES (%s, %s, %s) RETURNING id",
            (f"eval-{telegram_user_id}", telegram_user_id, "Eval Sentinel"),
        )
        specialist_id = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO specialist_disciplines (specialist_id, discipline_id) "
            "SELECT %s, id FROM disciplines WHERE code = 'nails'",
            (specialist_id,),
        )
        conn.commit()
        return queries.specialist_by_telegram_id(conn, telegram_user_id)


def _drop(conn, pattern: str) -> None:
    """Remove eval specialists and everything they billed.

    The sales go first, and that ORDER is the schema talking: `sales.specialist_id` has no ON
    DELETE action, so a specialist who has billed cannot be deleted. That is the production rule
    — someone who leaves the salon is deactivated, not erased.
    """
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM sales WHERE specialist_id IN "
            "  (SELECT id FROM specialists WHERE telegram_user_id LIKE %s)",
            (pattern,),
        )
        cur.execute("DELETE FROM specialists WHERE telegram_user_id LIKE %s", (pattern,))
    conn.commit()


def _drop_specialist(telegram_user_id: str) -> None:
    with queries.connect() as conn:
        _drop(conn, telegram_user_id)


def _clean_all() -> None:
    with queries.connect() as conn:
        _drop(conn, EVAL_PREFIX + "%")


async def _run_case(case: Case) -> tuple[bool, list[str], list[str]]:
    """One conversation. Returns whether it passed, every reply, and every voice complaint."""
    # A fresh graph per case: an agent may have one parent, so the tree is rebuilt from the spec.
    root = build_graph(
        SALES_SPEC,
        input_screen=guards.before_model_safety,
        generate_content_config=GENERATE_CONFIG,
    )
    runner = InMemoryRunner(agent=root, app_name=config.APP_NAME)

    who = _make_specialist(case.name) if case.registered else None
    # THE SAME SHAPING FUNCTION the channel uses. State injected here and state seeded live have
    # to be identical, or the eval measures a session production never produces
    # (agent-platform docs/ADK_LESSONS_LEARNED.md §6e).
    state = {session.SPECIALIST_KEY: channel._state_for(who)} if who else {}
    created = await runner.session_service.create_session(
        app_name=config.APP_NAME, user_id=case.name, state=state
    )

    replies: list[str] = []
    try:
        for turn in case.turns:
            message = types.Content(role="user", parts=[types.Part(text=turn)])
            spoken: list[str] = []
            async for event in runner.run_async(
                user_id=case.name, session_id=created.id, new_message=message
            ):
                if event.is_final_response() and event.content and event.content.parts:
                    if text := event.content.parts[0].text:
                        spoken.append(text)
            replies.append(" ".join(spoken).strip())
    finally:
        if who:
            _drop_specialist(who["telegram_user_id"])

    after = await runner.session_service.get_session(
        app_name=config.APP_NAME, user_id=case.name, session_id=created.id
    )
    session_state = dict(after.state) if after else {}

    # Voice is scored on EVERY reply, not only the last: a conversation that drifts into "usted"
    # halfway through is exactly what a last-reply check would miss.
    complaints = [
        f"turn {index + 1}: {reason}"
        for index, reply in enumerate(replies)
        for reason in voice_checks.reply_reasons(reply)
    ]
    try:
        passed = bool(case.check(replies, session_state))
    except Exception as exc:  # noqa: BLE001 - a check that raises is a failed case, not a crash
        replies.append(f"[check raised: {type(exc).__name__}: {exc}]")
        passed = False
    return passed, replies, complaints


async def _run_all(cases: tuple[Case, ...], runs: int) -> tuple[dict, dict, dict]:
    results: dict[str, list[bool]] = {case.name: [] for case in cases}
    voice: dict[str, list[str]] = {case.name: [] for case in cases}
    transcripts: dict[str, list[str]] = {}
    for run in range(1, runs + 1):
        for case in cases:
            passed, replies, complaints = await _run_case(case)
            results[case.name].append(passed)
            voice[case.name].extend(complaints)
            transcripts.setdefault(case.name, replies)
            print(f"  run {run}  {'PASS' if passed else 'FAIL'}  {case.name}")
    return results, voice, transcripts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--cases", default="", help="comma-separated case names")
    parser.add_argument("--list", action="store_true", help="print the case names and stop")
    parser.add_argument("--save", action="store_true", help="write the result to eval/history/")
    args = parser.parse_args()

    if args.list:
        for case in by_name(None):
            print(f"{case.name:42s} {','.join(case.tags):18s} {case.note}")
        return 0

    cases = by_name([name.strip() for name in args.cases.split(",") if name.strip()] or None)

    try:
        results, voice, transcripts = asyncio.run(_run_all(cases, args.runs))
    finally:
        _clean_all()

    agg = aggregate(results, runs=args.runs)
    print("\n" + "\n".join(agg.lines()))

    complaints = {name: found for name, found in voice.items() if found}
    if complaints:
        print(f"\nvoice (docs/BRAND_VOICE.md) — {len(complaints)} case(s) with findings:")
        for name, found in complaints.items():
            print(f"  {name}: {'; '.join(sorted(set(found)))}")
    else:
        print("\nvoice: no findings")

    if args.save:
        HISTORY.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
        path = HISTORY / f"{stamp}.json"
        path.write_text(
            json.dumps(
                {
                    "runs": args.runs,
                    "aggregate": agg.lines(),
                    "results": results,
                    "voice": complaints,
                    "transcripts": transcripts,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        print(f"\nsaved {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
