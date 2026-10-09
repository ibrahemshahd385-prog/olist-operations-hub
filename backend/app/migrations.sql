-- Tables added after Module 1. Every statement is safe to run again
-- (IF NOT EXISTS), so the API runs this file on start-up and an existing
-- database is upgraded without losing the orders already registered.

-- Module 2: what the models said when the order was registered.
-- Kept apart from `orders` on purpose: orders are facts, these are predictions.
CREATE TABLE IF NOT EXISTS order_predictions (
    order_id            TEXT PRIMARY KEY REFERENCES orders(order_id),
    eta_days            REAL,
    promise_days        INTEGER,
    promise_source      TEXT,      -- 'model' or 'olist_history'
    legacy_promise_days INTEGER,   -- what Olist would have promised, for comparison
    late_risk           REAL,
    risk_level          TEXT,
    risk_reasons        TEXT,      -- JSON list of plain-language reasons
    distance_km         REAL,
    model_trained_at    TEXT,
    created_at          TEXT NOT NULL
);

-- Module 4: one row per review with a written comment, scored by the review model.
CREATE TABLE IF NOT EXISTS review_insights (
    review_rowid  INTEGER PRIMARY KEY,   -- rowid of the review in order_reviews
    order_id      TEXT NOT NULL,
    review_score  INTEGER NOT NULL,
    sentiment     REAL NOT NULL,         -- probability that the text is negative (0-1)
    topics        TEXT NOT NULL          -- JSON list of topic keys found in the text
);
CREATE INDEX IF NOT EXISTS idx_review_insights_order ON review_insights(order_id);
