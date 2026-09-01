# Salón Aziza — assistant definition

The owner of what this service does and why it is shaped the way it is. Comments in the code cite
it by `§`. What each shared package holds is `agent-platform`'s `README.md` and it is the owner;
this document cites it rather than describing it again.

## §1 · Who the user is

**The users are the salon's specialists, not its clients.** A specialist opens a chat with the
Telegram bot between clients, says who she worked on and what she did, gets a priced ticket back,
charges the client, and at the end of the day receives what she earned.

No client ever talks to this assistant. That inverts every assumption the sibling assistants make
about the person on the other end, and two of them are load-bearing: the register is that of a
colleague rather than a customer (`docs/BRAND_VOICE.md`), and the sender is known in advance
rather than earning trust during the conversation (§3).

## §2 · Scope

In scope: putting a client who has arrived into the salon's line, calling the next one out of it
and taking a client out of it; recording services against a named client, pricing them from the
salon's catalog at the price that client pays, selling the client a product, taking payment across
one or more methods, recording a tip, closing the sale against the specialist who did the work,
charging a specialist for what she takes for herself, recording what she pays against that, and
reporting each specialist's day.

An owner does all of the above against a named specialist as well as herself, and may
read that specialist's day. She also records what the salon BUYS, by photographing a supplier
invoice, and downloads a month of those as the report DGII is filed (§15).

Out of scope, and the assistant says so rather than improvising: appointments, changing a price,
discounts, another specialist's figures **when the sender is not an owner**, anything about a
client beyond her name, her telephone, which of the salon's two price columns she reads, and — for
today only — which areas she is waiting for and when she arrived.

**The line is not an appointment, and the difference is what keeps that refusal honest.** An
appointment is a promise about a future time; the line is a fact about who is already standing in
the salon. Nothing in §12 holds a future time, nothing can be booked and nothing can be moved, so
a client asking to be put down for Thursday is refused exactly as she was before.

The telephone is in scope because it is an IDENTITY rather than a contact detail: without it two
people called María were one row, one balance and one history, and no report about a client could
be trusted to be about one woman. It is asked for once, never repeated back and never shown on
anything a specialist reads.

## §3 · Identity, and why it is not a conversation

**A sale carries a commission, so who did the work is never a value the sender types.** The
Telegram user id is matched against a pre-registered row in `specialists` at the edge of the
service — in `aziza_adk/channel.py`, before the Runner is invoked. An unregistered sender gets one
fixed line, no model call and no session.

This is the opposite of what a customer-facing assistant does, and the reason is the opposite too:
there, the sender authenticates nobody and must earn access through a conversation; here, the id
matched against a pre-registered row *is* the credential.

**A specialist may only record services in a discipline she holds.** The relation is many-to-many:
someone who does both wax and nails holds both, and is not a third discipline. The check is
deterministic and lives in `tools.add_service`, where the resolved service's discipline is in hand.
It is checked against the discipline of the specialist the work is BOOKED to, not of the sender —
an owner entering a wax service for a nails specialist is the same wrong booking as the specialist
doing it herself.

**Roles and disciplines are independent, and both are additive.** A discipline is what a person
may record; a role is what she may do beyond her own work. Someone can hold either, both or
neither, and the pair is two many-to-many relations rather than one column, because an owner who
also does wax is not a third kind of person.

**An owner is the caller that names somebody else, and the naming is not the model's to invent.**
The `owner` role is the authorization, read off the row the edge resolved and enforced in
`guards.before_tool_guard`, so no wording inside a turn can reach it. Three properties hold it
together:

- **Naming is required of an owner who does no salon work.** She has no work of her own for an
  unnamed entry to belong to, so it is refused rather than attributed to her; omission is the
  silent failure here, and a commission is what a person is paid. An owner who *does* hold a
  discipline is recording her own work when she names nobody, which is the ordinary case.
- **The name resolves deterministically.** `staff.py` matches what she said against the salon's
  own roster through the same resolver the catalog uses, so two specialists sharing a first name
  come back as two candidates and she says which. The roster is everyone holding a discipline:
  someone with none has nothing to book to, and someone who cannot type is still on it, because
  the salon records her work whether or not she can enter it.
- **Both halves are recorded, and one is shown.** `specialist_id` is whose work it is and
  `recorded_by` is who typed it, always set and never NULL, so the audit trail cannot be confused
  with a lost one. The ticket names whose work it is whenever somebody else entered it — the same
  reasoning as naming the client, applied to the other thing that could be wrong.

**A CLIENT's identity is a different kind of thing, and the section title stops applying to it.**
A specialist's is a credential the edge matches before the model runs, and it is never a value
anybody types. A client's is a datum a specialist types, so it IS a conversation — and everything
below follows from that one difference.

- **The identity is the pair: her name folded, and her telephone.** Neither half works alone. A
  name alone made two people called María one row, one balance and one history. A number alone
  would make a mother and her daughter one client, and they share a phone as a matter of course.
