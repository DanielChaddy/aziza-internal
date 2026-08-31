"""The tools, called directly with a fake context. No model anywhere.

Two halves. The first needs no database at all and holds the refusals a specialist can trip on
their own; the second drives a whole sale through the real schema.
"""

from decimal import Decimal

import pytest

from aziza_adk import queries, receipts, session, tools
from tests.conftest import service_named

MANI = service_named("Manicura + pintura normal")  # nails, RD$300 F / RD$400 M
PEDI = service_named("Pedicura + pintura normal")  # nails, RD$400 F / RD$500 M
LEGS = service_named("Piernas completas")  # wax,   RD$850 F / RD$1,400 M


# --- [1] An unregistered sender can do nothing, with no database behind it -----------------


@pytest.mark.parametrize(
    "call",
    [
        lambda c: tools.start_ticket("Laura", tool_context=c),
        lambda c: tools.add_service("manicura normal", 1, tool_context=c),
        lambda c: tools.show_ticket(tool_context=c),
        lambda c: tools.void_ticket(tool_context=c),
        lambda c: tools.record_payment("efectivo", "300", "0", tool_context=c),
        lambda c: tools.set_client_gender("hombre", tool_context=c),
        lambda c: tools.sell_product("agua", 1, tool_context=c),
        lambda c: tools.buy_product("agua", 1, tool_context=c),
        lambda c: tools.settle_debt("25", "productos", "efectivo", tool_context=c),
        lambda c: tools.my_day(tool_context=c),
    ],
)
def test_every_tool_refuses_a_session_with_no_specialist(ctx, call):
    """Defense in depth: the channel refused before the model ran and the guard refused before
    the tool did. A tool reached some other way must refuse too."""
    assert call(ctx())["error"] == "not_registered"


# --- [2] Argument validation, before anything is written -----------------------------------


def test_a_ticket_needs_a_client_name(ctx):
    who = {"id": 1, "full_name": "X", "disciplines": ["nails"]}
    assert tools.start_ticket("   ", tool_context=ctx(who))["error"] == "no_client_name"


def test_a_ticket_named_after_the_work_is_refused(working):
    """She said what she did and never said who for. Booking it opens a ticket for a client
    called "Axilas y bc", priced off the name table — wrong on the receipt and wrong on the total.
    """
    context, _ = working
    answer = tools.start_ticket("Axilas y bc", tool_context=context)
    assert answer["error"] == "name_is_the_work"
    assert answer["matched"] == "Axilas"


def test_a_client_whose_name_contains_a_catalog_word_is_still_served(working):
    """The guard reads whole words, so "Yaritza" is a client and not a Ritz."""
    context, _ = working
    assert "error" not in tools.start_ticket("Yaritza", tool_context=context)


@pytest.mark.parametrize("quantity", [0, -1, 21, 1.5, "dos", None])
def test_a_quantity_outside_the_range_is_refused(ctx, quantity):
    who = {"id": 1, "full_name": "X", "disciplines": ["nails"]}
    assert (
        tools.add_service("manicura normal", quantity, tool_context=ctx(who))["error"]
        == "bad_quantity"
    )


@pytest.mark.parametrize("method", ["cheque", "", "bitcoin", None])
def test_a_way_of_paying_the_salon_does_not_take_is_refused(ctx, method):
    who = {"id": 1, "full_name": "X", "disciplines": ["nails"]}
    assert tools.record_payment(method, "800", "0", tool_context=ctx(who))["error"] == "bad_method"


@pytest.mark.parametrize("amount", ["", "mucho", "abc", "0", "-500"])
def test_an_amount_that_is_not_an_amount_is_refused(ctx, amount):
    who = {"id": 1, "full_name": "X", "disciplines": ["nails"]}
    assert (
        tools.record_payment("efectivo", amount, "0", tool_context=ctx(who))["error"]
        == "bad_amount"
    )


@pytest.mark.parametrize(
    "spoken,canonical",
    [
        ("efectivo", "cash"),
        ("Efectivo", "cash"),
        ("cash", "cash"),
        ("banreservas", "banreservas"),
        ("BANRESERVAS", "banreservas"),
        ("Banco de Reservas", "banreservas"),
        ("bhd", "bhd"),
        ("BHD", "bhd"),
    ],
)
def test_every_way_of_saying_a_method_reaches_the_same_column_value(spoken, canonical):
    from conversation_core import fold

    assert tools._METHODS[fold(spoken).strip()] == canonical


# --- [3] A whole sale, through the real schema ---------------------------------------------


def test_a_ticket_opens_and_shows_the_catalog_price(working):
    context, _ = working
    assert tools.start_ticket("Laura", tool_context=context)["opened"] is True
    answer = tools.add_service("manicura normal", 1, tool_context=context)
    assert answer["total"] == "RD$300.00"
    assert "Cuenta de Laura" in answer["ticket"]


def test_the_price_is_the_salons_and_not_one_the_model_supplied(working, conn):
    """THE property this design rests on. There is no price argument, and the row that lands
    carries the catalog's figure."""
    context, who = working
    tools.start_ticket("Laura", tool_context=context)
    tools.add_service("manicura + pintura normal", 1, tool_context=context)
    sale = queries.open_sale(conn, who["id"])
    lines = queries.sale_lines(conn, sale["id"])
    assert lines[0].unit_price == Decimal(MANI["price_female"])


def test_a_quantity_multiplies_the_catalog_price(working):
    context, _ = working
    tools.start_ticket("Laura", tool_context=context)
    assert tools.add_service("manicura normal", 3, tool_context=context)["total"] == "RD$900.00"


def test_two_services_add_up(working):
    context, _ = working
    tools.start_ticket("Laura", tool_context=context)
    tools.add_service("manicura normal", 1, tool_context=context)
    assert tools.add_service("pedicura normal", 1, tool_context=context)["total"] == "RD$700.00"


def test_a_service_the_salon_does_not_sell_is_refused_and_the_catalog_named(working):
    context, _ = working
    tools.start_ticket("Laura", tool_context=context)
    answer = tools.add_service("corte de pelo", 1, tool_context=context)
    assert answer["error"] == "unknown_service"
    assert MANI["name"] in answer["options"]


def test_a_service_outside_the_specialists_area_is_refused(make_specialist, ctx):
    """The wax/nails split is a guard, not a label: a commission booked under the wrong person
    is money."""
    context = ctx(make_specialist("nails"))
    tools.start_ticket("Laura", tool_context=context)
    answer = tools.add_service("piernas", 1, tool_context=context)
    assert answer["error"] == "wrong_discipline"
    assert answer["service"] == LEGS["name"]


def test_someone_who_does_both_may_record_both(make_specialist, ctx):
    context = ctx(make_specialist("nails", "wax"))
    tools.start_ticket("Laura", tool_context=context)
    assert "error" not in tools.add_service("manicura normal", 1, tool_context=context)
    assert tools.add_service("piernas", 1, tool_context=context)["total"] == "RD$1,150.00"


def test_a_second_ticket_is_refused_while_one_is_open(working):
    context, _ = working
    tools.start_ticket("Laura", tool_context=context)
    assert tools.start_ticket("Ana", tool_context=context)["error"] == "ticket_already_open"


def test_nothing_can_be_added_without_a_ticket(working):
    context, _ = working
    assert (
        tools.add_service("manicura normal", 1, tool_context=context)["error"] == "no_open_ticket"
    )
    assert tools.show_ticket(tool_context=context)["error"] == "no_open_ticket"
    assert (
        tools.record_payment("efectivo", "300", "0", tool_context=context)["error"]
        == "no_open_ticket"
    )


def test_voiding_frees_the_specialist_to_start_again(working):
    context, _ = working
    tools.start_ticket("Laura", tool_context=context)
    assert tools.void_ticket(tool_context=context)["voided"] is True
    assert tools.start_ticket("Ana", tool_context=context)["opened"] is True


# --- [4] Charging ---------------------------------------------------------------------------


def test_a_charge_before_the_ticket_was_shown_is_refused(working):
    """The confirm-first gate: a specialist cannot charge a total they were never shown."""
    context, who = working
    tools.start_ticket("Laura", tool_context=context)
    tools.add_service("manicura normal", 1, tool_context=context)
    context.state.pop(session.QUOTED_KEY, None)  # as if the ticket had never been quoted
    assert (
        tools.record_payment("efectivo", "300", "0", tool_context=context)["error"] == "not_quoted"
    )


