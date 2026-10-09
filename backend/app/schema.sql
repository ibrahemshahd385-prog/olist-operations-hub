-- =====================================================================
-- Olist Operations Hub - database schema (SQLite)
--
-- Part 1 keeps the 9 original Olist tables with their original column
-- names, so every number here can be traced back to the Kaggle dataset.
-- Part 2 adds the tables a real operating system needs and the dataset
-- does not have: invoices (NF-e) and an audit trail of order events.
-- =====================================================================

-- ---------------------------------------------------------------------
-- Part 1: original Olist tables
-- ---------------------------------------------------------------------

-- One row per (customer, order). Olist gives every order a new customer_id;
-- customer_unique_id is the real person (96,096 people for 99,441 orders).
CREATE TABLE customers (
    customer_id              TEXT PRIMARY KEY,
    customer_unique_id       TEXT NOT NULL,
    customer_zip_code_prefix TEXT,
    customer_city            TEXT,
    customer_state           TEXT
);

CREATE TABLE sellers (
    seller_id              TEXT PRIMARY KEY,
    seller_zip_code_prefix TEXT,
    seller_city            TEXT,
    seller_state           TEXT,
    cnpj_simulated         TEXT   -- the dataset is anonymised; a fake 14-digit id for the NF-e simulator
);

-- Column names fixed from the original typos ("lenght" -> "length").
CREATE TABLE products (
    product_id                 TEXT PRIMARY KEY,
    product_category_name      TEXT,
    product_category_name_english TEXT,
    product_name_length        INTEGER,
    product_description_length INTEGER,
    product_photos_qty         INTEGER,
    product_weight_g           REAL,
    product_length_cm          REAL,
    product_height_cm          REAL,
    product_width_cm           REAL
);

CREATE TABLE orders (
    order_id                      TEXT PRIMARY KEY,
    customer_id                   TEXT NOT NULL REFERENCES customers(customer_id),
    order_status                  TEXT NOT NULL,
    order_purchase_timestamp      TEXT NOT NULL,
    order_approved_at             TEXT,
    order_delivered_carrier_date  TEXT,
    order_delivered_customer_date TEXT,
    order_estimated_delivery_date TEXT,
    -- added by this system:
    source                        TEXT NOT NULL DEFAULT 'system',  -- 'historical' (Kaggle) or 'system' (created here)
    canceled_at                   TEXT,
    cancel_reason                 TEXT
);

-- One row per unit sold: an order with 3 units of the same product has 3 rows
-- (order_item_id = 1, 2, 3). We keep that convention for new orders too.
CREATE TABLE order_items (
    order_id      TEXT NOT NULL REFERENCES orders(order_id),
    order_item_id INTEGER NOT NULL,
    product_id    TEXT NOT NULL REFERENCES products(product_id),
    seller_id     TEXT NOT NULL REFERENCES sellers(seller_id),
    price         REAL NOT NULL,
    freight_value REAL NOT NULL,
    PRIMARY KEY (order_id, order_item_id)
);

CREATE TABLE order_payments (
    order_id             TEXT NOT NULL REFERENCES orders(order_id),
    payment_sequential   INTEGER NOT NULL,
    payment_type         TEXT NOT NULL,
    payment_installments INTEGER NOT NULL,
    payment_value        REAL NOT NULL,
    PRIMARY KEY (order_id, payment_sequential)
);

-- review_id is NOT unique in the original data, so SQLite's rowid is the key.
CREATE TABLE order_reviews (
    review_id               TEXT NOT NULL,
    order_id                TEXT NOT NULL,
    review_score            INTEGER NOT NULL,
    review_comment_title    TEXT,
    review_comment_message  TEXT,
    review_creation_date    TEXT,
    review_answer_timestamp TEXT
);

-- The raw file has ~1M rows (many points per zip prefix). We keep one
-- representative point per prefix (median lat/lng), ~19k rows.
CREATE TABLE geolocation (
    zip_code_prefix TEXT PRIMARY KEY,
    lat             REAL NOT NULL,
    lng             REAL NOT NULL,
    city            TEXT,
    state           TEXT
);

CREATE TABLE category_translation (
    product_category_name         TEXT PRIMARY KEY,
    product_category_name_english TEXT
);

-- ---------------------------------------------------------------------
-- Part 2: tables added by the system
-- ---------------------------------------------------------------------

-- One NF-e per (order, seller): when an order has items from 2 sellers,
-- each seller is a different legal issuer and issues its own invoice.
CREATE TABLE invoices (
    invoice_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id        TEXT NOT NULL REFERENCES orders(order_id),
    seller_id       TEXT NOT NULL REFERENCES sellers(seller_id),
    number          INTEGER NOT NULL,          -- nNF: sequential per seller and series
    series          INTEGER NOT NULL,
    access_key      TEXT NOT NULL UNIQUE,      -- the 44-digit "chave de acesso"
    status          TEXT NOT NULL,             -- 'authorized' or 'canceled'
    issued_at       TEXT NOT NULL,
    canceled_at     TEXT,
    products_total  REAL NOT NULL,
    freight_total   REAL NOT NULL,
    total           REAL NOT NULL,
    items_count     INTEGER NOT NULL
);

-- Audit trail: every status change made through the system is recorded,
-- with when it happened and an optional note.
CREATE TABLE order_events (
    event_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id    TEXT NOT NULL REFERENCES orders(order_id),
    status      TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    note        TEXT
);

-- ---------------------------------------------------------------------
-- Reference tables pre-computed from history (used for suggestions)
-- ---------------------------------------------------------------------

-- What Olist historically promised vs. what actually happened, per state.
CREATE TABLE ref_state_delivery (
    customer_state       TEXT PRIMARY KEY,
    median_promised_days REAL NOT NULL,
    median_actual_days   REAL NOT NULL,
    orders               INTEGER NOT NULL
);

-- ---------------------------------------------------------------------
-- Indexes: make the filters used by the screens fast
-- ---------------------------------------------------------------------
CREATE INDEX idx_orders_purchase  ON orders(order_purchase_timestamp);
CREATE INDEX idx_orders_status    ON orders(order_status);
CREATE INDEX idx_orders_customer  ON orders(customer_id);
CREATE INDEX idx_customers_unique ON customers(customer_unique_id);
CREATE INDEX idx_customers_state  ON customers(customer_state);
CREATE INDEX idx_items_order      ON order_items(order_id);
CREATE INDEX idx_items_seller     ON order_items(seller_id);
CREATE INDEX idx_items_product    ON order_items(product_id);
CREATE INDEX idx_payments_order   ON order_payments(order_id);
CREATE INDEX idx_reviews_order    ON order_reviews(order_id);
CREATE INDEX idx_invoices_order   ON invoices(order_id);
-- business rules enforced by the database itself:
-- a seller can have only one valid invoice per order, and numbers never repeat.
CREATE UNIQUE INDEX ux_invoice_active ON invoices(order_id, seller_id) WHERE status = 'authorized';
CREATE UNIQUE INDEX ux_invoice_number ON invoices(seller_id, series, number);
CREATE INDEX idx_invoices_seller  ON invoices(seller_id);
CREATE INDEX idx_events_order     ON order_events(order_id);