- **A client the salon does not know is asked for her number, once.** A client it already knows by
  name is never asked again, and a name two clients answer to is a question rather than a pick:
  charging the first of two Marías is how one of them pays the other's balance. `clients.py`
  holds the shape and the choice, and reaches no database.
- **A number is refused rather than repaired.** Ten digits after `conversation_core`'s fold, or
  nothing. A digit short is a typo, and a typo resolved to whoever it happens to match is a
  stranger's balance. It never falls through to matching on the name alone.
- **A second client of a name already known is CONFIRMED rather than assumed.** A mistyped digit
  and a different person are the same input, so a person decides, with the client in front of
  her. The cost is one visible extra row instead of a silently merged balance.
- **A client who gives no number is served and cannot be fiada.** Her row is never matched by name
  again — `queries.clients_named` filters her out, which is the truth about what the salon knows
  rather than a limitation of the query. So she is charged, her work counts and the commission is
  paid; a balance on her would be one nothing could ever collect. The ticket says so where the
  charge is read, because sprung at the close the refusal arrives as the client is walking out.
- **Client names are matched exact-on-folded, never through the catalog's resolver.** Its overlap
  pass reads "Ana" out of "Mariana", and a fuzzy hit here attaches a real balance to the wrong
  person. That is why `clients.Client` carries no aliases.
- **A number can be corrected, and any specialist may do it.** She is the one the client tells,
  and requiring an owner means the old number simply stays. The correction moves nothing: the
  client is the same row, with the same balance and the same history — only the way to reach her
  changes, and the old number stops being hers rather than becoming a second one.
- **A number another client of that name already holds refuses the change.** Two balances
  becoming one is a merge, and nobody asked for one. Refused in the `UPDATE` itself rather than
  by a check in the tool, because the constraint is the guarantee: without it the unique index
  raises and the specialist is told to try again in a moment, forever.
- **A client who gave no number can give one while her ticket is open, and only then.** She is
  not findable by name, so the ticket she is standing at is the whole window. From then on she is
  findable and can be fiada — the refusal was never about her, it was about nothing being able to
  find her again. Once that ticket closes there is no way back to her, which is the cost of
  serving her at all.

**What the salon knows about a client, an OWNER can read, and nobody else.** `client_history`
answers what one client has had done — every charged visit, at the price the ticket carried, with
whose hands did it — and what she owes now. It resolves her the same way a ticket does, so a name
two clients answer to is a question here too: a history of the wrong woman is worse than none,
because it looks like a fact and nobody at the till is there to contest it.

Two figures on it are deliberately not one. What a visit says she left owing is what happened
that day; `Debe ahora` is her balance. A settlement carries no `sale_id` — it pays down the
balance rather than the ticket — so it can never be attributed back to a visit, and a payment
made weeks later does not rewrite what a day recorded.

Every child table is reached through its own correlated subquery rather than a join. `sale_lines`
and `sale_payments` each fan out independently, so one query joining both multiplies a sale's
total by the number of payments it took — and the figure that comes out still looks like money.

**Two reports read the salon rather than one client.** `salon_clients` answers who comes most,
who spends most and what the salon does most over a window of days; `lapsed_clients` answers who
used to come and no longer does, and whose balance nobody has moved in as long.

- **Spending is what she was BILLED, not what she handed over.** A client who left owing was
  still worth the work, and the commission was taken on it (§7).
- **Coming most and spending most are two readings of the same rows**, taken from one query
  rather than two ordered ones, so the two rankings cannot disagree about a client.
- **What the salon does most is counted by quantity, not by ticket** — two pedicures on one
  ticket were sold twice — and grouped on the service's id under its CURRENT name. §4 freezes a
  name to protect a quote already given, and a ranking is not one; grouping on the snapshot would
  split a service in two the day somebody renames it.
- **Lapsed means at least two charged visits, and none since the cutoff.** One visit is a walk-in
  who never became a client, and reporting her as having stopped is the noise that teaches people
  to skip the list. The default quiet is 60 days — roughly two missed fills: thirty would flag
  half the book every week, and ninety describes somebody who has already gone.
- **The old balances are a SECOND list, not a filter on the first.** They are two different phone
  calls, one to book her and one to collect, and a regular who owes belongs only in the second.
- **A window is clamped rather than refused**, because it is a window and not money — and the
  window it actually read is on the message, so a default the owner did not choose is visible.

## §4 · The ticket

One open ticket per specialist, enforced by a partial unique index rather than by a check in the
tool — the index holds under a race and the tool's own check exists only to say it kindly.

**A line's price is a snapshot.** `sale_lines.unit_price` and `service_name` are copied from the
catalog when the line is added, so a later price change cannot alter a ticket already quoted. What
the client agreed to is read from the frozen row, never re-derived.