def test_quoting_one_ticket_does_not_authorize_charging_the_next(working):
    """Keyed on the ticket rather than a flag — a different client and a different amount."""
    context, _ = working
    tools.start_ticket("Laura", tool_context=context)
    tools.add_service("manicura normal", 1, tool_context=context)
    tools.void_ticket(tool_context=context)
    tools.start_ticket("Ana", tool_context=context)
    tools.add_service("pedicura normal", 1, tool_context=context)
    context.state[session.QUOTED_KEY] = {"sale_ref": "some-other-ticket"}
    assert (
        tools.record_payment("efectivo", "400", "0", tool_context=context)["error"] == "not_quoted"
    )


def test_an_empty_ticket_cannot_be_charged(working):
    context, _ = working
    tools.start_ticket("Laura", tool_context=context)
    tools.show_ticket(tool_context=context)
    assert (
        tools.record_payment("efectivo", "100", "0", tool_context=context)["error"]
        == "empty_ticket"
    )


def test_paying_the_whole_total_closes_the_sale_and_returns_the_receipt(working):
    context, _ = working
    tools.start_ticket("Laura", tool_context=context)
    tools.add_service("manicura normal", 1, tool_context=context)
    answer = tools.record_payment("efectivo", "300", "0", tool_context=context)
    assert answer["paid"] is True
    assert "Cobrado — Laura" in answer["receipt"] and "Total: RD$300.00" in answer["receipt"]


def test_a_split_payment_keeps_the_ticket_open_until_it_adds_up(working):
    context, _ = working
    tools.start_ticket("Laura", tool_context=context)
    tools.add_service("manicura normal", 1, tool_context=context)
    first = tools.record_payment("efectivo", "100", "0", tool_context=context)
    assert first["paid"] is False and first["remaining"] == "RD$200.00"
    second = tools.record_payment("banreservas", "200", "0", tool_context=context)
    assert second["paid"] is True
    assert "Efectivo — RD$100.00" in second["receipt"]
    assert "Banreservas — RD$200.00" in second["receipt"]


def test_cash_over_the_total_comes_back_as_change(working, conn):
    """She handed over a note. The difference is the client's and leaves the drawer with her."""
    context, _ = working
    tools.start_ticket("Laura", tool_context=context)
    tools.add_service("manicura normal", 1, tool_context=context)
    answer = tools.record_payment("efectivo", "500", "0", tool_context=context)
    assert answer["paid"] is True
    assert "Vuelto: RD$200.00" in answer["receipt"]
    assert "Propina" not in answer["receipt"]
    row = queries.fetchone(
        conn,
        "SELECT amount, tip, change_given FROM sale_payments ORDER BY id DESC LIMIT 1",
    )
    # `amount` is what the TICKET received, so the totals still add up to the ticket.
    assert (row["amount"], row["tip"], row["change_given"]) == (
        Decimal("300.00"),
        Decimal("0.00"),
        Decimal("200.00"),
    )


def test_a_transfer_over_the_total_is_a_tip(working):
    """Nobody sends 500 by mistake when the ticket says 300, and no change can be handed back."""
    context, _ = working
    tools.start_ticket("Laura", tool_context=context)
    tools.add_service("manicura normal", 1, tool_context=context)
    answer = tools.record_payment("bhd", "500", "0", tool_context=context)
    assert answer["paid"] is True
    assert "Propina: RD$200.00" in answer["receipt"]
    assert "Vuelto" not in answer["receipt"]


def test_what_she_says_beats_the_method_default(working):
    """The default is a guess about an ordinary case, and she was there."""
    context, _ = working
    tools.start_ticket("Laura", tool_context=context)
    tools.add_service("manicura normal", 1, tool_context=context)
    answer = tools.record_payment("efectivo", "500", "0", extra="propina", tool_context=context)
    assert "Propina: RD$200.00" in answer["receipt"] and "Vuelto" not in answer["receipt"]


def test_an_extra_she_words_unrecognizably_is_asked_about(working):
    """Refused rather than defaulted: the argument was set, so she meant something by it."""
    context, _ = working
    tools.start_ticket("Laura", tool_context=context)
    tools.add_service("manicura normal", 1, tool_context=context)
    answer = tools.record_payment("efectivo", "500", "0", extra="ni idea", tool_context=context)
    assert answer["error"] == "bad_extra" and answer["extra"] == "RD$200.00"


def test_a_tip_rides_on_the_payment_and_stays_out_of_the_total(working, conn):
    context, who = working
    tools.start_ticket("Laura", tool_context=context)
    tools.add_service("manicura normal", 1, tool_context=context)
    answer = tools.record_payment("efectivo", "300", "200", tool_context=context)
    assert answer["paid"] is True
    assert "Total: RD$300.00" in answer["receipt"]
    assert "Propina: RD$200.00" in answer["receipt"]
    sale = queries.fetchone(
        conn,
        "SELECT services_total FROM sales WHERE specialist_id = %(s)s AND status = 'paid'",
        {"s": who["id"]},
    )
    assert sale["services_total"] == Decimal("300.00")


def test_a_closed_sale_frees_the_specialist_for_the_next_client(working):
    context, _ = working
    tools.start_ticket("Laura", tool_context=context)
    tools.add_service("manicura normal", 1, tool_context=context)
    tools.record_payment("efectivo", "300", "0", tool_context=context)
    assert tools.start_ticket("Ana", tool_context=context)["opened"] is True


# --- [5] The day ----------------------------------------------------------------------------


def test_the_day_counts_only_what_was_actually_paid(working):
    context, _ = working
    tools.start_ticket("Laura", tool_context=context)
    tools.add_service("manicura normal", 1, tool_context=context)
    tools.record_payment("efectivo", "300", "200", tool_context=context)
    tools.start_ticket("Ana", tool_context=context)  # opened and left open
    tools.add_service("pedicura normal", 1, tool_context=context)

    summary = tools.my_day(tool_context=context)["summary"]
    assert "Servicios: RD$300.00" in summary
    assert "Tu comisión (40%): RD$120.00" in summary
    assert "Propinas (te las entregamos hoy): RD$200.00" in summary
    assert "Total para ti hoy: RD$320.00" in summary


def test_a_specialist_with_no_sales_today_sees_zeroes(working):
    summary = tools.my_day(tool_context=working[0])["summary"]
    assert "Servicios: RD$0.00" in summary and "Total para ti hoy: RD$0.00" in summary


# --- [6] Which client the ticket is priced for ----------------------------------------------


def test_a_recognized_name_is_priced_without_a_notice(working):
    context, _ = working
    assert tools.start_ticket("Laura", tool_context=context)["priced_for"] == "femenino"
    answer = tools.add_service("manicura normal", 1, tool_context=context)
    assert answer["total"] == "RD$300.00"
    assert "Precio: femenino" in answer["ticket"]
    assert receipts.GENDER_ASSUMED_TEXT not in answer["ticket"]


def test_an_unrecognized_name_is_priced_female_and_the_ticket_says_so(working):
    """The tables cannot be exhaustive, so the one thing that must not happen is silence."""
    context, _ = working
    tools.start_ticket("Ariel", tool_context=context)
    answer = tools.add_service("manicura normal", 1, tool_context=context)
    assert answer["total"] == "RD$300.00"
    assert receipts.GENDER_ASSUMED_TEXT in answer["ticket"]


def test_nothing_is_said_where_the_client_cannot_change_a_figure(working):
    """The acrylic block is one price for everyone. Naming the client there is noise."""
    context, _ = working
    tools.start_ticket("Ariel", tool_context=context)
    answer = tools.add_service("acrilico vip", 1, tool_context=context)
    assert "Precio:" not in answer["ticket"]
    assert receipts.GENDER_ASSUMED_TEXT not in answer["ticket"]


def test_the_specialist_saying_so_beats_the_name(working):
    context, _ = working
    tools.start_ticket("Laura", client_gender="hombre", tool_context=context)
    assert tools.add_service("manicura normal", 1, tool_context=context)["total"] == "RD$400.00"


def test_correcting_the_client_reprices_the_whole_ticket(working):
    context, _ = working
    tools.start_ticket("Laura", tool_context=context)
    tools.add_service("manicura normal", 1, tool_context=context)
    answer = tools.set_client_gender("hombre", tool_context=context)
    assert answer["total"] == "RD$400.00"
    assert "Precio: masculino" in answer["ticket"]


