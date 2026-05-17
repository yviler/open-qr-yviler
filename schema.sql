-- Set your local timezone. Examples: 'Asia/Jakarta', 'America/New_York', 'Europe/London'
SET TIME ZONE 'Asia/Jakarta';

-- =========================
-- Schemas
-- =========================

CREATE SCHEMA IF NOT EXISTS qr;

-- =========================
-- Types
-- =========================

CREATE TYPE public.service_type AS ENUM (
    'dine_in',
    'takeaway',
    'delivery'
);

-- =========================
-- Functions
-- =========================

CREATE OR REPLACE FUNCTION public.set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$;

-- =========================
-- Core tables
-- =========================

CREATE TABLE IF NOT EXISTS sessions (
    id                      TEXT PRIMARY KEY,
    pax                     INTEGER DEFAULT 1,
    table_number            TEXT NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    guest_name              TEXT,
    dp_amount               INTEGER DEFAULT 0,
    dp_method               TEXT,
    dp_paid_at              TIMESTAMPTZ,
    note                    TEXT,
    status                  TEXT DEFAULT 'active',
    closed_at               TIMESTAMPTZ,
    opened_by_user_id       INTEGER,
    closed_by_user_id       INTEGER,
    split_labels            TEXT,
    split_meta              JSONB NOT NULL DEFAULT '{}',
    lock_user_id            INTEGER NULL,
    lock_until              TIMESTAMP NULL,
    lock_nonce              TEXT,
    lock_acquired_at        TIMESTAMPTZ DEFAULT now(),
    billing_started_at      TIMESTAMPTZ,
    service_type            public.service_type NOT NULL DEFAULT 'dine_in',
    pickup_time             TIMESTAMPTZ,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    reopened_at             TIMESTAMP,
    reopened_by_user_id     INTEGER,
    CONSTRAINT sessions_status_chk
      CHECK (status IN ('active','closed','cancelled','moved'))
);

CREATE TABLE IF NOT EXISTS order_items (
    id                  INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id          TEXT NOT NULL,
    table_number        TEXT NOT NULL,
    item_name           TEXT NOT NULL,
    qty                 NUMERIC(10,1) NOT NULL,
    price               INTEGER NOT NULL,
    total_price         INTEGER NOT NULL,
    sauce               TEXT,
    note                TEXT,
    status              TEXT NOT NULL DEFAULT 'new',
    "timestamp"         TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by_user_id  INTEGER,
    updated_by_user_id  INTEGER,
    bill_group          TEXT DEFAULT NULL,
    void_qty            NUMERIC(10,1) NOT NULL DEFAULT 0,
    updated_at          TIMESTAMPTZ,
    CONSTRAINT fk_order_items_session
      FOREIGN KEY (session_id) REFERENCES sessions(id)
      ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT order_items_qty_chk
      CHECK (
        status = 'cancelled'
        OR (qty >= 0 AND ((qty * 10)::INT % 5) = 0)
      ),
    CONSTRAINT order_items_status_chk
      CHECK (status IN ('new','edited','served','paid','cancelled','printed'))
);