**Correcting the client is the one thing that re-prices a ticket, and it is not an exception to
that rule.** The snapshot protects a quote from a later CATALOG edit. When the client was wrong,
the quote was wrong, and a ticket whose lines disagreed with the client it names would be the
actual defect. It is refused outright where a line already on the ticket has no price for the new
client: dropping that line silently would rewrite something she has read.

**The confirm-first gate is keyed on the total as well as the ticket.** A gate that knew only
which ticket had been shown would go on authorizing a figure that has since moved — re-pricing
shifts it by as much as RD$550. Every path that changes a total re-shows it, and keying the gate
on the amount is what makes that a property rather than a habit.

**The template is rendered in Python, not composed by the model.** `aziza_adk/receipts.py` builds
the ticket and the receipt from Decimals; the tools return the rendered text and the prompt
instructs the agent to send it as it came. Every figure the specialist reads came out of a tool.

## §5 · The catalog

**A service the salon does not sell is refused, never invented, and never priced.** What the
specialist said is resolved against the catalog by `aziza_adk/catalog.py` — accent-folded, in her
own words, aliases included. Three passes, narrowest first: the full name, an alias, then
containment. A phrase naming two services comes back as both, and the agent asks which; picking
the first of two prices is a wrong receipt, which is worse than one more question.

There is no price argument on any tool. The price is the catalog row's.

**A row carries two prices, and which one applies is not the model's to decide.** Many services
cost a different amount for a man than for a woman, so `price_female` and `price_male` are both
columns and `catalog.price_for` picks between them from the client the TICKET already names.
Choosing the column is choosing the price, so the same rule that keeps a price out of a tool
argument keeps this out of the model.

**A NULL is not a zero.** Where the salon offers a service to one client only — Brasilero to
women, Barba to men — the other column is NULL and the service is refused with a reason. Reading
across to the column that does have a figure would charge a price the salon never set.

**Which column a name selects is a table, and the ticket says when it guessed.** `names.py` holds
common given names and answers with a provenance: `matched` when the name is known, `defaulted`
when it is not or when it genuinely goes both ways. A defaulted ticket is priced female AND says
so, so a wrong guess is a line the specialist can see before money moves rather than RD$550 lost
in silence. The tables cannot be exhaustive; that is what the notice is for.

**Products resolve through the same resolver.** A product is a catalog row with a name and
aliases, so it reuses `catalog.resolve` rather than a second implementation, and ambiguity behaves
identically for both.

## §6 · The data

`db/schema.sql` is the implementation and is the owner of the columns. What matters about its
shape:

- Money is `NUMERIC(12,2)` in the database and `Decimal` in Python, end to end. A float cannot
  hold RD$1,500.10 exactly, and a cent lost per sale is a discrepancy nobody can reconstruct.
- A payment is a row, not a column, because a client may settle across cash, card and transfer.
  The ticket stays open until the payments cover the total.
- The tip rides on the payment that carried it and is **not** part of its amount.
- `daily_summaries` carries a unique key on (specialist, day). That key is the claim in §8.
- A service carries two price columns, either of which may be NULL; a `CHECK` refuses a row with
  neither, so a service nobody can be charged for cannot exist (§5).
- Product lines are their own table beside service lines, and the specialist's ledger is a third.
  Both separations are what make the commission base structural rather than remembered (§7).
- A client is identified by the PAIR `(folded, phone)`, not by either half. A name alone made two
  people called Carmen one row and one balance; a number alone would make a mother and daughter
  one client. A NULL phone is somebody who gave no number, and Postgres counts NULLs as distinct
  in a unique index — so each of those gets her own row rather than joining one heap.

## §7 · What a specialist earns

**Commission is 40% of the services subtotal, taken before any tip.** The rate is
`COMMISSION_PCT`, one configuration value rather than a per-person column — a per-person split is
a schema change when a real one appears, not a guess made today.

**Tips are the specialist's in full.** A tip folded into the amount would be taxed at the
commission rate, which is why the two are separate columns and separate arguments.

**A product pays her nothing, and that is structural rather than a rule to remember.** A product
sold to a client is a row in `sale_product_lines` and a figure in `sales.products_total`, both
kept apart from the service line table and `services_total`. The commission base is therefore
`services_total` by construction: there is no query that could sweep a product into the figure a
person is paid on by forgetting a `WHERE`.

**What she takes for herself is a debit, not a sale.** She buys at `price_specialist`, which no
client is ever charged, and it never touches a client's ticket. The salon lets her settle it the
same day or carry it to pay-day, so `specialist_ledger` is a ledger of purchases and payments and
the balance is their difference, never a stored number. A settled flag per purchase could not
express a part payment, which is the ordinary case rather than the exception.

**The salon takes cash, Banreservas and BHD, and a payment names which.** Bare "transferencia" is
not a value: it says money arrived and not where, and a register that cannot attribute a figure
cannot be reconciled against one. A client paying part in cash and part by transfer is two calls,
and the ticket stays open until they add up.