def test_a_service_the_salon_does_not_do_for_that_client_is_refused(make_specialist, ctx):
    """None is not a zero and not the other column — RD$0.00 would be worse than a refusal."""
    context = ctx(make_specialist("wax"))
    tools.start_ticket("Luis", tool_context=context)
    answer = tools.add_service("brasilero completo", 1, tool_context=context)
    assert answer["error"] == "not_offered_to_client"
    assert answer["service"] == "Brasilero completo"


def test_correcting_the_client_is_refused_when_a_line_stands_in_the_way(make_specialist, ctx):
    """Dropping the line silently would rewrite a ticket she has already read."""
    context = ctx(make_specialist("wax"))
    tools.start_ticket("Laura", tool_context=context)
    tools.add_service("brasilero completo", 1, tool_context=context)
    answer = tools.set_client_gender("hombre", tool_context=context)
    assert answer["error"] == "not_offered_to_client"
    assert "Brasilero completo" in answer["services"]


def test_a_total_that_changed_since_it_was_shown_cannot_be_charged(working, conn):
    """THE gate, and why it is keyed on the total rather than the ticket alone: re-pricing moves
    the figure, and the one she was shown must stop authorizing the one she was not."""
    context, who = working
    tools.start_ticket("Laura", tool_context=context)
    tools.add_service("manicura normal", 1, tool_context=context)
    tools.set_client_gender("hombre", tool_context=context)

    sale = queries.open_sale(conn, who["id"])
    # as if she had been shown RD$300.00 and the ticket had moved behind her
    context.state[session.QUOTED_KEY] = {"sale_ref": sale["sale_ref"], "total": "300.00"}
    assert (
        tools.record_payment("efectivo", "400", "0", tool_context=context)["error"] == "not_quoted"
    )


# --- [7] Products, and what a specialist owes -----------------------------------------------


def test_a_product_is_charged_to_the_client_but_pays_no_commission(working):
    """THE property behind two totals and two line tables: commission is taken on work."""
    context, _ = working
    tools.start_ticket("Laura", tool_context=context)
    tools.add_service("manicura normal", 1, tool_context=context)
    answer = tools.sell_product("agua", 1, tool_context=context)
    assert answer["total"] == "RD$325.00"
    assert "Productos:" in answer["ticket"]

    tools.record_payment("efectivo", "325", "0", tool_context=context)
    summary = tools.my_day(tool_context=context)["summary"]
    assert "Servicios: RD$300.00" in summary
    assert "Tu comisión (40%): RD$120.00" in summary
    assert "Productos vendidos: RD$25.00" in summary


def test_a_ticket_can_hold_nothing_but_products(working):
    context, _ = working
    tools.start_ticket("Laura", tool_context=context)
    assert tools.sell_product("coca", 2, tool_context=context)["total"] == "RD$100.00"
    assert tools.record_payment("efectivo", "100", "0", tool_context=context)["paid"] is True


def test_a_specialist_buying_for_herself_owes_rather_than_sells(working, conn):
    context, who = working
    answer = tools.buy_product("agua", 2, tool_context=context)
    assert answer["charged"] == "RD$30.00"  # her price, not the client's RD$25.00
    assert answer["balance"] == "RD$30.00"
    assert queries.open_sale(conn, who["id"]) is None  # no ticket was touched


def test_part_of_a_debt_can_be_paid_and_the_rest_carried(working):
    """A settled flag per purchase could not express this, which is why it is a ledger."""
    context, _ = working
    tools.buy_product("presidente", 1, tool_context=context)  # RD$125.00 at her price

    def pay(amount: str) -> dict:
        return tools.settle_debt(amount, "productos", "efectivo", tool_context=context)

    assert pay("50")["balance"] == "RD$75.00"
    assert pay("75")["balance"] == "RD$0.00"
    assert pay("10")["error"] == "nothing_owed"


def test_paying_more_than_is_owed_is_refused(working):
    context, _ = working
    tools.buy_product("agua", 1, tool_context=context)
    answer = tools.settle_debt("100", "productos", "efectivo", tool_context=context)
    assert answer["error"] == "more_than_owed"


def test_what_she_owes_shows_on_her_day(working):
    context, _ = working
    tools.buy_product("agua", 1, tool_context=context)
    assert "• Consumo: RD$15.00" in tools.my_day(tool_context=context)["summary"]


# --- [8] An owner, who is the one caller that can name somebody else -------------------------
#
# Sentinel names are deliberately unlike the seeded roster's: `working_specialists` returns every
# active specialist, so a test that called its own person "Yamilé" would collide with the demo
# data and measure resolution instead of what it meant to.


@pytest.fixture
def owner(ctx, make_specialist):
    """An owner who does no salon work: she names whose every entry is."""
    return ctx(make_specialist(full_name="Zoila Dueña", roles=("owner",)))


def test_an_ordinary_specialist_cannot_name_anyone_else(working):
    """The tool body refuses even though the guard already did — a tool reached another way must
    not move a commission to a person the sender is not."""
    context, _ = working
    answer = tools.start_ticket("Laura", on_behalf_of="Zenaida", tool_context=context)
    assert answer["error"] == "not_an_owner"


@pytest.mark.parametrize(
    "call",
    [
        lambda c: tools.start_ticket("Laura", tool_context=c),
        lambda c: tools.add_service("manicura normal", 1, tool_context=c),
        lambda c: tools.sell_product("agua", 1, tool_context=c),
        lambda c: tools.show_ticket(tool_context=c),
        lambda c: tools.void_ticket(tool_context=c),
        lambda c: tools.record_payment("efectivo", "300", "0", tool_context=c),
        lambda c: tools.buy_product("agua", 1, tool_context=c),
        lambda c: tools.settle_debt("15", "productos", "efectivo", tool_context=c),
        lambda c: tools.my_day(tool_context=c),
    ],
)
def test_an_owner_naming_nobody_is_refused_rather_than_credited(owner, call):
    """THE property of this design: she does no salon work, so a sale in her name is a commission
    paid to the wrong person. Omission is never an attribution."""
    assert call(owner)["error"] == "specialist_required"


def test_an_owner_who_also_works_records_her_own_when_she_names_nobody(ctx, make_specialist):
    """THE property of an additive role: holding `owner` widens what she may do and takes nothing
    away. Naming nobody is her own work, exactly as it is for a specialist who is not an owner."""
    her = make_specialist("wax", full_name="Zenaida Dueña", roles=("owner",))
    context = ctx(her)
    assert tools.start_ticket("Laura", tool_context=context)["opened"]
    answer = tools.add_service("axilas", 1, tool_context=context)
    assert "error" not in answer
    assert "Trabajo de:" not in answer["ticket"], "her own work is not attributed to anyone"


def test_an_owner_who_also_works_can_still_name_somebody_else(ctx, make_specialist, conn):
    """The other half: widening is not a swap. She keeps the naming an owner has."""
    her = make_specialist("wax", full_name="Zenaida Dueña", roles=("owner",))
    other = make_specialist("nails", full_name="Ubaldina Segunda")
    tools.start_ticket("Laura", on_behalf_of="Ubaldina", tool_context=ctx(her))
    assert queries.open_sale(conn, other["id"]) is not None
    assert queries.open_sale(conn, her["id"]) is None


def test_work_can_be_recorded_for_someone_who_cannot_type(owner, make_specialist, conn):
    """A specialist with no Telegram id reaches nothing herself, which is exactly why she must be
    reachable through an owner — otherwise the salon cannot record her work at all."""
    her = make_specialist("nails", full_name="Zenaida Sinclave", telegram_user_id=None)
    assert tools.start_ticket("Laura", on_behalf_of="Zenaida", tool_context=owner)["opened"]
    assert queries.open_sale(conn, her["id"]) is not None


def test_an_owner_records_against_the_specialist_she_named(owner, make_specialist, conn):
    her = make_specialist("nails", full_name="Zenaida Prueba")
    assert tools.start_ticket("Laura", on_behalf_of="Zenaida", tool_context=owner)["opened"]
    answer = tools.add_service("manicura normal", 1, on_behalf_of="Zenaida", tool_context=owner)
    assert answer["total"] == "RD$300.00"

    sale = queries.open_sale(conn, her["id"])
    assert sale is not None, "the ticket belongs to the specialist, not the owner"
    assert queries.open_sale(conn, session.specialist_id(owner)) is None


def test_the_ticket_names_whose_work_it_is(owner, make_specialist):
    make_specialist("nails", full_name="Zenaida Prueba")
    tools.start_ticket("Laura", on_behalf_of="Zenaida", tool_context=owner)
    answer = tools.add_service("manicura normal", 1, on_behalf_of="Zenaida", tool_context=owner)
    assert "Trabajo de: Zenaida Prueba" in answer["ticket"]


