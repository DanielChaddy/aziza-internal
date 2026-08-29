"""The end-of-day message, and the one thing it must never do twice.

Idempotency here is not care, it is construction: a unique key on (specialist, day), a claim
taken before the send, and a commit only once the send has succeeded. These assert each of those
three separately, because any one of them alone leaves a way to double-send or to go silent.
"""

import datetime as dt
from decimal import Decimal

import pytest

from aziza_adk import config, queries, tools
from scripts import daily_summary


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setattr(config, "SUMMARY_SEND_MODE", "live")


@pytest.fixture
def outbox(monkeypatch):
    """Every message the job would send, with the send never reaching the network."""
    sent: list[tuple[str, str]] = []

    async def send_text(chat_id, body):
        sent.append((chat_id, body))
        return type("R", (), {"ok": True, "error_code": None})()

    monkeypatch.setattr(daily_summary.bot_client, "send_text", send_text)
    return sent


@pytest.fixture
def broken_outbox(monkeypatch):
    async def send_text(chat_id, body):
        return type("R", (), {"ok": False, "error_code": 403})()

    monkeypatch.setattr(daily_summary.bot_client, "send_text", send_text)


@pytest.fixture
def sold(ctx, make_specialist):
    """A specialist who billed RD$300.00 and was tipped RD$200.00 today."""
    who = make_specialist("nails", full_name="Yamilé Sentinel")
    context = ctx(who)
    tools.start_ticket("Laura", tool_context=context)
    tools.add_service("manicura normal", 1, tool_context=context)
    tools.record_payment("efectivo", "300", "200", tool_context=context)
    return who


def _today():
    return tools._today()


def _mine(outbox, who) -> list[str]:
    """Just this specialist's messages.

    `daily_summary.run` walks the WHOLE salon, so a tally over its counts measures whatever else
    the database happens to hold — a demo driven by hand, another test's leftovers — rather than
    the property under test. Filtering by the sentinel's own chat id is what keeps these
    re-runnable and order-independent, which is the rule the rest of the suite already follows.
    """
    return [body for chat_id, body in outbox if chat_id == who["telegram_user_id"]]


def _claims(conn, specialist_id) -> int:
    row = queries.fetchone(
        conn,
        "SELECT COUNT(*) AS n FROM daily_summaries WHERE specialist_id = %(s)s",
        {"s": specialist_id},
    )
    return row["n"]


# --- [1] Who is owed a message ------------------------------------------------------------


def test_a_specialist_who_billed_today_gets_one(sold, live, outbox, conn):
    daily_summary.run(_today())
    assert len(_mine(outbox, sold)) == 1


def test_a_specialist_who_billed_nothing_gets_nothing(make_specialist, live, outbox):
    idle = make_specialist("nails")
    daily_summary.run(_today())
    assert _mine(outbox, idle) == []


def test_an_open_ticket_is_not_a_days_work(ctx, make_specialist, live, outbox):
    """Only a closed sale counts; a ticket left open is money not yet taken."""
    who = make_specialist("nails")
    context = ctx(who)
    tools.start_ticket("Laura", tool_context=context)
    tools.add_service("manicura normal", 1, tool_context=context)
    daily_summary.run(_today())
    assert _mine(outbox, who) == []


# --- [2] The figures ----------------------------------------------------------------------


def test_the_message_carries_all_four_figures(sold, live, outbox):
    daily_summary.run(_today())
    body = _mine(outbox, sold)[0]
    assert "Servicios: RD$300.00" in body
    assert f"Tu comisión ({config.COMMISSION_PCT}%): RD$120.00" in body
    assert "Propinas (te las entregamos hoy): RD$200.00" in body
    assert "Total para ti hoy: RD$320.00" in body


def test_the_message_and_my_day_cannot_disagree(sold, ctx, live, outbox):
    """Same renderer, same figures — so a specialist checking mid-afternoon and the night's
    message are answering the same question the same way."""
    daily_summary.run(_today())
    assert tools.my_day(tool_context=ctx(sold))["summary"] == _mine(outbox, sold)[0]


def test_the_recorded_claim_holds_the_figures_that_were_sent(sold, live, outbox, conn):
    daily_summary.run(_today())
    row = queries.fetchone(
        conn,
        "SELECT services_total, commission, tips FROM daily_summaries WHERE specialist_id = %(s)s",
        {"s": sold["id"]},
    )
    assert (row["services_total"], row["commission"], row["tips"]) == (
        Decimal("300.00"),
        Decimal("120.00"),
        Decimal("200.00"),
    )


# --- [3] THE property: it never sends twice, and never goes quiet on a failure -------------


def test_a_second_run_sends_nothing(sold, live, outbox, conn):
    """Scoped to this specialist's claim rather than a tally over the whole database: any other
    sale recorded today — a demo driven by hand, say — is not this test's subject."""
    daily_summary.run(_today())
    outbox.clear()
    daily_summary.run(_today())
    assert _mine(outbox, sold) == []
    assert _claims(conn, sold["id"]) == 1


def test_a_failed_send_records_nothing_so_the_next_run_retries(sold, live, broken_outbox, conn):
    """The claim goes back. A claim committed before the send is how a person is silently
    skipped for the day with no way to notice."""
    daily_summary.run(_today())
    assert _claims(conn, sold["id"]) == 0