**What she takes is two things, and she is told them apart.** A product off the shelf is a
`purchase`; money out of the register is a `loan`. Both are debits in `specialist_ledger` and both
are hers to settle, but owing for a drink and owing cash do not feel the same to be told you owe,
so `settles` says which of the two a payment pays down. Without it the two could only be reported
gross, and a part payment would belong to both. Lending is an owner's — `record_loan` — because
it empties the register.

**The register is closed once a day, by an owner, and both figures are kept.** `close_register`
records what each account holds and what the day's entries say it should, and stores them both:
recomputing the expectation later would quietly absorb anything entered afterwards, which is the
one thing a reconciliation exists to catch. The difference is derived and never stored.

Expected is `amount + tip` on the day's payments, plus client settlements, plus what specialists
paid back, minus what was lent. **Change is not subtracted** — `amount` is what the ticket
received, so a note and its change already net there, and `change_given` is reported rather than
summed. Cash tips are in the drawer until they are handed over at the end of the day, so the close
names what to pay out rather than deducting it.

**A ticket still open refuses the close**, and the refusal names whose it is: money not yet taken
would be measured against an expectation that is not finished, and a variance nobody can explain
teaches people to ignore variances.

**A client can pay less, and then the ticket CLOSES.** One open ticket per specialist is what
makes "my current ticket" mean anything, so a client who leaves owing would otherwise stop her
serving anybody else. The sale closes `partial`, the balance goes to `client_ledger` against the
person rather than the words on the ticket, and it is on **every** render of the next ticket in
her name — beside the total and never inside it, because it is not that sale's money and
`settle_client_debt` is what collects it. Every render rather than the open alone: whoever charges
is not always whoever opened the ticket, and a balance announced once has stopped being visible by
the time anybody could ask for it. Which client
she is, and how the salon tells two of them apart, is §3.

**A `partial` sale is the specialist's work in full and pays her commission in full.** What she
earns is measured by what she did, not by what the salon managed to collect — chasing the balance
is the salon's job, and a commission that waited on it would put her pay at the mercy of whether
a client comes back. `queries.WORKED_STATUSES` is that rule, and the whole `services_total` enters
her day and her pay period on the day she worked; the later settlement reaches `client_ledger`
alone, so nothing is counted twice.

**A client can pay more, and what happens then is decided by the method, not by the model.** Cash
left her hand as notes and the difference is expected back, so it is change: recorded in
`sale_payments.change_given`, which is neither a payment nor a tip, and the drawer is short by it.
A transfer is an exact instruction nobody sends by accident, so the difference was meant and is a
tip. Either default is overridden by what the specialist actually says, and an `extra` she words
unrecognizably is asked about rather than guessed — she set the argument, so she meant something.

`amount` is always what the TICKET received, never what was handed over. That is what keeps
`SUM(amount)` equal to the total on a closed sale no matter how the change and the tips fell.

What she made is commission + tips. The end-of-day message shows all four figures — services,
commission with its rate beside it, tips, and the total — so the arithmetic can be checked by
hand. A figure that appears from nowhere is the kind people dispute later. Products sold and the
whole outstanding balance are reported beside them: the balance is shown rather than subtracted,
because taking it off today's figure would state a deduction nobody has made.

**An owner who asked about somebody is told about her, not handed her message.** The two differ
only in person: one template renders both, because two would drift on the layout while the
figures stayed identical, and a day the reader is greeted by somebody else's name over is a total
she has every reason to read as her own. The third person never says *su* before one of those
figures — docs/BRAND_VOICE.md §1 reads that as *usted*.

## §8 · The working day, and its end

**The salon opens Tuesday to Friday 09:00–19:00 and Saturday 09:00–18:00, and is closed Sunday and
Monday.** `aziza_adk/hours.py` is the schedule and nothing else holds a copy of it.

**A specialist records inside those hours plus one; an owner records whenever.** The grace hour
is there because finishing a client at 19:20 is ordinary, and a window that refused her would be
worked around rather than obeyed. Outside it — after the grace hour, before opening, and all day
Sunday and Monday — the ticket path is an owner's alone: `start_ticket`, `add_service`,
`sell_product`, `record_payment`, `buy_product`. Reading is never gated, so she can still see her
day at midnight.

The refusal is in `guards.before_tool_guard`, beside the one on `on_behalf_of`, because it is the
same widening read the same way: off the role the edge resolved, where no wording in a turn
reaches it. It is **not** re-checked in the tool bodies, which is the one place this design does
not double up — the guard runs on every call ADK makes, and putting the clock in ten bodies would
make every tool test depend on the hour it ran at.

**`hours.py` holds no clock.** Every predicate is handed the moment it judges, and the single
wall-clock read on the turn path is `tools.now` — so "a specialist is refused at 20:01 on a
Tuesday" is a value a test asserts rather than an evening it waits for.