def test_a_specialist_recording_her_own_work_is_not_told_whose_it_is(working):
    """Shown only where it could be wrong, as the client label is."""
    context, _ = working
    tools.start_ticket("Laura", tool_context=context)
    answer = tools.add_service("manicura normal", 1, tool_context=context)
    assert "Trabajo de:" not in answer["ticket"]


def test_the_audit_column_holds_who_typed_it(owner, make_specialist, conn):
    her = make_specialist("nails", full_name="Zenaida Prueba")
    tools.start_ticket("Laura", on_behalf_of="Zenaida", tool_context=owner)
    row = queries.fetchone(
        conn,
        "SELECT specialist_id, recorded_by FROM sales WHERE specialist_id = %(s)s",
        {"s": her["id"]},
    )
    assert row["specialist_id"] == her["id"]
    assert row["recorded_by"] == session.specialist_id(owner)


def test_the_area_checked_is_hers_and_not_the_owners(owner, make_specialist):
    """An owner holds no disciplines at all, so checking the sender's would refuse everything —
    or, worse, let anything through."""
    make_specialist("nails", full_name="Zenaida Prueba")
    tools.start_ticket("Laura", on_behalf_of="Zenaida", tool_context=owner)
    assert "error" not in tools.add_service(
        "manicura normal", 1, on_behalf_of="Zenaida", tool_context=owner
    )
    refused = tools.add_service("piernas", 1, on_behalf_of="Zenaida", tool_context=owner)
    assert refused["error"] == "wrong_discipline"


def test_two_specialists_sharing_a_first_name_come_back_as_both(owner, make_specialist):
    make_specialist("nails", full_name="Zenaida Prueba")
    make_specialist("nails", full_name="Zenaida Segunda")
    answer = tools.start_ticket("Laura", on_behalf_of="Zenaida", tool_context=owner)
    assert answer["error"] == "ambiguous_specialist"
    assert set(answer["options"]) == {"Zenaida Prueba", "Zenaida Segunda"}


def test_a_name_the_salon_does_not_have_is_refused(owner):
    answer = tools.start_ticket("Laura", on_behalf_of="Nadie", tool_context=owner)
    assert answer["error"] == "unknown_specialist"


def test_an_owner_cannot_be_named_as_having_done_the_work(owner, make_specialist):
    """She is not in the roster a name resolves against, so there is nothing to book to her."""
    make_specialist(full_name="Ubaldina Dueña", roles=("owner",))
    answer = tools.start_ticket("Laura", on_behalf_of="Ubaldina", tool_context=owner)
    assert answer["error"] == "unknown_specialist"


def test_a_clash_names_the_client_rather_than_guessing(owner, ctx, make_specialist):
    """Her open ticket may be for a different client, and adding to it silently would rewrite
    someone else's sale."""
    her = make_specialist("nails", full_name="Zenaida Prueba")
    tools.start_ticket("Carmen", tool_context=ctx(her))
    answer = tools.start_ticket("Laura", on_behalf_of="Zenaida", tool_context=owner)
    assert answer["error"] == "ticket_already_open"
    assert answer["client_name"] == "Carmen"
    assert answer["specialist"] == "Zenaida Prueba"


def test_the_days_figures_land_on_her_and_not_on_the_owner(owner, ctx, make_specialist):
    her = make_specialist("nails", full_name="Zenaida Prueba")
    tools.start_ticket("Laura", on_behalf_of="Zenaida", tool_context=owner)
    tools.add_service("manicura normal", 1, on_behalf_of="Zenaida", tool_context=owner)
    tools.record_payment("efectivo", "300", "0", on_behalf_of="Zenaida", tool_context=owner)

    about_her = tools.my_day(on_behalf_of="Zenaida", tool_context=owner)["summary"]
    hers = tools.my_day(tool_context=ctx(her))["summary"]
    assert "Servicios: RD$300.00" in about_her and "Servicios: RD$300.00" in hers
    assert "Comisión (40%): RD$120.00" in about_her
    assert "Tu comisión (40%): RD$120.00" in hers


def test_an_owner_asking_about_somebody_is_told_about_her_rather_than_addressed_as_her(
    owner, make_specialist
):
    """She named somebody, so the day is a report. Handed to her in the second person it greets
    her by that woman's name and calls that commission hers."""
    make_specialist("nails", full_name="Zenaida Prueba")
    tools.start_ticket("Laura", on_behalf_of="Zenaida", tool_context=owner)
    tools.add_service("manicura normal", 1, on_behalf_of="Zenaida", tool_context=owner)
    tools.record_payment("efectivo", "300", "0", on_behalf_of="Zenaida", tool_context=owner)

    about_her = tools.my_day(on_behalf_of="Zenaida", tool_context=owner)["summary"]
    assert "Así cerró el día de Zenaida" in about_her
    assert "Total para ella hoy: RD$120.00" in about_her
    for said_to_the_reader in ("Hola ", "tu día", "Tu comisión", "te las", "para ti"):
        assert said_to_the_reader not in about_her, said_to_the_reader


def test_an_owner_who_also_works_reads_her_own_day_addressed_to_her(ctx, make_specialist):
    """Naming herself is not naming somebody else. The comparison is on the resolved id, so the
    spelling she used cannot decide which voice she gets."""
    her = make_specialist("wax", full_name="Zenaida Dueña", roles=("owner",))
    assert "Hola Zenaida" in tools.my_day(on_behalf_of="Zenaida", tool_context=ctx(her))["summary"]


def test_a_debt_recorded_by_the_owner_is_owed_by_the_specialist(owner, ctx, make_specialist):
    her = make_specialist("nails", full_name="Zenaida Prueba")
    answer = tools.buy_product("agua", 1, on_behalf_of="Zenaida", tool_context=owner)
    assert answer["balance"] == "RD$15.00"
    assert answer["owed_by"] == "Zenaida Prueba"
    assert "• Consumo: RD$15.00" in tools.my_day(tool_context=ctx(her))["summary"]


# --- [10] A client who leaves owing -------------------------------------------------------------
# The ticket cannot stay open: one open ticket per specialist is what makes "my current ticket"
# mean anything, so a client who has not finished paying would otherwise stop the specialist
# serving anybody else.


def _ticket_for(context, client: str = "Laura") -> None:
    tools.start_ticket(client, tool_context=context)
    tools.add_service("manicura normal", 1, tool_context=context)


def test_a_client_can_leave_owing_and_the_specialist_carries_on(working, conn):
    """THE property. Closing with a balance is what frees her for the next client."""
    context, who = working
    _ticket_for(context)
    tools.record_payment("efectivo", "100", "0", tool_context=context)
    answer = tools.close_ticket_with_debt(tool_context=context)

    assert answer["owes"] == "RD$200.00"
    assert "QUEDA DEBIENDO: RD$200.00" in answer["receipt"]
    assert queries.open_sale(conn, who["id"]) is None, "she can open the next ticket"
    row = queries.fetchone(conn, "SELECT status FROM sales ORDER BY id DESC LIMIT 1")
    assert row["status"] == "partial"


def test_what_she_owes_meets_her_at_the_next_ticket(working):
    """Recording a balance nobody is ever shown would be bookkeeping for its own sake. The moment
    it is useful is the one moment somebody is standing in front of her."""
    context, _ = working
    _ticket_for(context, "Carmen")
    tools.close_ticket_with_debt(tool_context=context)
    assert tools.start_ticket("Carmen", tool_context=context)["owed_from_before"] == "RD$300.00"


def test_the_balance_is_on_the_ticket_whoever_reads_it_next(working):
    """Announced once at the open it has scrolled away by the time anybody could ask for it. The
    person charging is the one who needs it, and she is not always the one who opened it."""
    context, _ = working
    _ticket_for(context, "Carmen")
    tools.close_ticket_with_debt(tool_context=context)

    opened = tools.start_ticket("Carmen", tool_context=context)
    assert opened["owed_from_before"] == "RD$300.00"
    ticket = tools.add_service("manicura normal", 1, tool_context=context)["ticket"]
    assert "DEUDA ANTERIOR: RD$300.00 (aparte de este total)" in ticket
    assert "Total: RD$300.00" in ticket, "the debt is beside the total, never inside it"
    assert "DEUDA ANTERIOR: RD$300.00" in tools.show_ticket(tool_context=context)["ticket"]