def test_the_retry_after_a_failed_send_actually_sends(sold, live, monkeypatch, conn):
    """The whole point of rolling the claim back: the person is told one run late, rather than
    silently skipped for the day with nothing to notice."""
    seen = {"hers": 0}

    async def send_text(chat_id, body):
        # Only THIS specialist's first send fails. run() walks the whole salon, so failing every
        # call would make the assertion depend on whatever else the database holds.
        if chat_id != sold["telegram_user_id"]:
            return type("R", (), {"ok": True, "error_code": None})()
        seen["hers"] += 1
        ok = seen["hers"] > 1
        return type("R", (), {"ok": ok, "error_code": None if ok else 403})()

    monkeypatch.setattr(daily_summary.bot_client, "send_text", send_text)

    daily_summary.run(_today())
    assert _claims(conn, sold["id"]) == 0, "the claim goes back so the next run retries her"
    daily_summary.run(_today())
    assert _claims(conn, sold["id"]) == 1
    assert seen["hers"] == 2


def test_a_simulated_run_records_nothing(sold, outbox, conn, monkeypatch):
    """THE footgun the sibling assistant hit: one dry run against a live database permanently
    marks everyone as already told, and nothing un-sets it."""
    monkeypatch.setattr(config, "SUMMARY_SEND_MODE", "simulate")
    daily_summary.run(_today())
    assert _claims(conn, sold["id"]) == 0


def test_a_simulated_run_does_not_reach_the_network(sold, outbox, monkeypatch):
    monkeypatch.setattr(config, "SUMMARY_SEND_MODE", "simulate")
    daily_summary.run(_today())
    assert _mine(outbox, sold) == []


def test_a_simulated_run_leaves_the_live_one_free_to_send(sold, outbox, conn, monkeypatch):
    monkeypatch.setattr(config, "SUMMARY_SEND_MODE", "simulate")
    daily_summary.run(_today())
    monkeypatch.setattr(config, "SUMMARY_SEND_MODE", "live")
    daily_summary.run(_today())
    assert _claims(conn, sold["id"]) == 1


# --- [4] Another day is another claim -----------------------------------------------------


def test_each_day_gets_its_own_claim(sold, live, outbox, conn):
    """The key is (specialist, day), so two days are two claims and neither blocks the other.

    Asserted on the sentinel's own claims rather than on the job's counts. A tally over those
    measures whatever else the database happens to hold — which is what `_mine` exists to avoid,
    and what made the previous version of this case fail on any day somebody had billed the day
    before.
    """
    daily_summary.run(_today())
    assert _claims(conn, sold["id"]) == 1

    # Move the ticket she already has back a day, so there is a second day to claim.
    yesterday = _today() - dt.timedelta(days=1)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sales SET business_date = %(day)s WHERE specialist_id = %(sid)s",
            {"day": yesterday, "sid": sold["id"]},
        )

    daily_summary.run(yesterday)
    assert _claims(conn, sold["id"]) == 2, "one claim per day, not one per specialist"


# --- [4] Somebody with no way to receive it, and the register ----------------------------------


def test_a_specialist_with_no_telegram_id_is_skipped_and_not_claimed(
    ctx, make_specialist, conn, live, outbox
):
    """An owner records her work and she cannot receive anything yet. Claiming the day would mark
    it reported forever, so the moment she has an id there would be nothing left to send."""
    her = make_specialist("nails", full_name="Zenaida Sinclave", telegram_user_id=None)
    owner = ctx(make_specialist(roles=("owner",), full_name="Zoila Dueña"))
    tools.start_ticket("Laura", on_behalf_of="Zenaida", tool_context=owner)
    tools.add_service("manicura normal", 1, on_behalf_of="Zenaida", tool_context=owner)
    tools.record_payment("efectivo", "300", "0", on_behalf_of="Zenaida", tool_context=owner)

    daily_summary.run(_today())

    assert not _mine(outbox, her)
    claimed = queries.fetchone(
        conn,
        "SELECT 1 FROM daily_summaries WHERE specialist_id = %(s)s AND business_date = %(d)s",
        {"s": her["id"], "d": _today()},
    )
    assert claimed is None, "the day stays unclaimed until she can be reached"


def test_the_owners_are_asked_to_count_the_register(ctx, make_specialist, sold, live, outbox):
    her = make_specialist(roles=("owner",), full_name="Zoila Dueña")
    daily_summary.run(_today())
    asked = [body for chat, body in outbox if chat == her["telegram_user_id"]]
    assert asked and "Cuadra la caja" in asked[0]
    assert "Efectivo: RD$500.00" in asked[0], "300 taken plus the 200 tipped, still in the drawer"
    assert f"{sold['full_name']} — RD$200.00" in asked[0], "and what to hand over"


def test_nobody_is_asked_once_the_register_is_closed(ctx, make_specialist, sold, live, outbox):
    """The already-closed check is the real state rather than a record of having asked."""
    her = make_specialist(roles=("owner",), full_name="Zoila Dueña")
    tools.close_register("500", "0", "0", tool_context=ctx(her))
    daily_summary.run(_today())
    assert not [body for chat, body in outbox if chat == her["telegram_user_id"]]
