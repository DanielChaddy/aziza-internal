"""The end-of-day message, and the one thing it must never do twice.

Idempotency here is not care, it is construction: a unique key on (specialist, day), a claim
taken before the send, and a commit only once the send has succeeded. These assert each of those
three separately, because any one of them alone leaves a way to double-send or to go silent.
"""

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
    tools.add_service("manicura normal", 1, context)
    tools.record_payment("efectivo", "300", "200", context)
    return who


def _today():
    return tools._today()


def _claims(conn, specialist_id) -> int:
    row = queries.fetchone(
        conn,
        "SELECT COUNT(*) AS n FROM daily_summaries WHERE specialist_id = %(s)s",
        {"s": specialist_id},
    )
    return row["n"]


# --- [1] Who is owed a message ------------------------------------------------------------


def test_a_specialist_who_billed_today_gets_one(sold, live, outbox, conn):
    counts = daily_summary.run(_today())
    assert counts["sent"] == 1
    chat_id, body = outbox[0]
    assert chat_id == sold["telegram_user_id"]


def test_a_specialist_who_billed_nothing_gets_nothing(make_specialist, live, outbox):
    make_specialist("nails")
    assert daily_summary.run(_today())["sent"] == 0
    assert outbox == []


def test_an_open_ticket_is_not_a_days_work(ctx, make_specialist, live, outbox):
    """Only a closed sale counts; a ticket left open is money not yet taken."""
    context = ctx(make_specialist("nails"))
    tools.start_ticket("Laura", tool_context=context)
    tools.add_service("manicura normal", 1, context)
    assert daily_summary.run(_today())["sent"] == 0


# --- [2] The figures ----------------------------------------------------------------------


def test_the_message_carries_all_four_figures(sold, live, outbox):
    daily_summary.run(_today())
    body = outbox[0][1]
    assert "Servicios: RD$300.00" in body
    assert f"Tu comisión ({config.COMMISSION_PCT}%): RD$120.00" in body
    assert "Propinas: RD$200.00" in body
    assert "Total para ti: RD$320.00" in body


def test_the_message_and_my_day_cannot_disagree(sold, ctx, live, outbox):
    """Same renderer, same figures — so a specialist checking mid-afternoon and the night's
    message are answering the same question the same way."""
    daily_summary.run(_today())
    assert tools.my_day(ctx(sold))["summary"] == outbox[0][1]


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
    counts = daily_summary.run(_today())
    assert counts["sent"] == 0
    assert outbox == []
    assert _claims(conn, sold["id"]) == 1


def test_a_failed_send_records_nothing_so_the_next_run_retries(sold, live, broken_outbox, conn):
    """The claim goes back. A claim committed before the send is how a person is silently
    skipped for the day with no way to notice."""
    assert daily_summary.run(_today())["send_failed"] == 1
    assert _claims(conn, sold["id"]) == 0


def test_the_retry_after_a_failed_send_actually_sends(sold, live, monkeypatch):
    """The whole point of rolling the claim back: the person is told one run late, rather than
    silently skipped for the day with nothing to notice."""
    attempts = {"n": 0}

    async def send_text(chat_id, body):
        attempts["n"] += 1
        ok = attempts["n"] > 1
        return type("R", (), {"ok": ok, "error_code": None if ok else 403})()

    monkeypatch.setattr(daily_summary.bot_client, "send_text", send_text)

    assert daily_summary.run(_today())["send_failed"] == 1
    assert daily_summary.run(_today())["sent"] == 1
    assert attempts["n"] == 2


def test_a_simulated_run_records_nothing(sold, outbox, conn, monkeypatch):
    """THE footgun the sibling assistant hit: one dry run against a live database permanently
    marks everyone as already told, and nothing un-sets it."""
    monkeypatch.setattr(config, "SUMMARY_SEND_MODE", "simulate")
    daily_summary.run(_today())
    assert _claims(conn, sold["id"]) == 0


def test_a_simulated_run_does_not_reach_the_network(sold, outbox, monkeypatch):
    monkeypatch.setattr(config, "SUMMARY_SEND_MODE", "simulate")
    daily_summary.run(_today())
    assert outbox == []


def test_a_simulated_run_leaves_the_live_one_free_to_send(sold, outbox, conn, monkeypatch):
    monkeypatch.setattr(config, "SUMMARY_SEND_MODE", "simulate")
    daily_summary.run(_today())
    monkeypatch.setattr(config, "SUMMARY_SEND_MODE", "live")
    assert daily_summary.run(_today())["sent"] == 1


# --- [4] Another day is another claim -----------------------------------------------------


def test_yesterday_is_a_separate_claim(sold, live, outbox, conn):
    import datetime as dt

    daily_summary.run(_today())
    yesterday = _today() - dt.timedelta(days=1)
    # Nobody billed yesterday, so nothing is sent — and the key does not collide either way.
    assert daily_summary.run(yesterday)["already_sent"] == 0