def test_settling_it_mid_visit_takes_it_off_the_ticket(working):
    """Read on every render rather than carried from the open, so paying it is visible at once."""
    context, _ = working
    _ticket_for(context, "Carmen")
    tools.close_ticket_with_debt(tool_context=context)
    tools.start_ticket("Carmen", tool_context=context)
    tools.add_service("manicura normal", 1, tool_context=context)

    tools.settle_client_debt("Carmen", "300", "efectivo", tool_context=context)
    assert "DEUDA" not in tools.show_ticket(tool_context=context)["ticket"]


def test_a_client_who_owes_nothing_is_not_told_about_it(working):
    context, _ = working
    assert "owed_from_before" not in tools.start_ticket("Laura", tool_context=context)


def test_one_client_however_she_is_spelled(working):
    """Matched folded, so an accent or a capital does not open a second balance for one person."""
    context, _ = working
    _ticket_for(context, "MARÍA")
    tools.close_ticket_with_debt(tool_context=context)
    assert tools.start_ticket("maria", tool_context=context)["owed_from_before"] == "RD$300.00"


def test_a_settled_ticket_has_nothing_to_leave_owing(working):
    context, _ = working
    _ticket_for(context)
    tools.record_payment("efectivo", "300", "0", tool_context=context)
    assert tools.close_ticket_with_debt(tool_context=context)["error"] == "no_open_ticket"


def test_paying_it_off_later_clears_the_balance(working):
    context, _ = working
    _ticket_for(context, "Carmen")
    tools.close_ticket_with_debt(tool_context=context)

    part = tools.settle_client_debt("Carmen", "100", "efectivo", tool_context=context)
    assert part["still_owes"] == "RD$200.00"
    rest = tools.settle_client_debt("Carmen", "200", "banreservas", tool_context=context)
    assert rest["still_owes"] == "RD$0.00"
    assert "owed_from_before" not in tools.start_ticket("Carmen", tool_context=context)


def test_a_client_who_left_owing_still_earns_the_whole_commission(working):
    """What she earns is what she did, not what the salon collected — §7. The figure is the whole
    ticket, and the RD$100.00 that did reach the drawer has nothing to do with it."""
    context, _ = working
    _ticket_for(context, "Carmen")
    tools.record_payment("efectivo", "100", "0", tool_context=context)
    tools.close_ticket_with_debt(tool_context=context)

    summary = tools.my_day(tool_context=context)["summary"]
    assert "Servicios: RD$300.00" in summary
    assert "Tu comisión (40%): RD$120.00" in summary
    accrued = next(line for line in summary.splitlines() if line.startswith("Acumulado"))
    assert accrued.endswith("RD$120.00"), "it accrues toward pay-day like any other sale"


def test_settling_the_balance_later_does_not_pay_the_commission_twice(working):
    """The balance is the client's debt rather than a second sale: the day she worked already
    counted the whole ticket, and settling only ever reaches `client_ledger`."""
    context, _ = working
    _ticket_for(context, "Carmen")
    tools.close_ticket_with_debt(tool_context=context)
    before = tools.my_day(tool_context=context)["summary"]

    tools.settle_client_debt("Carmen", "300", "efectivo", tool_context=context)
    assert tools.my_day(tool_context=context)["summary"] == before


def test_more_than_she_owes_is_refused_rather_than_held(working):
    """The salon has no way to hold money FOR a client, so an overpayment here would go missing."""
    context, _ = working
    _ticket_for(context, "Carmen")
    tools.close_ticket_with_debt(tool_context=context)
    answer = tools.settle_client_debt("Carmen", "500", "efectivo", tool_context=context)
    assert answer["error"] == "more_than_owed" and answer["balance"] == "RD$300.00"


def test_settling_for_somebody_who_owes_nothing_is_refused(working):
    context, _ = working
    assert tools.settle_client_debt("Nadie", "100", "efectivo", tool_context=context)["error"] == (
        "unknown_client"
    )


# --- [11] The register, and money lent out of it -------------------------------------------------


def test_what_the_register_should_hold_is_every_way_money_moved(owner, working, conn):
    """The load-bearing arithmetic. A ticket paid, a tip left in the drawer, an old debt settled
    into a bank, and cash lent out — each moves a different account in a different direction."""
    context, her = working
    tools.start_ticket("Laura", tool_context=context)
    tools.add_service("manicura normal", 1, tool_context=context)
    tools.record_payment("efectivo", "300", "50", tool_context=context)

    tools.start_ticket("Carmen", tool_context=context)
    tools.add_service("manicura normal", 1, tool_context=context)
    tools.close_ticket_with_debt(tool_context=context)
    tools.settle_client_debt("Carmen", "100", "banreservas", tool_context=context)

    tools.record_loan(her["full_name"], "200", "efectivo", tool_context=owner)

    expected = queries.expected_register(conn, tools._today())
    # 300 taken + 50 tipped - 200 lent = 150 in the drawer; the 100 went to Banreservas.
    assert expected["cash"] == Decimal("150.00")
    assert expected["banreservas"] == Decimal("100.00")
    assert expected["bhd"] == Decimal("0.00")


def test_the_change_is_not_subtracted_twice(owner, working, conn):
    """`amount` is what the ticket received, so a note and its change already net there. A reader
    who also subtracted `change_given` would count it twice."""
    context, _ = working
    tools.start_ticket("Laura", tool_context=context)
    tools.add_service("manicura normal", 1, tool_context=context)
    tools.record_payment("efectivo", "500", "0", tool_context=context)  # RD$200 back
    assert queries.expected_register(conn, tools._today())["cash"] == Decimal("300.00")


def test_closing_the_register_records_both_figures_and_neither_difference(owner, working, conn):
    context, _ = working
    tools.start_ticket("Laura", tool_context=context)
    tools.add_service("manicura normal", 1, tool_context=context)
    tools.record_payment("efectivo", "300", "0", tool_context=context)

    answer = tools.close_register("290", "0", "0", tool_context=owner)
    assert answer["closed"] is True
    assert answer["expected"]["cash"] == "RD$300.00"
    assert answer["counted"]["cash"] == "RD$290.00"
    assert answer["variance"]["cash"] == "-RD$10.00"
    row = queries.fetchone(conn, "SELECT * FROM register_closes ORDER BY id DESC LIMIT 1")
    assert (row["counted_cash"], row["expected_cash"]) == (Decimal("290.00"), Decimal("300.00"))


def test_an_open_ticket_stops_the_register_being_closed(owner, working):
    """Money not yet taken would be measured against an expectation that is not finished."""
    context, her = working
    tools.start_ticket("Laura", tool_context=context)
    tools.add_service("manicura normal", 1, tool_context=context)
    answer = tools.close_register("0", "0", "0", tool_context=owner)
    assert answer["error"] == "tickets_open"
    assert answer["open"] == [f"{her['full_name']} — Laura"]


def test_the_register_closes_once(owner):
    assert tools.close_register("0", "0", "0", tool_context=owner)["closed"] is True
    assert tools.close_register("0", "0", "0", tool_context=owner)["error"] == "already_closed"


def test_the_close_says_what_to_hand_out_in_tips(owner, working):
    """Tips sit in the drawer that was just counted and are paid out of it, so they are reported
    beside the close rather than taken off it."""
    context, her = working
    tools.start_ticket("Laura", tool_context=context)
    tools.add_service("manicura normal", 1, tool_context=context)
    tools.record_payment("efectivo", "300", "80", tool_context=context)
    answer = tools.close_register("380", "0", "0", tool_context=owner)
    assert answer["tips_to_pay"] == [f"{her['full_name']} — RD$80.00"]
    assert answer["variance"]["cash"] == "RD$0.00"


def test_a_loan_and_a_purchase_are_owed_separately(owner, working, conn):
    """Owing for a drink and owing cash are not the same thing to be told you owe."""
    context, her = working
    tools.buy_product("agua", tool_context=context)
    tools.record_loan(her["full_name"], "500", "efectivo", tool_context=owner)

    balances = queries.debt_balances(conn, her["id"])
    assert balances == {
        "purchase": Decimal("15.00"),
        "loan": Decimal("500.00"),
        "total": Decimal("515.00"),
    }


def test_paying_one_balance_leaves_the_other_alone(owner, working, conn):
    context, her = working
    tools.buy_product("agua", tool_context=context)
    tools.record_loan(her["full_name"], "500", "efectivo", tool_context=owner)
    tools.settle_debt("500", "préstamo", "efectivo", tool_context=context)

    balances = queries.debt_balances(conn, her["id"])
    assert balances["loan"] == Decimal("0.00")
    assert balances["purchase"] == Decimal("15.00"), "the water is still owed"


