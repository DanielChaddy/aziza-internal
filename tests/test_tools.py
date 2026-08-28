"""The tools, called directly with a fake context. No model anywhere.

Two halves. The first needs no database at all and holds the refusals a specialist can trip on
their own; the second drives a whole sale through the real schema.
"""

from decimal import Decimal

import pytest

from aziza_adk import queries, session, tools
from tests.conftest import service_named

MANI = service_named("Manicure clásico")  # nails, RD$800.00
LEGS = service_named("Depilación de piernas")  # wax,   RD$1,500.00


# --- [1] An unregistered sender can do nothing, with no database behind it -----------------


@pytest.mark.parametrize(
    "call",
    [
        lambda c: tools.start_ticket("Laura", c),
        lambda c: tools.add_service("manicure", 1, c),
        lambda c: tools.show_ticket(c),
        lambda c: tools.void_ticket(c),
        lambda c: tools.record_payment("efectivo", "800", "0", c),
        lambda c: tools.my_day(c),
    ],
)
def test_every_tool_refuses_a_session_with_no_specialist(ctx, call):
    """Defense in depth: the channel refused before the model ran and the guard refused before
    the tool did. A tool reached some other way must refuse too."""
    assert call(ctx())["error"] == "not_registered"


# --- [2] Argument validation, before anything is written -----------------------------------


def test_a_ticket_needs_a_client_name(ctx):
    who = {"id": 1, "full_name": "X", "disciplines": ["nails"]}
    assert tools.start_ticket("   ", ctx(who))["error"] == "no_client_name"


@pytest.mark.parametrize("quantity", [0, -1, 21, 1.5, "dos", None])
def test_a_quantity_outside_the_range_is_refused(ctx, quantity):
    who = {"id": 1, "full_name": "X", "disciplines": ["nails"]}
    assert tools.add_service("manicure", quantity, ctx(who))["error"] == "bad_quantity"


@pytest.mark.parametrize("method", ["cheque", "", "bitcoin", None])
def test_a_way_of_paying_the_salon_does_not_take_is_refused(ctx, method):
    who = {"id": 1, "full_name": "X", "disciplines": ["nails"]}
    assert tools.record_payment(method, "800", "0", ctx(who))["error"] == "bad_method"


@pytest.mark.parametrize("amount", ["", "mucho", "abc", "0", "-500"])
def test_an_amount_that_is_not_an_amount_is_refused(ctx, amount):
    who = {"id": 1, "full_name": "X", "disciplines": ["nails"]}
    assert tools.record_payment("efectivo", amount, "0", ctx(who))["error"] == "bad_amount"


@pytest.mark.parametrize(
    "spoken,canonical",
    [
        ("efectivo", "cash"),
        ("Efectivo", "cash"),
        ("cash", "cash"),
        ("tarjeta", "card"),
        ("TARJETA", "card"),
        ("débito", "card"),
        ("transferencia", "transfer"),
        ("Transferencia", "transfer"),
    ],
)
def test_every_way_of_saying_a_method_reaches_the_same_column_value(spoken, canonical):
    from conversation_core import fold

    assert tools._METHODS[fold(spoken).strip()] == canonical


# --- [3] A whole sale, through the real schema ---------------------------------------------


def test_a_ticket_opens_and_shows_the_catalog_price(working):
    context, _ = working
    assert tools.start_ticket("Laura", context)["opened"] is True
    answer = tools.add_service("manicure", 1, context)
    assert answer["total"] == "RD$800.00"
    assert "Cuenta de Laura" in answer["ticket"]


def test_the_price_is_the_salons_and_not_one_the_model_supplied(working, conn):
    """THE property this design rests on. There is no price argument, and the row that lands
    carries the catalog's figure."""
    context, who = working
    tools.start_ticket("Laura", context)
    tools.add_service("manicure clásico", 1, context)
    sale = queries.open_sale(conn, who["id"])
    lines = queries.sale_lines(conn, sale["id"])
    assert lines[0].unit_price == Decimal(MANI["price"])


def test_a_quantity_multiplies_the_catalog_price(working):
    context, _ = working
    tools.start_ticket("Laura", context)
    assert tools.add_service("manicure", 3, context)["total"] == "RD$2,400.00"


def test_two_services_add_up(working):
    context, _ = working
    tools.start_ticket("Laura", context)
    tools.add_service("manicure", 1, context)
    assert tools.add_service("pedicure", 1, context)["total"] == "RD$2,000.00"


def test_a_service_the_salon_does_not_sell_is_refused_and_the_catalog_named(working):
    context, _ = working
    tools.start_ticket("Laura", context)
    answer = tools.add_service("corte de pelo", 1, context)
    assert answer["error"] == "unknown_service"
    assert MANI["name"] in answer["options"]


def test_a_service_outside_the_specialists_area_is_refused(make_specialist, ctx):
    """The wax/nails split is a guard, not a label: a commission booked under the wrong person
    is money."""
    context = ctx(make_specialist("nails"))
    tools.start_ticket("Laura", context)
    answer = tools.add_service("depilación de piernas", 1, context)
    assert answer["error"] == "wrong_discipline"
    assert answer["service"] == LEGS["name"]


def test_someone_who_does_both_may_record_both(make_specialist, ctx):
    context = ctx(make_specialist("nails", "wax"))
    tools.start_ticket("Laura", context)
    assert "error" not in tools.add_service("manicure", 1, context)
    assert tools.add_service("piernas", 1, context)["total"] == "RD$2,300.00"


