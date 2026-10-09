"""Module 2: smart logistics - model results, live quotes, at-risk orders, delivery lanes."""
import json
import sqlite3
from datetime import datetime

from ..db import rows_to_dicts
from ..errors import ValidationFailed
from ..ml import predictor
from ..schemas import QuoteIn
from .orders import resolve_address
from .workflow import STATUS_LABELS, parse_ts

_lanes_cache = {}


def overview(conn: sqlite3.Connection) -> dict:
    return {"models": predictor.metrics(), "lanes": lanes(conn)}


def lanes(conn: sqlite3.Connection, limit: int = 12) -> list:
    """The busiest seller-state -> customer-state routes in the dataset, with how they perform.
    Computed once per run (the dataset does not change)."""
    if "rows" not in _lanes_cache:
        _lanes_cache["rows"] = rows_to_dicts(conn.execute(
            """WITH order_lane AS (
                   SELECT DISTINCT o.order_id, s.seller_state, c.customer_state,
                          julianday(o.order_delivered_customer_date) - julianday(o.order_purchase_timestamp) AS days,
                          date(o.order_delivered_customer_date) > date(o.order_estimated_delivery_date) AS late
                   FROM orders o
                   JOIN customers c ON c.customer_id = o.customer_id
                   JOIN order_items i ON i.order_id = o.order_id
                   JOIN sellers s ON s.seller_id = i.seller_id
                   WHERE o.source = 'historical' AND o.order_status = 'delivered'
                     AND o.order_delivered_customer_date IS NOT NULL)
               SELECT seller_state, customer_state, COUNT(*) AS orders,
                      ROUND(AVG(days), 1) AS avg_days, ROUND(AVG(late), 4) AS late_rate
               FROM order_lane GROUP BY seller_state, customer_state
               ORDER BY orders DESC LIMIT ?""", (limit,)).fetchall())
    return _lanes_cache["rows"]


def quote(conn: sqlite3.Connection, payload: QuoteIn) -> dict:
    address, error = resolve_address(conn, payload.customer)
    if error:
        raise ValidationFailed([error])
    result = predictor.quote(conn, address["state"], address["zip"],
                             [l.model_dump() for l in payload.items], payload.payment_types)
    result["destination_state"] = address["state"]
    return result


def at_risk(conn: sqlite3.Connection, now: datetime = None) -> list:
    """Open orders registered in the system, riskiest first, with days left to the promise."""
    now = now or datetime.now()
    rows = rows_to_dicts(conn.execute(
        """SELECT o.order_id, o.order_status, o.order_purchase_timestamp, o.order_estimated_delivery_date,
                  c.customer_city, c.customer_state, p.late_risk, p.risk_level, p.risk_reasons,
                  p.promise_days, p.legacy_promise_days, p.eta_days
           FROM orders o
           JOIN customers c ON c.customer_id = o.customer_id
           JOIN order_predictions p ON p.order_id = o.order_id
           WHERE o.source = 'system' AND o.order_status IN ('created', 'approved', 'processing', 'invoiced', 'shipped')
           ORDER BY p.late_risk DESC""").fetchall())
    for r in rows:
        r["risk_reasons"] = json.loads(r["risk_reasons"] or "[]")
        r["status_label"] = STATUS_LABELS[r["order_status"]]
        r["days_left"] = (parse_ts(r["order_estimated_delivery_date"]).date() - now.date()).days
    return rows