def test_a_payment_must_say_which_balance_it_pays(working):
    context, _ = working
    tools.buy_product("agua", tool_context=context)
    assert tools.settle_debt("15", "lo que sea", "efectivo", tool_context=context)["error"] == (
        "bad_owes"
    )


def test_only_an_owner_reaches_the_register(working):
    """The tool body refuses even though the guard already did."""
    context, _ = working
    assert tools.close_register("0", "0", "0", tool_context=context)["error"] == "owner_only"
    assert tools.salon_day(tool_context=context)["error"] == "owner_only"


# --- [12] Which client she is ---------------------------------------------------------------
# Two people called María were one row, one balance and one history. The number is the half of
# an identity the salon can actually ask for, and these hold what it buys.

_A = "8095551111"
_B = "8295552222"


def _billed(context, client: str, phone: str = "", **kw) -> dict:
    """Open a ticket for `client` and put one service on it. Answers the ticket call."""
    opened = tools.start_ticket(client, client_phone=phone, tool_context=context, **kw)
    if "error" in opened:
        return opened
    return tools.add_service("manicura normal", 1, tool_context=context)


def test_a_client_the_salon_does_not_know_needs_a_number(working):
    """Registering her under a name alone is what put two people on one balance."""
    context, _ = working
    answer = tools.start_ticket("Ingrid", tool_context=context)
    assert answer["error"] == "client_phone_required"


def test_the_number_on_the_second_call_opens_the_ticket(working, conn):
    """The question is answered by the re-call, like an ambiguous specialist. Nothing is held
    between the turns and `session.py` keeps its two facts."""
    context, _ = working
    tools.start_ticket("Ingrid", tool_context=context)
    assert tools.start_ticket("Ingrid", client_phone="809-555-1111", tool_context=context)["opened"]
    row = queries.fetchone(conn, "SELECT phone FROM clients WHERE folded = 'ingrid'")
    assert row["phone"] == _A, "stored as digits, however she wrote it"


def test_a_client_the_salon_knows_is_never_asked_again(working):
    """ "Always" is about a client it does not know. Asking a regular every visit is how a rule
    stops being obeyed."""
    context, _ = working
    tools.start_ticket("Ingrid", client_phone=_A, tool_context=context)
    tools.void_ticket(tool_context=context)
    assert tools.start_ticket("Ingrid", tool_context=context)["opened"]


def test_two_clients_who_share_a_name_keep_separate_balances(working):
    """THE property. One leaves owing; the other is not told about a debt that is not hers."""
    context, _ = working
    _billed(context, "Ingrid", _A)
    tools.close_ticket_with_debt(tool_context=context)

    second = tools.start_ticket("Ingrid", client_phone=_B, is_new_client=True, tool_context=context)
    assert second["opened"]
    assert "owed_from_before" not in second
    ticket = tools.add_service("manicura normal", 1, tool_context=context)["ticket"]
    assert "DEUDA ANTERIOR" not in ticket


def test_the_first_of_them_still_owes_it(working):
    """The other half: separating them must not lose the debt it separated."""
    context, _ = working
    _billed(context, "Ingrid", _A)
    tools.close_ticket_with_debt(tool_context=context)
    tools.start_ticket("Ingrid", client_phone=_B, is_new_client=True, tool_context=context)
    tools.void_ticket(tool_context=context)

    hers = tools.start_ticket("Ingrid", client_phone=_A, tool_context=context)
    assert hers["owed_from_before"] == "RD$300.00"


def test_a_second_client_of_that_name_is_confirmed_rather_than_assumed(working):
    """A mistyped digit and a different person are the same input, so a person is asked. The cost
    is one visible extra row instead of a silently merged balance."""
    context, _ = working
    tools.start_ticket("Ingrid", client_phone=_A, tool_context=context)
    tools.void_ticket(tool_context=context)
    answer = tools.start_ticket("Ingrid", client_phone=_B, tool_context=context)
    assert answer["error"] == "another_client_with_that_name"


def test_the_same_name_and_number_is_one_client(working, conn):
    """Two rows for one person would be two balances for one person."""
    context, _ = working
    tools.start_ticket("Ingrid", client_phone=_A, tool_context=context)
    tools.void_ticket(tool_context=context)
    tools.start_ticket("Ingrid", client_phone="1-809-555-1111", tool_context=context)
    row = queries.fetchone(conn, "SELECT COUNT(*) AS n FROM clients WHERE folded = 'ingrid'")
    assert row["n"] == 1


def test_a_mother_and_daughter_on_one_number_are_two_clients(working, conn):
    """The pair is the identity, and a shared phone is ordinary."""
    context, _ = working
    tools.start_ticket("Ingrid", client_phone=_A, tool_context=context)
    tools.void_ticket(tool_context=context)
    assert tools.start_ticket("Sonia", client_phone=_A, tool_context=context)["opened"]


def test_a_number_the_salon_cannot_read_writes_nothing(working, conn):
    """And does NOT fall through to matching on the name alone, which is how a typo opens a
    ticket on the wrong woman."""
    context, _ = working
    answer = tools.start_ticket("Ingrid", client_phone="80955511", tool_context=context)
    assert answer["error"] == "bad_phone"
    row = queries.fetchone(conn, "SELECT COUNT(*) AS n FROM clients WHERE folded = 'ingrid'")
    assert row["n"] == 0


# --- [13] A client who gave no number ---------------------------------------------------------
# She is charged and her work counts. What she cannot be is fiada: her row is never matched by
# name again, so a balance on it is one nothing could ever collect.


def test_she_can_still_be_served(working):
    """Refusing the ticket would cost the specialist the commission on work she actually did."""
    context, _ = working
    assert tools.start_ticket("Ingrid", walk_in=True, tool_context=context)["opened"]


def test_the_ticket_says_so_before_anybody_tries_to_fiarle(working):
    """Sprung at the close, the refusal arrives with the client already walking out."""
    context, _ = working
    ticket = _billed(context, "Ingrid", walk_in=True)["ticket"]
    assert "(de paso)" in ticket
    assert "Sin teléfono" in ticket


def test_she_cannot_leave_owing(working):
    """A debt on a row nothing can find again is uncollectable by construction."""
    context, _ = working
    _billed(context, "Ingrid", walk_in=True)
    assert tools.close_ticket_with_debt(tool_context=context)["error"] == "no_credit_walk_in"


def test_she_is_never_found_by_name_again(working):
    """`clients_named` filters her out, which is the whole mechanism — the truth about what the
    salon knows rather than a limitation of the query."""
    context, _ = working
    tools.start_ticket("Ingrid", walk_in=True, tool_context=context)
    tools.void_ticket(tool_context=context)
    assert tools.start_ticket("Ingrid", tool_context=context)["error"] == "client_phone_required"


# --- [14] Settling for a client who shares a name ---------------------------------------------


def test_settling_for_a_shared_name_is_refused_rather_than_applied(working):
    """NOT the one who happens to owe. It looks like the only reading that does anything, and it
    credits money to a woman who may not have handed it over."""
    context, _ = working
    _billed(context, "Ingrid", _A)
    tools.close_ticket_with_debt(tool_context=context)
    tools.start_ticket("Ingrid", client_phone=_B, is_new_client=True, tool_context=context)
    tools.void_ticket(tool_context=context)

    answer = tools.settle_client_debt("Ingrid", "100", "efectivo", tool_context=context)
    assert answer["error"] == "ambiguous_client"


def test_the_number_settles_the_right_ones_balance(working):
    context, _ = working
    _billed(context, "Ingrid", _A)
    tools.close_ticket_with_debt(tool_context=context)
    tools.start_ticket("Ingrid", client_phone=_B, is_new_client=True, tool_context=context)
    tools.void_ticket(tool_context=context)

    answer = tools.settle_client_debt(
        "Ingrid", "300", "efectivo", client_phone=_A, tool_context=context
    )
    assert answer["still_owes"] == "RD$0.00"


def test_settling_never_registers_anybody(working, conn):
    """Answering a typo with a new client is how money lands on a person the salon never saw."""
    context, _ = working
    answer = tools.settle_client_debt("Ingrid", "100", "efectivo", tool_context=context)
    assert answer["error"] == "unknown_client"
    row = queries.fetchone(conn, "SELECT COUNT(*) AS n FROM clients WHERE folded = 'ingrid'")
    assert row["n"] == 0