CREATE TABLE IF NOT EXISTS payments (
    id                      INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id              TEXT,
    amount                  INTEGER,
    method                  TEXT,
    paid_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    cash_received           INTEGER DEFAULT NULL,
    change_given            INTEGER DEFAULT NULL,
    discount_percent        INTEGER DEFAULT 0,
    discount_amount         INTEGER DEFAULT 0,
    tax                     INTEGER DEFAULT 0,
    service                 INTEGER DEFAULT 0,
    total_before_discount   INTEGER DEFAULT 0,
    card_type               TEXT DEFAULT NULL,
    created_by_user_id      INTEGER,
    bill_group              TEXT DEFAULT NULL,
    dp_applied_amount       INTEGER DEFAULT 0,
    is_refund               BOOLEAN NOT NULL DEFAULT FALSE,
    refund_of               INTEGER REFERENCES payments(id),
    refund_reason           TEXT,
    refunded_by_user_id     INTEGER,
    is_dp                   BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS reservations (
    id                      INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    guest_name              TEXT NOT NULL,
    phone                   TEXT,
    pax                     INTEGER NOT NULL,
    date                    DATE NOT NULL,
    "time"                  TIME NOT NULL,
    notes                   TEXT,
    status                  TEXT DEFAULT 'pending',
    table_number            TEXT DEFAULT NULL,
    session_id              TEXT DEFAULT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by_user_id      INTEGER,
    confirmed_by_user_id    INTEGER,
    seated_by_user_id       INTEGER,
    dp_amount               INTEGER NOT NULL DEFAULT 0,
    dp_method               TEXT,
    dp_paid_at              TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS users (
    id                      INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username                TEXT NOT NULL UNIQUE,
    full_name               TEXT,
    password_hash           TEXT NOT NULL,
    demo_password_plain     TEXT,
    role                    TEXT NOT NULL CHECK (role IN ('admin','cashier','waiter','viewer')),
    is_active               BOOLEAN NOT NULL DEFAULT TRUE,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS reservation_items (
    id                  INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    reservation_id      INTEGER NOT NULL,
    item_name           TEXT NOT NULL,
    qty                 INTEGER NOT NULL,
    price               INTEGER NOT NULL,
    sauce               TEXT,
    note                TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by_user_id  INTEGER,
    CONSTRAINT reservation_items_qty_chk
      CHECK (qty >= 0 AND (qty * 10) % 5 = 0),
    CONSTRAINT fk_reservation_items_res
      FOREIGN KEY (reservation_id) REFERENCES reservations(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS floor_layouts (
    floor               TEXT PRIMARY KEY,
    grid_cols           INTEGER NOT NULL DEFAULT 12,
    grid_row_px         INTEGER NOT NULL DEFAULT 90,
    grid_gap_px         INTEGER NOT NULL DEFAULT 6,
    boxes               JSONB NOT NULL,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by_user_id  INTEGER
);

-- =========================
-- QR schema
-- =========================

CREATE TABLE IF NOT EXISTS qr.qr_orders (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    table_number    TEXT NOT NULL,
    session_id      TEXT,
    guest_name      TEXT,
    items           JSONB NOT NULL,
    notes           TEXT,
    status          TEXT NOT NULL DEFAULT 'new',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    sent_at         TIMESTAMPTZ
);

-- =========================
-- Triggers
-- =========================

DROP TRIGGER IF EXISTS trg_sessions_updated_at ON public.sessions;
CREATE TRIGGER trg_sessions_updated_at
    BEFORE UPDATE ON public.sessions
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- =========================
-- Indexes
-- =========================

CREATE INDEX IF NOT EXISTS idx_users_username             ON users(username);

CREATE INDEX IF NOT EXISTS idx_order_items_session_group  ON order_items(session_id, bill_group);
CREATE INDEX IF NOT EXISTS idx_order_items_ts             ON order_items("timestamp");
CREATE INDEX IF NOT EXISTS idx_order_items_status         ON order_items(status);
CREATE INDEX IF NOT EXISTS idx_order_items_item           ON order_items(item_name);

CREATE INDEX IF NOT EXISTS idx_payments_is_refund         ON payments(is_refund);
CREATE INDEX IF NOT EXISTS idx_payments_refund_of         ON payments(refund_of);
CREATE INDEX IF NOT EXISTS idx_payments_paid_at           ON payments(paid_at);
CREATE INDEX IF NOT EXISTS idx_payments_method            ON payments(method);

CREATE INDEX IF NOT EXISTS idx_sessions_closed_at         ON sessions(closed_at);
CREATE INDEX IF NOT EXISTS idx_sessions_created_at        ON sessions(created_at);
CREATE INDEX IF NOT EXISTS idx_sessions_lock_until        ON sessions(lock_until);
CREATE INDEX IF NOT EXISTS idx_sessions_ta_open           ON sessions(COALESCE(pickup_time, created_at))
    WHERE service_type = 'takeaway' AND closed_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_reservations_date_time     ON reservations(date, "time");
CREATE INDEX IF NOT EXISTS idx_reservation_items_res      ON reservation_items(reservation_id);

CREATE INDEX IF NOT EXISTS qr_idx_qr_orders_status_created ON qr.qr_orders(status, created_at DESC);
CREATE INDEX IF NOT EXISTS qr_idx_qr_orders_table_status   ON qr.qr_orders(table_number, status);