**Pay is twice a month: the 1st–15th and the 16th to the end of it, paid on the 15th and the
30th.** A pay-day that lands on a day the salon is shut is paid on the last one before it, and a
February with no 30th pays on its last day. `aziza_adk/pay.py` holds the calendar and, like
`hours.py`, takes the day it is asked about rather than reading a clock.

**What accumulates toward pay-day is commission, and not tips.** Tips are handed over the same
evening they are earned, so there is nothing of them left to accrue. What she owes is shown beside
the figure and never subtracted from it — the salon lets her settle when she likes, and deducting
would state a deduction nobody has made — split into what she consumed and what she borrowed.

`scripts/daily_summary.py` sends each specialist who billed that day one message, and asks every
owner to count the register unless one of them already has. **That check is the real state rather
than a record of having asked**, which is stronger than a claim: a retry after a failed send still
asks, and nothing asks again once the count is in.

**Somebody with no Telegram id is skipped before the claim, not after.** Her work is recorded by
an owner and she has no way to receive a message; claiming her day would mark it reported forever,
so the moment she has an id there would be nothing left to send. Telegram needs
no approved template and has no reply window, so it is a plain send.

Idempotent by construction rather than by care: the `daily_summaries` row is claimed before the
message goes out and committed only once the send has succeeded. A failed send rolls the claim
back and the next run retries; a second run after a good one claims nothing.

**A simulated run records nothing.** `SUMMARY_SEND_MODE=simulate` logs what would be sent and
writes no claim — a dry run that marks the work as done permanently silences the people it was
rehearsing for.

The business date is the salon's local date at closing, passed in rather than taken from `now()`,
so a night that runs past midnight belongs to the day it began.

## §9 · The transport

Telegram, over `channel-telegram`. The webhook is authenticated by the secret registered at
`setWebhook` — there is no signature and no verification handshake, so a payload is trusted only
as far as the transport that carried it, and the specialist table is the real gate.

A voice note takes the same path a typed message does: the channel transcribes it through
`agent-transcription` and runs the text as an ordinary turn, so it is screened by whatever screens
text rather than arriving as a shape no guard reads.

**A photo does NOT, and that difference is why §15 is shaped the way it is.** It reaches the model
as an image part, and the input screen reads text parts — so what is written inside a picture is
unscreened by code, and there is no transcription step that could flatten it into something the
screen sees. The bytes are fetched through `channel-telegram`'s `media.image_bytes`, which takes
the message and nothing else, so nothing here names one transport's argument list.

Replies are plain text with no parse mode. One unescaped character in the platform's markup
dialect rejects the whole message, and a reply full of prices and decimal points is the worst case
for that — a rejected body is silence, not a formatting glitch.

## §10 · Testing

The deterministic suite is the regression gate and reaches no model and no network. Three
quarters of it needs no database either: the money, the catalog resolution and the rendered
templates are asserted from values alone, which is what lets the arithmetic behind a commission be
held at all. `REQUIRE_DB=1` turns an absent database from skips into failures.

The eval is the second layer, over the wording and the shape of a turn, and is never wired into
`pytest` — a case flips run-to-run even at temperature 0.

## §11 · What is open

This repository's GitHub issues, and nothing here keeps a second copy. **Nothing of this
repository's goes on the board the siblings use**, and that holds for work waiting on the platform
as much as for work that is only ours.

Work spanning the platform and a consumer is two items rather than one, because its halves are
owned in different places: tagging a package is the platform's work and sits on the platform's
board, and moving this repository's pin is ours and is an issue here, naming the tag it waits for.
Neither tracker holds a relation into the other, so that naming is what carries the ordering — and
an issue that does not name its tag is unstartable without asking.

## §12 · The line

**One line for the whole salon, in the order people arrived.** Not a line per specialist: whoever
is free takes whoever is next, and a client showing up does not have to know whose chair she wants.

One arrival is one **visit by one woman**, and she may want more than one area on it — nails and
wax, in either order, from two different people. So what she came for is a row per area rather than
a column: `arrivals` holds who and when, `arrival_wants` holds each area and where it has got to.

**Her place is the moment she walked in, and nothing ever rewrites it.** Two rules follow, and the
salon runs on both:

- She keeps her arrival-time place in every line she is in. Being served for nails does not spend
  her place for wax.
- While somebody has her she is **absent** from every line rather than behind it — she is in a
  chair and cannot take a turn anywhere. Clients who arrived after her are taken ahead of her for
  as long as that lasts, and the moment she is free she is ahead of them again.

The second rule is what makes the first cost nothing. Had the design demoted her instead of
removing her, she would lose the place her arrival gave her every time she was served, which is
precisely the unfairness the line exists to prevent.