# --- [15] What one client has had done ---------------------------------------------------------
# The report is only about ONE woman because [12] made her one row. Built on the old identity it
# would have shown two people's visits as one history, to an owner, formatted authoritatively.


def _history(owner_ctx, client: str = "Ingrid", **kw) -> str:
    return tools.client_history(client, tool_context=owner_ctx, **kw)["summary"]


def test_her_visits_come_back_newest_first(working, owner):
    """The order she would tell it in."""
    context, _ = working
    _billed(context, "Ingrid", _A)
    tools.record_payment("efectivo", "300", "0", tool_context=context)
    tools.start_ticket("Ingrid", tool_context=context)
    tools.add_service("pedicura normal", 1, tool_context=context)
    tools.record_payment("efectivo", "400", "0", tool_context=context)

    out = _history(owner)
    assert out.index("Pedicura") < out.index("Manicura"), "the later visit is listed first"
    assert "2 visitas" in out


def test_a_visit_shows_the_price_that_was_actually_charged(working, owner):
    """Read off the sale rather than re-derived from the catalog: this service is RD$300.00 for a
    woman and RD$400.00 for a man, and the ticket said which (§4)."""
    context, _ = working
    tools.start_ticket("Ingrid", client_phone=_A, client_gender="hombre", tool_context=context)
    tools.add_service("manicura normal", 1, tool_context=context)
    tools.record_payment("efectivo", "400", "0", tool_context=context)
    assert "RD$400.00" in _history(owner)


def test_a_ticket_paid_in_three_parts_is_one_visit(working, owner):
    """THE fan-out, on the payments side. A join to `sale_payments` would list this sale three
    times and treble what it came to, and the figure would still look like money."""
    context, _ = working
    _billed(context, "Ingrid", _A)
    tools.record_payment("efectivo", "100", "0", tool_context=context)
    tools.record_payment("banreservas", "100", "0", tool_context=context)
    tools.record_payment("bhd", "100", "0", tool_context=context)

    out = _history(owner)
    assert out.count("• ") == 1
    assert "1 visita" in out
    assert "Total facturado: RD$300.00" in out


def test_a_ticket_with_two_services_is_one_visit_at_its_whole_total(working, owner):
    """The fan-out on the lines side, and both services are named on the one line."""
    context, _ = working
    _billed(context, "Ingrid", _A)
    tools.add_service("pedicura normal", 1, tool_context=context)
    tools.record_payment("efectivo", "700", "0", tool_context=context)

    out = _history(owner)
    assert out.count("• ") == 1
    assert "Manicura + pintura normal, Pedicura + pintura normal" in out
    assert "RD$700.00" in out


def test_a_voided_ticket_is_not_a_visit(working, owner):
    """`WORKED_STATUSES` applies here as everywhere: it never happened."""
    context, _ = working
    _billed(context, "Ingrid", _A)
    tools.void_ticket(tool_context=context)
    assert _history(owner) == "Ingrid todavía no tiene visitas cobradas."


def test_settling_later_moves_what_she_owes_now_and_not_the_visit(working, owner):
    """The two figures, end to end. The visit records what she left owing THAT day and cannot be
    rewritten by a payment made weeks after it."""
    context, _ = working
    _billed(context, "Ingrid", _A)
    tools.close_ticket_with_debt(tool_context=context)
    before = _history(owner)
    assert "(quedó debiendo RD$300.00)" in before
    assert "Debe ahora: RD$300.00" in before

    tools.settle_client_debt("Ingrid", "300", "efectivo", client_phone=_A, tool_context=context)
    after = _history(owner)
    assert "(quedó debiendo RD$300.00)" in after, "what happened that day did not change"
    assert "Debe ahora" not in after


def test_a_client_the_salon_never_saw_is_refused_rather_than_invented(owner, conn):
    context = owner
    assert tools.client_history("Ingrid", tool_context=context)["error"] == "unknown_client"
    row = queries.fetchone(conn, "SELECT COUNT(*) AS n FROM clients WHERE folded = 'ingrid'")
    assert row["n"] == 0


def test_a_history_for_a_shared_name_asks_which_one(working, owner):
    """A history of the wrong woman is worse than none: it looks like a fact, and nobody at the
    till is there to contest it."""
    context, _ = working
    _billed(context, "Ingrid", _A)
    tools.record_payment("efectivo", "300", "0", tool_context=context)
    tools.start_ticket("Ingrid", client_phone=_B, is_new_client=True, tool_context=context)
    tools.void_ticket(tool_context=context)
    assert tools.client_history("Ingrid", tool_context=owner)["error"] == "ambiguous_client"


def test_a_clients_history_is_an_owners_alone(working):
    """The body refuses even though the guard already did."""
    context, _ = working
    assert tools.client_history("Ingrid", tool_context=context)["error"] == "owner_only"


def test_the_guard_knows_the_client_report_is_an_owners():
    """Named as a literal rather than parametrized over the set. Every owner-only test reads that
    set, so a tool MISSING from it is invisible to all of them — which is this tool's failure
    shape, not a hypothetical."""
    assert "client_history" in tools.OWNER_TOOL_NAMES


# --- [16] Who comes, who spends, and who stopped ----------------------------------------------

_C = "8495553333"
_D = "8095554444"


