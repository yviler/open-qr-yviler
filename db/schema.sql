-- =============================================================================
-- QR Ordering SaaS Schema
-- Multi-tenant: one PostgreSQL schema per restaurant
-- =============================================================================
-- Structure:
--   platform schema  → tenant registry, platform-level auth
--   {slug} schema    → per-restaurant data (menu, orders, sessions, etc.)
-- =============================================================================


-- ---------------------------------------------------------------------------
-- PLATFORM SCHEMA
-- Shared across all tenants. Manages restaurant registration and access.
-- ---------------------------------------------------------------------------

CREATE SCHEMA IF NOT EXISTS platform;

-- Restaurant registry (one row per tenant)
CREATE TABLE platform.restaurants (
    id          serial      PRIMARY KEY,
    slug        text        NOT NULL UNIQUE,           -- used as schema name + URL segment
    name        text        NOT NULL,
    owner_email text        NOT NULL UNIQUE,
    plan        text        NOT NULL DEFAULT 'trial'   -- trial, basic, pro, etc.
                            CHECK (plan IN ('trial', 'basic', 'pro')),
    is_active   boolean     NOT NULL DEFAULT true,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

-- Platform users (restaurant owners/admins — NOT customer-facing)
-- Each user belongs to one restaurant.
CREATE TABLE platform.users (
    id              serial      PRIMARY KEY,
    restaurant_id   integer     NOT NULL REFERENCES platform.restaurants(id) ON DELETE CASCADE,
    email           text        NOT NULL UNIQUE,
    password_hash   text        NOT NULL,
    full_name       text,
    role            text        NOT NULL DEFAULT 'owner'
                                CHECK (role IN ('owner', 'manager', 'staff')),
    is_active       boolean     NOT NULL DEFAULT true,
    created_at      timestamptz NOT NULL DEFAULT now(),
    last_login_at   timestamptz
);

CREATE INDEX ON platform.users (restaurant_id);


-- ---------------------------------------------------------------------------
-- PER-RESTAURANT SCHEMA TEMPLATE
-- Run once per new restaurant, replacing {slug} with the restaurant's slug.
-- Call: SELECT platform.create_restaurant_schema('slug');
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION platform.create_restaurant_schema(p_slug text)
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    EXECUTE format('CREATE SCHEMA IF NOT EXISTS %I', p_slug);

    -- Settings: key/value config store for this restaurant
    EXECUTE format('
        CREATE TABLE IF NOT EXISTS %I.settings (
            key     text PRIMARY KEY,
            value   text NOT NULL
        )', p_slug);

    -- Seed default settings
    EXECUTE format($s$
        INSERT INTO %I.settings (key, value) VALUES
            (''qr_mode'',       ''table''),
            (''brand_name'',    ''My Restaurant''),
            (''currency'',      ''IDR''),
            (''lang_default'',  ''id''),
            (''hours_enabled'', ''1''),
            (''hours_label_id'',''Jam Buka''),
            (''hours_label_en'',''Opening Hours''),
            (''hours_open'',    ''''),
            (''hours_close'',   ''''),
            (''hours_note_id'', ''Jam buka hari ini''),
            (''hours_note_en'', ''Opening times today'')
        ON CONFLICT DO NOTHING
    $s$, p_slug);

    -- Tables: physical restaurant tables
    EXECUTE format('
        CREATE TABLE IF NOT EXISTS %I.tables (
            id              serial      PRIMARY KEY,
            table_number    text        NOT NULL UNIQUE,
            label           text,
            active          boolean     NOT NULL DEFAULT true
        )', p_slug);

    -- Categories: top-level menu groupings
    EXECUTE format('
        CREATE TABLE IF NOT EXISTS %I.categories (
            id          serial  PRIMARY KEY,
            name        text    NOT NULL,
            sort_order  integer NOT NULL DEFAULT 0
        )', p_slug);

    -- Items: individual menu items
    EXECUTE format('
        CREATE TABLE IF NOT EXISTS %I.items (
            id              serial      PRIMARY KEY,
            category_id     integer     NOT NULL REFERENCES %I.categories(id) ON DELETE CASCADE,
            name            text        NOT NULL,
            description     text,
            price           integer,                    -- fixed price in minor currency unit
            price_per_kg    integer,                    -- kg-based pricing
            unit            text,                       -- e.g. "portion", "kg"
            portion_info    text,
            portion_choices text,
            portion_ons_min integer,
            portion_ons_max integer,
            available       boolean     NOT NULL DEFAULT true,
            qr_render       boolean     NOT NULL DEFAULT true,
            image_path      text,
            sort_order      integer     NOT NULL DEFAULT 0
        )', p_slug, p_slug);

    -- Dishes: variants of an item (e.g. cooking styles)
    EXECUTE format('
        CREATE TABLE IF NOT EXISTS %I.dishes (
            id              serial      PRIMARY KEY,
            item_id         integer     NOT NULL REFERENCES %I.items(id) ON DELETE CASCADE,
            name            text        NOT NULL,
            available       boolean     NOT NULL DEFAULT true,
            price_override  integer,
            image_path      text,
            sort_order      integer     NOT NULL DEFAULT 0
        )', p_slug, p_slug);

    -- Sessions: one per table visit / customer group
    EXECUTE format('
        CREATE TABLE IF NOT EXISTS %I.sessions (
            id              text        PRIMARY KEY,    -- "table:{number}" or UUID
            table_number    text        NOT NULL,
            status          text        NOT NULL DEFAULT ''active''
                                        CHECK (status IN (''active'', ''closed'')),
            guest_name      text,
            created_at      timestamptz NOT NULL DEFAULT now(),
            closed_at       timestamptz
        )', p_slug);

    EXECUTE format('CREATE INDEX IF NOT EXISTS sessions_table_idx ON %I.sessions (table_number)', p_slug);
    EXECUTE format('CREATE INDEX IF NOT EXISTS sessions_status_idx ON %I.sessions (status)', p_slug);

    -- Orders: one submission event per "send to kitchen" action
    EXECUTE format('
        CREATE TABLE IF NOT EXISTS %I.orders (
            id              serial      PRIMARY KEY,
            session_id      text        REFERENCES %I.sessions(id) ON DELETE SET NULL,
            table_number    text        NOT NULL,
            guest_name      text,
            status          text        NOT NULL DEFAULT ''submitted''
                                        CHECK (status IN (''submitted'', ''seen'', ''done'')),
            created_at      timestamptz NOT NULL DEFAULT now()
        )', p_slug, p_slug);

    EXECUTE format('CREATE INDEX IF NOT EXISTS orders_session_idx ON %I.orders (session_id)', p_slug);

    -- Order items: line items within an order
    EXECUTE format('
        CREATE TABLE IF NOT EXISTS %I.order_items (
            id          serial      PRIMARY KEY,
            order_id    integer     NOT NULL REFERENCES %I.orders(id) ON DELETE CASCADE,
            item_name   text        NOT NULL,
            dish_name   text,                          -- variant selected, if any
            qty         numeric(10,3) NOT NULL,
            unit_price  integer     NOT NULL DEFAULT 0,
            line_total  integer     NOT NULL DEFAULT 0,
            note        text
        )', p_slug, p_slug);

    -- Images: uploaded media tracked per restaurant
    EXECUTE format('
        CREATE TABLE IF NOT EXISTS %I.images (
            id              serial      PRIMARY KEY,
            filename        text        NOT NULL,
            original_name   text,
            alt_text        text,
            uploaded_at     timestamptz NOT NULL DEFAULT now()
        )', p_slug);

END;
$$;


-- ---------------------------------------------------------------------------
-- HELPER: updated_at trigger (reusable across all schemas)
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION platform.set_updated_at()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

CREATE TRIGGER restaurants_updated_at
    BEFORE UPDATE ON platform.restaurants
    FOR EACH ROW EXECUTE FUNCTION platform.set_updated_at();