**Both rules are one filter over one order, and neither is stored.** `arrivals.py` is arrival order
with the attended removed; a position is derived on every read, exactly as every balance in this
schema is. Two partial unique indexes make the second rule structural rather than remembered:
`ux_arrival_wants_one_serving_per_arrival` — one woman cannot be in two chairs, so a second
specialist reading the line cannot also take her — and
`ux_arrival_wants_one_serving_per_specialist`, which is the same shape and the same argument as
`ux_sales_one_open_per_specialist`.

**A want ends when the ticket does**, in `queries.close_sale`, which is the one place both closing
paths pass through. It is matched on the client as well as on the specialist, because she records
between clients (§1) and has usually already called the next one by the time she charges the last:
matched on her alone, closing that ticket would take the woman now in her chair out of the line.

**A ticket is not the only way out**, and it must not be — a client who changes her mind or is not
there when she is called never reaches one, and a want left `serving` is a specialist who can never
call anybody again. `tools.remove_from_queue` takes her out of every line she is in, because a woman
who is not here is not here for the other one either.

**The line is a DAY's line**, scoped by `arrivals.business_date` and written by the app for the same
reason a sale's is (§8): a night that runs past midnight belongs to the day it began. Without it
tomorrow opens with everybody who was never called yesterday at the head of it, because their
arrival time is earlier. There is deliberately no unique on `(client_id, business_date)` — a client
who comes at ten and again at four is two arrivals, and a constraint forbidding the second would be
wrong about an ordinary day. What `queries.record_arrival` will not do is put her in the line twice
at once: it reuses the arrival she is still standing in and adds only what is new.

**Which line a specialist may call from is her own area**, checked in the tool body where the
resolved area is in hand and against the specialist the call is FOR rather than the sender — the
same rule, in the same place, as the discipline on a service (§3). Holding two areas and naming
neither is a question rather than a guess: a client taken out of the wrong line is a woman sent to
the wrong chair.

## §13 · The code she scans, and the page it opens

**A client puts herself in the line by scanning a code a specialist is showing her.** That is the
one thing in this service a client touches, and it is a FORM rather than a conversation — §1 still
holds, because no client talks to the assistant. What she reaches is two routes and four short
pages, and the assistant is not behind either of them.

**The code is short-lived on purpose.** A printed one can be photographed and used from a sofa, so
the mini app mints a fresh signed link every couple of minutes and the old one dies. The signing is
`agent_webview.tokens` — HMAC, audience-bound, with the clock and the nonce as arguments, so the
exact string is a value a test asserts.

**A token is a CAPABILITY, not a person.** It proves somebody was standing where the code was shown
in the last few minutes. It says nothing about who she is, so the page asks, and nothing downstream
trusts the token for identity.

**Three numbers are one design**, and `aziza_adk/config.py` holds them: the token's life, the
rotation period, and the leeway. What matters is `(ttl - rotate) + leeway` — the grace a client
still has after the code she raised her phone at has left the screen. Too short and there is a
window every rotation in which a real scan fails and nobody can reproduce it; too long and a
photographed code is worth having. The floor is also a client typing: a client the salon knows
reaches the line in ONE post, and one it does not posts twice.

**Her number is half of an identity here too** (§3). A number reaches a mother and her daughter, so
`queries.clients_on_phone` returns candidates and the page offers her the names it found rather
than asking her to type one. That is §3's rule arriving from the other end, and `clients.pick` is
the same function.

**What it refuses, and what it says while refusing.** A stale code says it is stale, because that is
the failure a real client actually hits. Every other reason — forged, wrong audience, wrong secret —
renders the same page and explains nothing: the difference would answer questions about the secret
for whoever is asking. Joining is refused outright while the salon is closed, on `hours.is_open`,
which carries no grace hour — the grace is for a specialist finishing the client already in her
chair, and a client asking to be STARTED after closing is asking for something else.

**One code is not one join, and it is not unlimited either.** A code sits on a screen and several
clients legitimately scan the same one, so single-use would refuse the second real client of the
afternoon. It admits a ceiling instead, which bounds a script rather than a salon. The real defence
against a repeat is elsewhere and is structural: `queries.record_arrival` reuses the arrival she is
already standing in, so scanning twice cannot put one woman in the line twice.

**What this does not stop, stated plainly:** somebody in the salon with a live code can enter names
and numbers that are not hers. Nothing on an unauthenticated form can prevent that. The backstop is
human — the line is on the specialist's own screen, and `tools.remove_from_queue` takes out whatever
is wrong.

## §14 · The mini app

**The specialist's side is a Telegram Mini App**, because a rotating code needs a screen that keeps
minting and a printed sign cannot. It shows the current code, counts down to the next one, and lists
the line as it stands.

**The credential is the one §3 already names.** Telegram signs `initData` with a key derived from
the bot token, and the id inside it is the `telegram_user_id` the `specialists` table keys on — so a
mini app request is authorized exactly as a message is, by a row the salon registered in advance.
A valid Telegram signature from somebody the salon never registered reaches nothing. What Telegram
adds over a webhook delivery is the signature itself.