def _backdate(conn, client_folded: str, days_ago: int) -> None:
    """Move every charged sale of that client back. The register tests already move a business
    date this way; the sentinel cleanup cascades them off however the case ends."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sales SET business_date = CURRENT_DATE - %(n)s * INTERVAL '1 day' "
            "WHERE client_id = (SELECT id FROM clients WHERE folded = %(f)s)",
            {"n": days_ago, "f": client_folded},
        )


def _sold(context, client: str, phone: str, service: str = "manicura normal") -> None:
    tools.start_ticket(client, client_phone=phone, tool_context=context)
    tools.add_service(service, 1, tool_context=context)
    tools.record_payment("efectivo", "10000", "0", extra="vuelto", tool_context=context)


def test_who_comes_most_counts_visits_and_who_spends_most_counts_pesos(working, owner):
    """Two readings of the same rows, and a ranking that mixed them would be unreadable."""
    context, _ = working
    _sold(context, "Ingrid", _A)
    _sold(context, "Ingrid", _A)
    _sold(context, "Sonia", _C, "pedicura vip")

    out = tools.salon_clients(tool_context=owner)["summary"]
    visits = out[out.index("Las que más vienen:") : out.index("Las que más gastan:")]
    spend = out[out.index("Las que más gastan:") : out.index("Lo que más se hace:")]
    assert visits.index("Ingrid") < visits.index("Sonia"), "two visits beat one"
    assert spend.index("Sonia") < spend.index("Ingrid"), "one bigger ticket beats two small ones"


def test_what_sells_most_counts_a_quantity_of_two_as_two(working, owner):
    """`SUM(quantity)`, not `COUNT(*)`: two pedicures on one ticket were sold twice."""
    context, _ = working
    tools.start_ticket("Ingrid", client_phone=_A, tool_context=context)
    tools.add_service("pedicura normal", 2, tool_context=context)
    tools.record_payment("efectivo", "10000", "0", extra="vuelto", tool_context=context)
    assert (
        "Pedicura + pintura normal — 2 veces" in tools.salon_clients(tool_context=owner)["summary"]
    )


def test_a_sale_outside_the_window_is_absent(working, owner, conn):
    context, _ = working
    _sold(context, "Ingrid", _A)
    _backdate(conn, "ingrid", 200)
    out = tools.salon_clients(days=30, tool_context=owner)["summary"]
    assert "Ingrid" not in out


def test_a_nonsense_window_is_clamped_rather_than_refused(working, owner):
    """A window is not money. A bad value should still answer, and the message says which window
    it read — so a default the owner did not choose is visible."""
    context, _ = working
    _sold(context, "Ingrid", _A)
    for days in (0, -5, 99999):
        answer = tools.salon_clients(days=days, tool_context=owner)
        assert "error" not in answer, days
        assert "Del " in answer["summary"]


def test_somebody_who_came_once_is_not_somebody_who_stopped_coming(working, owner, conn):
    """One visit is a walk-in who never became a client, and reporting her as lapsed is the noise
    that teaches people to skip the list."""
    context, _ = working
    _sold(context, "Ingrid", _A)
    _backdate(conn, "ingrid", 120)
    assert "Ingrid" not in tools.lapsed_clients(tool_context=owner)["summary"]


def test_a_regular_who_stopped_is_reported_with_when_and_how_often(working, owner, conn):
    context, _ = working
    _sold(context, "Ingrid", _A)
    _sold(context, "Ingrid", _A)
    _backdate(conn, "ingrid", 120)
    out = tools.lapsed_clients(tool_context=owner)["summary"]
    assert "Ingrid" in out and "2 visitas" in out and "tel 809-555-1111" in out


def test_a_client_seen_recently_is_not_lapsed(working, owner):
    context, _ = working
    _sold(context, "Ingrid", _A)
    _sold(context, "Ingrid", _A)
    assert "Ingrid" not in tools.lapsed_clients(tool_context=owner)["summary"]


def test_an_old_balance_is_listed_even_when_she_still_comes(working, owner, conn):
    """The halves are independent: a regular who owes is a collection problem, not a retention
    one, and folding them into one list would hide her in it."""
    context, _ = working
    _billed(context, "Sonia", _C)
    tools.close_ticket_with_debt(tool_context=context)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE client_ledger SET business_date = CURRENT_DATE - 200 * INTERVAL '1 day' "
            "WHERE client_id = (SELECT id FROM clients WHERE folded = 'sonia')"
        )
    out = tools.lapsed_clients(tool_context=owner)["summary"]
    owing = out[out.index("Con saldo viejo sin mover:") :]
    assert "Sonia — RD$300.00" in owing


def test_a_settled_balance_drops_off_the_list(working, owner, conn):
    """The same expression `client_balance` uses, so the report and the ticket cannot disagree."""
    context, _ = working
    _billed(context, "Sonia", _C)
    tools.close_ticket_with_debt(tool_context=context)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE client_ledger SET business_date = CURRENT_DATE - 200 * INTERVAL '1 day' "
            "WHERE client_id = (SELECT id FROM clients WHERE folded = 'sonia')"
        )
    tools.settle_client_debt("Sonia", "300", "efectivo", client_phone=_C, tool_context=context)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE client_ledger SET business_date = CURRENT_DATE - 200 * INTERVAL '1 day' "
            "WHERE client_id = (SELECT id FROM clients WHERE folded = 'sonia')"
        )
    assert "Sonia" not in tools.lapsed_clients(tool_context=owner)["summary"]


def test_both_client_reports_are_an_owners_alone(working):
    """The bodies refuse even though the guard already did."""
    context, _ = working
    assert tools.salon_clients(tool_context=context)["error"] == "owner_only"
    assert tools.lapsed_clients(tool_context=context)["error"] == "owner_only"


def test_the_guard_knows_both_client_reports_are_an_owners():
    """Named as literals. Every owner-only test reads the set, so a tool missing from it is
    invisible to all of them."""
    assert {"salon_clients", "lapsed_clients"} <= tools.OWNER_TOOL_NAMES


# --- [17] When her number changes --------------------------------------------------------------
# The number is half an identity, so changing it is the one write that says somebody is somebody
# else. What it must never do is move a balance.

_NEW = "8095559999"


def test_her_number_changes_and_the_new_one_finds_her(working):
    context, _ = working
    tools.start_ticket("Ingrid", client_phone=_A, tool_context=context)
    assert tools.set_client_phone(_NEW, tool_context=context)["changed"]
    tools.void_ticket(tool_context=context)
    assert tools.start_ticket("Ingrid", client_phone=_NEW, tool_context=context)["opened"]


def test_the_old_number_stops_being_hers(working):
    """A correction that left the old one working would be an addition, and the salon would have
    two ways to reach one woman and no way to tell which is current."""
    context, _ = working
    tools.start_ticket("Ingrid", client_phone=_A, tool_context=context)
    tools.set_client_phone(_NEW, tool_context=context)
    tools.void_ticket(tool_context=context)
    answer = tools.start_ticket("Ingrid", client_phone=_A, tool_context=context)
    assert answer["error"] == "another_client_with_that_name"


def test_what_she_owes_follows_her_and_not_the_number(working):
    """THE property. She is the same woman: same row, same balance, same history."""
    context, _ = working
    _billed(context, "Ingrid", _A)
    tools.close_ticket_with_debt(tool_context=context)
    tools.start_ticket("Ingrid", client_phone=_A, tool_context=context)
    assert tools.set_client_phone(_NEW, tool_context=context)["changed"]
    tools.void_ticket(tool_context=context)

    assert tools.start_ticket("Ingrid", tool_context=context)["owed_from_before"] == "RD$300.00"


def test_a_client_of_that_name_who_holds_it_already_refuses_the_change(working):
    """Two balances becoming one is a merge, and nobody asked for one."""
    context, _ = working
    tools.start_ticket("Ingrid", client_phone=_A, tool_context=context)
    tools.void_ticket(tool_context=context)
    tools.start_ticket("Ingrid", client_phone=_B, is_new_client=True, tool_context=context)
    assert tools.set_client_phone(_A, tool_context=context)["error"] == "phone_taken"


def test_a_number_the_salon_cannot_read_changes_nothing(working):
    context, _ = working
    tools.start_ticket("Ingrid", client_phone=_A, tool_context=context)
    assert tools.set_client_phone("80955", tool_context=context)["error"] == "bad_phone"
    tools.void_ticket(tool_context=context)
    assert tools.start_ticket("Ingrid", client_phone=_A, tool_context=context)["opened"]


def test_naming_nobody_with_no_open_ticket_is_refused(working):
    context, _ = working
    assert tools.set_client_phone(_NEW, tool_context=context)["error"] == "no_open_ticket"


def test_a_name_two_clients_answer_to_asks_which(working):
    context, _ = working
    tools.start_ticket("Ingrid", client_phone=_A, tool_context=context)
    tools.void_ticket(tool_context=context)
    tools.start_ticket("Ingrid", client_phone=_B, is_new_client=True, tool_context=context)
    tools.void_ticket(tool_context=context)
    answer = tools.set_client_phone(_NEW, client="Ingrid", tool_context=context)
    assert answer["error"] == "ambiguous_client"


def test_the_current_number_says_which_of_them_changed(working):
    context, _ = working
    tools.start_ticket("Ingrid", client_phone=_A, tool_context=context)
    tools.void_ticket(tool_context=context)
    tools.start_ticket("Ingrid", client_phone=_B, is_new_client=True, tool_context=context)
    tools.void_ticket(tool_context=context)
    assert tools.set_client_phone(_NEW, client="Ingrid", client_phone=_B, tool_context=context)[
        "changed"
    ]
    assert tools.start_ticket("Ingrid", client_phone=_A, tool_context=context)["opened"]


# --- [18] A client of passage who changes her mind ---------------------------------------------
# Her open ticket is the only way to reach her: she is not findable by name, deliberately. So the
# ticket she is standing at is the whole window, and it closes when it closes.


def test_she_can_give_a_number_while_her_ticket_is_open(working):
    context, _ = working
    _billed(context, "Ingrid", walk_in=True)
    assert tools.set_client_phone(_A, tool_context=context)["changed"]


def test_the_ticket_stops_calling_her_de_paso(working):
    """Read on every render rather than carried from the open, so it lands at once — and she is
    charged in front of somebody who can now fiarle."""
    context, _ = working
    _billed(context, "Ingrid", walk_in=True)
    tools.set_client_phone(_A, tool_context=context)
    ticket = tools.show_ticket(tool_context=context)["ticket"]
    assert "de paso" not in ticket and "Sin teléfono" not in ticket


def test_she_can_be_fiada_from_then_on(working):
    """The refusal was never about her: it was about nothing being able to find her again."""
    context, _ = working
    _billed(context, "Ingrid", walk_in=True)
    tools.set_client_phone(_A, tool_context=context)
    assert tools.close_ticket_with_debt(tool_context=context)["owes"] == "RD$300.00"


def test_she_is_findable_by_name_from_then_on(working):
    context, _ = working
    _billed(context, "Ingrid", walk_in=True)
    tools.set_client_phone(_A, tool_context=context)
    tools.void_ticket(tool_context=context)
    assert tools.start_ticket("Ingrid", tool_context=context)["opened"]


def test_once_the_ticket_closes_there_is_no_way_back_to_her(working):
    """Said plainly rather than discovered: the window is the ticket, and a name cannot reopen
    it. That is the cost of serving her at all, and it is the honest one."""
    context, _ = working
    _billed(context, "Ingrid", walk_in=True)
    tools.record_payment("efectivo", "300", "0", tool_context=context)
    assert tools.set_client_phone(_A, client="Ingrid", tool_context=context)["error"] == (
        "unknown_client"
    )