def test_a_second_ticket_is_refused_while_one_is_open(working):
    context, _ = working
    tools.start_ticket("Laura", context)
    assert tools.start_ticket("Ana", context)["error"] == "ticket_already_open"


def test_nothing_can_be_added_without_a_ticket(working):
    context, _ = working
    assert tools.add_service("manicure", 1, context)["error"] == "no_open_ticket"
    assert tools.show_ticket(context)["error"] == "no_open_ticket"
    assert tools.record_payment("efectivo", "800", "0", context)["error"] == "no_open_ticket"


def test_voiding_frees_the_specialist_to_start_again(working):
    context, _ = working
    tools.start_ticket("Laura", context)
    assert tools.void_ticket(context)["voided"] is True
    assert tools.start_ticket("Ana", context)["opened"] is True


# --- [4] Charging ---------------------------------------------------------------------------


def test_a_charge_before_the_ticket_was_shown_is_refused(working):
    """The confirm-first gate: a specialist cannot charge a total they were never shown."""
    context, who = working
    tools.start_ticket("Laura", context)
    tools.add_service("manicure", 1, context)
    context.state.pop(session.QUOTED_KEY, None)  # as if the ticket had never been quoted
    assert tools.record_payment("efectivo", "800", "0", context)["error"] == "not_quoted"


def test_quoting_one_ticket_does_not_authorize_charging_the_next(working):
    """Keyed on the ticket rather than a flag — a different client and a different amount."""
    context, _ = working
    tools.start_ticket("Laura", context)
    tools.add_service("manicure", 1, context)
    tools.void_ticket(context)
    tools.start_ticket("Ana", context)
    tools.add_service("pedicure", 1, context)
    context.state[session.QUOTED_KEY] = {"sale_ref": "some-other-ticket"}
    assert tools.record_payment("efectivo", "1200", "0", context)["error"] == "not_quoted"


def test_an_empty_ticket_cannot_be_charged(working):
    context, _ = working
    tools.start_ticket("Laura", context)
    tools.show_ticket(context)
    assert tools.record_payment("efectivo", "100", "0", context)["error"] == "empty_ticket"


def test_paying_the_whole_total_closes_the_sale_and_returns_the_receipt(working):
    context, _ = working
    tools.start_ticket("Laura", context)
    tools.add_service("manicure", 1, context)
    answer = tools.record_payment("efectivo", "800", "0", context)
    assert answer["paid"] is True
    assert "Cobrado — Laura" in answer["receipt"] and "Total: RD$800.00" in answer["receipt"]


def test_a_split_payment_keeps_the_ticket_open_until_it_adds_up(working):
    context, _ = working
    tools.start_ticket("Laura", context)
    tools.add_service("manicure", 1, context)
    first = tools.record_payment("efectivo", "300", "0", context)
    assert first["paid"] is False and first["remaining"] == "RD$500.00"
    second = tools.record_payment("tarjeta", "500", "0", context)
    assert second["paid"] is True
    assert "Efectivo — RD$300.00" in second["receipt"]
    assert "Tarjeta — RD$500.00" in second["receipt"]


def test_paying_more_than_is_owed_is_refused_rather_than_absorbed(working):
    """It is either a typo or a tip, and guessing which writes the wrong commission either way."""
    context, _ = working
    tools.start_ticket("Laura", context)
    tools.add_service("manicure", 1, context)
    answer = tools.record_payment("efectivo", "1000", "0", context)
    assert answer["error"] == "overpayment" and answer["remaining"] == "RD$800.00"


def test_a_tip_rides_on_the_payment_and_stays_out_of_the_total(working, conn):
    context, who = working
    tools.start_ticket("Laura", context)
    tools.add_service("manicure", 1, context)
    answer = tools.record_payment("efectivo", "800", "200", context)
    assert answer["paid"] is True
    assert "Total: RD$800.00" in answer["receipt"]
    assert "Propina: RD$200.00" in answer["receipt"]
    sale = queries.fetchone(
        conn,
        "SELECT services_total FROM sales WHERE specialist_id = %(s)s AND status = 'paid'",
        {"s": who["id"]},
    )
    assert sale["services_total"] == Decimal("800.00")


def test_a_closed_sale_frees_the_specialist_for_the_next_client(working):
    context, _ = working
    tools.start_ticket("Laura", context)
    tools.add_service("manicure", 1, context)
    tools.record_payment("efectivo", "800", "0", context)
    assert tools.start_ticket("Ana", context)["opened"] is True


# --- [5] The day ----------------------------------------------------------------------------


def test_the_day_counts_only_what_was_actually_paid(working):
    context, _ = working
    tools.start_ticket("Laura", context)
    tools.add_service("manicure", 1, context)
    tools.record_payment("efectivo", "800", "200", context)
    tools.start_ticket("Ana", context)  # opened and left open
    tools.add_service("pedicure", 1, context)

    summary = tools.my_day(context)["summary"]
    assert "Servicios: RD$800.00" in summary
    assert "Tu comisión (40%): RD$320.00" in summary
    assert "Propinas: RD$200.00" in summary
    assert "Total para ti: RD$520.00" in summary


def test_a_specialist_with_no_sales_today_sees_zeroes(working):
    summary = tools.my_day(working[0])["summary"]
    assert "Servicios: RD$0.00" in summary and "Total para ti: RD$0.00" in summary