`initData` travels in a HEADER and never in a query string: it carries its own signature, and a
query string lands in an access log and in a Referer.

**The shell and the script are PUBLIC, and that is not a gap.** `initData` reaches the page through
`window.Telegram.WebApp`, so it is absent from the request that fetches the page and cannot gate it.
The shell therefore carries no name and no figure — everything about the salon arrives through one
of the two gated reads.

**Its policy is the one place in this service that must not deny framing.** A mini app IS framed by
Telegram Web, so `frame-ancestors 'none'` would break it outright, and `X-Frame-Options` has no
origin-list form so any value breaks it. Both are asserted, because the failure is a blank page with
nothing on the server side to see.

**It rides on the same workload as the webhook.** A separate one would need the bot token to verify
`initData`, so splitting would put that credential in two pods instead of one — the opposite of what
a split is for. The cost is that the join page shares the webhook's fate during a rollout, and the
trigger for revisiting it is the one the runbook already names: more than one replica forces the
split, and that is a code project rather than a chart change.


## §15 · What the salon buys

**An owner photographs a supplier invoice, reads back what the assistant made of it, and registers
it.** Nobody else can: `on_media` refuses a specialist who holds no `owner` role at the edge,
before the bytes are fetched and before any model call.

**That refusal is the containment rather than a convenience.** The image reaches the model as a
picture and the input screen reads text (§9), so text rendered inside one is unscreened by code, and
nothing here can change that. What bounds it is everything else being narrow: only owners send a
photo at all, five tools are reachable from it, none takes an amount that bypasses a render, and
the write is gated on a block a human read. The worst a successful injection achieves is a draft the
owner declines.

**The handle on the photo is written to session state at the edge and is never a tool argument.** A
model asked for one produces something plausible, so a tool that accepted it could be called on a
typed description of an invoice. `draft_expense` refuses without one.

### The flow is the ticket's, in miniature

`draft_expense` records nothing: it stages a row and returns a rendered block, which is what she
reads and the only thing that authorizes writing. `register_expense` writes it and **takes no
amount** — every figure comes off the row she was shown, so there is no parameter in which a
misreading could arrive a second time. That is the rule about a price never being an argument (§3),
reaching the one part of this service where the salon's own figures are not the source.

The gate is `session.was_expense_shown`, keyed on the row AND its total exactly as `was_quoted` is.
The row in the database is the source and session state is only the WITNESS that she read it, which
is the way round `record_payment` already works.

**A second photograph replaces the staged one** rather than colliding with it: photographing the
next invoice while the first is still on screen is the ordinary case. The old draft is deleted
rather than kept, because a draft is a question waiting for an answer and keeping every misread
photograph would leave a wrong figure beside a right one in the table the 606 reads.

**A draft goes stale, and the bound is in the query.** A *sí* long afterwards answers a question
whose figures she has stopped looking at, so a draft older than `EXPENSE_DRAFT_TTL_MINUTES` is
simply not found and she sends the photo again.

**She corrects one field at a time**, with `amend_expense`. Re-drafting would ask the model to
re-emit every figure from a photo it may no longer be attending to, and the nasty failure there is
that she corrects the ITBIS and the total moves in silence. Correcting one field necessarily breaks
the reconciliation for a moment — the ITBIS has moved and the total has not — so **the draft is a
scratchpad that says what is wrong, and the check runs again at the moment of writing.** That is
where the gate is.

**`void_expense` exists because the register was already lowered.** Without it the first misread
that got through would be permanently wrong in what the drawer should hold. A status flip, never a
delete, and refused into a day already closed for the reason below.

### What holds a misread still

The model reads figures off a photograph, so a confirmation she skims is not a control.
`agent-platform`'s `packages/fiscal-do/` holds what is decidable from the values alone — no
database, no model and no clock, so the day a date is judged against is a parameter as it is in
`hours.py`. What the norm does not fix stays here: what size of invoice is worth a second look,
which of the salon's methods becomes which `Forma de Pago`, and which spoken word means which
category. The package takes the first as an argument and never sees the other two.

Refused: the parts not adding up to what she paid, an id that is neither nine digits nor eleven, a
comprobante that is not one of the shapes, a date in the future or over a year old, and a supplier
nobody named. **`Monto Facturado` is derived rather than passed**, because DGII defines it as
*Bienes + Servicios* — so there is no field in which a misread of it could arrive. `total_paid` is
the opposite: it is what left the account, so it is reconciled against the parts and never derived
from them, and a mismatch names both figures because neither can be trusted over the other.

Shown and not refused: an ITBIS rate that is neither 18% nor zero, because exemptions and selective
consumption both break 18% and a refusal there would refuse real invoices; an amount over
`LARGE_EXPENSE_THRESHOLD`, because a salon buys a chair and a ceiling that refused one would be
raised until it refused nothing — though a misplaced decimal point is the highest-cost error there
is, which is what the notice is for; and a *consumidor final* comprobante, which gives no ITBIS
credit.

