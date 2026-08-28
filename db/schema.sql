-- Salón Aziza — business schema for database `aziza`.
-- Mirrors docs/PROJECT_DEFINITION.md §6. Idempotent: safe to apply repeatedly.
--
-- The ADK session store lives in a SEPARATE database (`aziza_sessions`), created empty by
-- db/init.sql and managed entirely by ADK (agent-platform docs/ADK_LESSONS_LEARNED.md §6a).
-- Nothing here touches it.
--
-- Money is NUMERIC(12,2) everywhere. A commission is what a person is paid, and a float cannot
-- hold RD$1,500.10 exactly.

BEGIN;

CREATE TABLE IF NOT EXISTS disciplines (
    id   SERIAL PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS specialists (
    id               SERIAL PRIMARY KEY,
    specialist_ref   TEXT NOT NULL UNIQUE,
    -- THE CREDENTIAL. A sale carries a commission, so who did the work is never a value the
    -- sender types — it is this, matched at the edge before the model runs (§3).
    telegram_user_id TEXT NOT NULL UNIQUE,
    full_name        TEXT NOT NULL,
    active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Many-to-many, because someone who does both wax and nails holds both and is not a third
-- discipline (§3).
CREATE TABLE IF NOT EXISTS specialist_disciplines (
    specialist_id INTEGER NOT NULL REFERENCES specialists (id)  ON DELETE CASCADE,
    discipline_id INTEGER NOT NULL REFERENCES disciplines (id)  ON DELETE CASCADE,
    PRIMARY KEY (specialist_id, discipline_id)
);

CREATE TABLE IF NOT EXISTS services (
    id            SERIAL PRIMARY KEY,
    service_ref   TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL UNIQUE,
    discipline_id INTEGER NOT NULL REFERENCES disciplines (id),
    price         NUMERIC(12, 2) NOT NULL CHECK (price >= 0),
    currency      TEXT NOT NULL DEFAULT 'DOP',
    -- What a specialist calls it out loud, in their own words. Matched on, never shown.
    aliases       TEXT NOT NULL DEFAULT '',
    active        BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS ix_services_discipline ON services (discipline_id);

CREATE TABLE IF NOT EXISTS sales (
    id             SERIAL PRIMARY KEY,
    sale_ref       TEXT NOT NULL UNIQUE,
    specialist_id  INTEGER NOT NULL REFERENCES specialists (id),
    client_name    TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'open'
                   CHECK (status IN ('open', 'paid', 'void')),
    services_total NUMERIC(12, 2) NOT NULL DEFAULT 0 CHECK (services_total >= 0),
    -- Stamped when the sale closes, in salon-local time: a night that runs past midnight belongs
    -- to the day it started, and the end-of-day message is grouped by this.
    business_date  DATE,
    opened_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    paid_at        TIMESTAMPTZ
);

-- One open ticket per specialist, so "my current ticket" is unambiguous — and it holds under a
-- race, which a check-then-insert in the tool does not. Partial, so a closed sale frees the slot.
CREATE UNIQUE INDEX IF NOT EXISTS ux_sales_one_open_per_specialist
    ON sales (specialist_id) WHERE status = 'open';

CREATE INDEX IF NOT EXISTS ix_sales_specialist_date ON sales (specialist_id, business_date);

CREATE TABLE IF NOT EXISTS sale_lines (
    id           SERIAL PRIMARY KEY,
    sale_id      INTEGER NOT NULL REFERENCES sales (id) ON DELETE CASCADE,
    service_id   INTEGER NOT NULL REFERENCES services (id),
    -- SNAPSHOTS, both of them. A later catalog edit must not change a ticket already quoted:
    -- what the client agreed to is read from this row, never re-derived (§4).
    service_name TEXT NOT NULL,
    unit_price   NUMERIC(12, 2) NOT NULL CHECK (unit_price >= 0),
    quantity     INTEGER NOT NULL CHECK (quantity > 0),
    line_total   NUMERIC(12, 2) NOT NULL CHECK (line_total >= 0),
    added_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_sale_lines_sale ON sale_lines (sale_id);

CREATE TABLE IF NOT EXISTS sale_payments (
    id          SERIAL PRIMARY KEY,
    sale_id     INTEGER NOT NULL REFERENCES sales (id) ON DELETE CASCADE,
    method      TEXT NOT NULL CHECK (method IN ('cash', 'card', 'transfer')),
    amount      NUMERIC(12, 2) NOT NULL CHECK (amount > 0),
    -- The tip rides on the payment that carried it and is NOT part of `amount`: commission is
    -- taken on services alone, and a tip folded into the total would be taxed at 40% (§7).
    tip         NUMERIC(12, 2) NOT NULL DEFAULT 0 CHECK (tip >= 0),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_sale_payments_sale ON sale_payments (sale_id);

CREATE TABLE IF NOT EXISTS daily_summaries (
    id             SERIAL PRIMARY KEY,
    specialist_id  INTEGER NOT NULL REFERENCES specialists (id) ON DELETE CASCADE,
    business_date  DATE NOT NULL,
    services_total NUMERIC(12, 2) NOT NULL,
    commission     NUMERIC(12, 2) NOT NULL,
    tips           NUMERIC(12, 2) NOT NULL,
    sent_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- THE claim that stops a second send. The row is written before the message goes out and
    -- committed only once it has (scripts/daily_summary.py).
    UNIQUE (specialist_id, business_date)
);

COMMIT;