**The RNC's check digit is not implemented.** It would be the most valuable check available — a
transposed digit is the likeliest misreading — but `conversation_core.identity` deliberately ships
no check digit, so adding one is a decision rather than a fix. A wrong notice is ignored; a wrong
refusal is a feature abandoned.

**Nothing verifies the photograph was of an invoice at all.** Handed a picture of a client's nails
the model will produce plausible fields. The only defence is the person reading the block, which is
why the supplier and the comprobante are on it verbatim and not only the money.

### Two dates, and the day the money left

`invoice_date` is what the paper says. `business_date` is the day the money left an account — what
the register reads AND what the 606 files as *Fecha Pago*, so it is one column rather than two that
could disagree. It defaults to today, because the drawer she is short of is today's, and
`register_expense` takes a `paid_on` for an invoice she paid on Monday and is entering on Friday.

**A late registration into a day already closed is refused.** `register_closes.expected_*` is a
frozen snapshot precisely so nothing entered afterwards can absorb into it (§7), and reaching back
to lower it would contradict that on purpose.

**An invoice bought on terms moves no money**, so it has no method and no business date and never
touches the register. The pair is enforced by a `CHECK`, the same shape and the same argument as
`specialist_ledger.method`. Without it the first invoice on thirty-day terms would manufacture a
shortfall in a drawer nothing came out of.

### The register, and why the spend is visible

`queries.expected_register` subtracts a registered expense for its method, exactly as it subtracts a
loan. All three of its callers want that — the close, the salon-wide day, and the end-of-day message
that asks an owner to count — so `salon_day` picking it up is correct rather than an oversight.

**What was spent is listed wherever the expectation drops.** A figure appearing from nowhere is the
kind people dispute later (§7), and a count is only useful as a question about the difference: an
expectation quietly lower is that figure. Listed, never subtracted twice.

**A staged draft does not hold the close hostage**, unlike an open ticket. A draft is not money that
moved, and blocking the count on a photograph she forgot about is the wrong trade; the TTL reaps it.

### The 606, and what is not verified about it

`agent-platform`'s `fiscal_do.report_606` renders one month as the pipe-delimited file DGII is
sent. Nothing in it uses `money.rd`: a machine reads it and would reject `RD$1,000.00`. Its `Line`
is the package's contract rather than this schema, so `queries` hands it rows and the mapping stays
here.

`ITBIS por Adelantar` is derived from the columns it is made of rather than stored at zero, because
a zero understates the credit the salon is owed.

**Rows that cannot be a 606 line are excluded, and how many is said out loud.** An invoice with no
RNC and no comprobante is still registered — the money left the drawer, and the register has to know
— but it cannot be filed, and an owner handed a report quietly missing a third of her invoices would
file it.

> **THE COLUMN LIST AND ITS CODE VALUES ARE NOT VERIFIED.** The governing norm is General Norm
> 07-2018 as amended by 05-2019, and the authority is DGII's current instructivo and the
> pre-validation spreadsheet on its portal. What this repository implements was read off neither.
> `db/schema.sql` carries no `ALTER`, so a wrong shape is a rebuild rather than a migration — and
> four facts would force one: that *Fecha Pago* is one date rather than one per instalment, that
> *Bienes* and *Servicios* are two amounts on one record rather than a line-item breakdown, that
> *Tipo ID* is derivable from the digit count, and that `(RNC, NCF)` identifies an invoice. The
> treatment columns being zero is not among them: they are already columns, so the salon becoming
> an ITBIS-retaining agent is a behaviour change and not a schema one.

**The same invoice cannot be registered twice.** It would come off the register twice and DGII
rejects a repeated comprobante too, so `(rnc, ncf)` is unique among registered rows — refused by the
insert, because the constraint is what guarantees it. Voided rows are outside the index: a misread
that got through is voided and re-entered.

**`Forma de Pago` is derived from the method and is LOSSY.** The salon's accounts are cash,
Banreservas and BHD, and a bank name cannot say whether the money moved as a transfer or on a card,
which the format distinguishes. It is stored on the row rather than derived at render time, so the
derivation is visible as a default rather than passing for a fact.

### The link she taps

`month_606` mints a short-lived signed link, and the download is one route on the app that already
serves the join page. A token is a CAPABILITY as §13's is: it proves somebody was sent this link and
says nothing about who they are.

**Its own signing secret**, never the join page's — sharing would mean rotating the code a client
scans in order to rotate the link an owner holds. **No spend counter**, because link scanners and
in-app browsers fetch a URL before anybody taps it (§13) and a single-use link would be spent by the
chat's own preview; a download is a read, and the TTL is the bound. The month travels in the token
rather than in the path, so one link means one month.

**With no `SALON_RNC` or no signing secret nothing is minted.** A filing that does not say who filed
it is worse than none, and an unsigned link is worse than no link.
