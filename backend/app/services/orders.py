"""Orders: list, detail, KPIs and registration of new orders."""
import json
import math
import sqlite3
import uuid
from datetime import datetime, timedelta
from typing import Optional

from ..config import INSTANT_PAYMENT_TYPES, MONEY_TOLERANCE
from ..db import row_to_dict, rows_to_dicts
from ..errors import ValidationFailed
from ..schemas import OrderCreate
from ..ml import predictor
from . import catalog
from .workflow import OPEN_STATUSES, STATUS_LABELS, allowed_actions, load_order, log_event, now_str, parse_ts


# ---------------------------------------------------------------------------
# List + KPIs
# ---------------------------------------------------------------------------

def list_orders(conn: sqlite3.Connection, status: Optional[str] = None, state: Optional[str] = None,
                source: Optional[str] = None, seller_id: Optional[str] = None, q: Optional[str] = None,
                date_from: Optional[str] = None, date_to: Optional[str] = None,
                page: int = 1, page_size: int = 25) -> dict:
    where, params = [], {}
    if status:
        where.append("o.order_status = :status"); params["status"] = status
    if state:
        where.append("c.customer_state = :state"); params["state"] = state
    if source:
        where.append("o.source = :source"); params["source"] = source
    if seller_id:
        where.append("EXISTS (SELECT 1 FROM order_items i WHERE i.order_id = o.order_id AND i.seller_id = :seller_id)")
        params["seller_id"] = seller_id
    if q:
        where.append("(o.order_id LIKE :q || '%' OR c.customer_unique_id LIKE :q || '%')")
        params["q"] = q.strip().lower()
    if date_from:
        where.append("o.order_purchase_timestamp >= :date_from"); params["date_from"] = date_from
    if date_to:
        where.append("o.order_purchase_timestamp < date(:date_to, '+1 day')"); params["date_to"] = date_to
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    base = f"FROM orders o JOIN customers c ON c.customer_id = o.customer_id {where_sql}"
    total = conn.execute(f"SELECT COUNT(*) {base}", params).fetchone()[0]

    params.update(limit=page_size, offset=(page - 1) * page_size)
    rows = rows_to_dicts(conn.execute(
        f"""SELECT o.order_id, o.order_status, o.source, o.order_purchase_timestamp,
                   o.order_estimated_delivery_date, o.order_delivered_customer_date,
                   c.customer_unique_id, c.customer_city, c.customer_state
            {base}
            ORDER BY o.order_purchase_timestamp DESC
            LIMIT :limit OFFSET :offset""",
        params,
    ).fetchall())

    # Totals only for the 25 orders on this page (fast, instead of aggregating 112k items)
    if rows:
        ids = [r["order_id"] for r in rows]
        marks = ",".join("?" * len(ids))
        totals = {r["order_id"]: dict(r) for r in conn.execute(
            f"""SELECT order_id, COUNT(*) AS items, COUNT(DISTINCT seller_id) AS sellers,
                       ROUND(SUM(price), 2) AS products_total, ROUND(SUM(freight_value), 2) AS freight_total
                FROM order_items WHERE order_id IN ({marks}) GROUP BY order_id""", ids)}
        for r in rows:
            t = totals.get(r["order_id"], {})
            r["items"] = t.get("items", 0)
            r["sellers"] = t.get("sellers", 0)
            r["total"] = round((t.get("products_total") or 0) + (t.get("freight_total") or 0), 2)
            r["status_label"] = STATUS_LABELS.get(r["order_status"], r["order_status"])

    return {"items": rows, "total": total, "page": page, "page_size": page_size,
            "pages": max(1, math.ceil(total / page_size))}


def summary(conn: sqlite3.Connection) -> dict:
    o = dict(conn.execute(
        """SELECT COUNT(*) AS orders,
                  SUM(source = 'system') AS system_orders,
                  MIN(CASE WHEN source = 'historical' THEN order_purchase_timestamp END) AS dataset_from,
                  MAX(CASE WHEN source = 'historical' THEN order_purchase_timestamp END) AS dataset_to
           FROM orders""").fetchone())
    money = dict(conn.execute(
        "SELECT ROUND(SUM(price), 2) AS gmv, ROUND(SUM(freight_value), 2) AS freight FROM order_items").fetchone())
    by_status = {r["order_status"]: r["n"] for r in conn.execute(
        "SELECT order_status, COUNT(*) AS n FROM orders GROUP BY order_status")}
    # the work queue: system orders waiting for someone to act
    queue = {r["order_status"]: r["n"] for r in conn.execute(
        f"""SELECT order_status, COUNT(*) AS n FROM orders
            WHERE source = 'system' AND order_status IN ({",".join("?" * len(OPEN_STATUSES))})
            GROUP BY order_status""", OPEN_STATUSES)}
    return {
        **o, **money,
        "avg_order_value": round((money["gmv"] + money["freight"]) / o["orders"], 2) if o["orders"] else 0,
        "by_status": by_status,
        "work_queue": {s: queue.get(s, 0) for s in OPEN_STATUSES},
    }


# ---------------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------------

def get_order(conn: sqlite3.Connection, order_id: str) -> dict:
    order = load_order(conn, order_id)
    data = dict(order)
    data["status_label"] = STATUS_LABELS.get(order["order_status"], order["order_status"])
    data["customer"] = row_to_dict(conn.execute(
        "SELECT * FROM customers WHERE customer_id = ?", (order["customer_id"],)).fetchone())
    data["customer_previous_orders"] = conn.execute(
        """SELECT COUNT(*) - 1 FROM orders o JOIN customers c ON c.customer_id = o.customer_id
           WHERE c.customer_unique_id = ?""", (data["customer"]["customer_unique_id"],)).fetchone()[0]

    # one row per unit in the table -> group back into lines with a quantity
    data["items"] = rows_to_dicts(conn.execute(
        """SELECT i.product_id, i.seller_id, s.seller_city, s.seller_state,
                  COALESCE(p.product_category_name_english, 'uncategorized') AS category,
                  p.product_weight_g AS weight_g,
                  COUNT(*) AS quantity, i.price AS unit_price, i.freight_value AS unit_freight,
                  ROUND(SUM(i.price), 2) AS line_total, ROUND(SUM(i.freight_value), 2) AS line_freight
           FROM order_items i
           LEFT JOIN products p ON p.product_id = i.product_id
           LEFT JOIN sellers s ON s.seller_id = i.seller_id
           WHERE i.order_id = ?
           GROUP BY i.product_id, i.seller_id, i.price, i.freight_value
           ORDER BY MIN(i.order_item_id)""", (order_id,)).fetchall())
    products_total = round(sum(i["line_total"] for i in data["items"]), 2)
    freight_total = round(sum(i["line_freight"] for i in data["items"]), 2)
    data["totals"] = {"products": products_total, "freight": freight_total,
                      "total": round(products_total + freight_total, 2),
                      "freight_share": round(freight_total / products_total * 100, 1) if products_total else None}

    data["payments"] = rows_to_dicts(conn.execute(
        "SELECT * FROM order_payments WHERE order_id = ? ORDER BY payment_sequential", (order_id,)).fetchall())
    data["paid_total"] = round(sum(p["payment_value"] for p in data["payments"]), 2)
    data["reviews"] = rows_to_dicts(conn.execute(
        "SELECT * FROM order_reviews WHERE order_id = ? ORDER BY review_creation_date", (order_id,)).fetchall())
    data["events"] = rows_to_dicts(conn.execute(
        "SELECT * FROM order_events WHERE order_id = ? ORDER BY event_id", (order_id,)).fetchall())
    data["sellers"] = _seller_invoice_status(conn, order)
    data["timeline"] = _timeline(order, data["events"])
    data["delivery"] = _delivery_performance(order)
    data["actions"] = allowed_actions(order)
    pred = row_to_dict(conn.execute("SELECT * FROM order_predictions WHERE order_id = ?", (order_id,)).fetchone())
    if pred:
        pred["risk_reasons"] = json.loads(pred["risk_reasons"] or "[]")
    data["prediction"] = pred
    return data


def _seller_invoice_status(conn: sqlite3.Connection, order) -> list:
    """For each seller in the order: their share of the order and their NF-e (if any)."""
    sellers = rows_to_dicts(conn.execute(
        """SELECT i.seller_id, s.seller_city AS city, s.seller_state AS state,
                  COUNT(*) AS items, ROUND(SUM(i.price) + SUM(i.freight_value), 2) AS subtotal
           FROM order_items i JOIN sellers s ON s.seller_id = i.seller_id
           WHERE i.order_id = ? GROUP BY i.seller_id ORDER BY MIN(i.order_item_id)""",
        (order["order_id"],)).fetchall())
    for s in sellers:
        s["invoice"] = row_to_dict(conn.execute(
            """SELECT invoice_id, number, series, access_key, status, issued_at FROM invoices
               WHERE order_id = ? AND seller_id = ? ORDER BY invoice_id DESC LIMIT 1""",
            (order["order_id"], s["seller_id"])).fetchone())
        active = s["invoice"] is not None and s["invoice"]["status"] == "authorized"
        s["can_issue_invoice"] = (order["source"] == "system" and order["order_status"] == "processing"
                                  and not active)
    return sellers


def _timeline(order, events: list) -> list:
    first_event = {}
    for e in events:
        first_event.setdefault(e["status"], e["occurred_at"])

    steps = [
        ("purchased", "Order placed", order["order_purchase_timestamp"]),
        ("approved", "Payment approved", order["order_approved_at"]),
        ("processing", "Seller processing", first_event.get("processing")),
        ("invoiced", "NF-e issued", first_event.get("invoiced")),
        ("shipped", "Handed to carrier", order["order_delivered_carrier_date"]),
        ("delivered", "Delivered", order["order_delivered_customer_date"]),
    ]
    # the furthest step that has really happened
    reached = max((i for i, s in enumerate(steps) if s[2]), default=0)
    if order["order_status"] in [s[0] for s in steps]:
        reached = max(reached, [s[0] for s in steps].index(order["order_status"]))
    stopped = order["order_status"] in ("canceled", "unavailable")

    out = []
    for i, (key, label, at) in enumerate(steps):
        if i <= reached:
            state = "done"
        elif stopped:
            state = "skipped"
        else:
            state = "current" if i == reached + 1 else "pending"
        out.append({"key": key, "label": label, "at": at, "state": state,
                    "note": "not recorded in the dataset" if state == "done" and not at else None})
    if stopped:
        at = order["canceled_at"] or first_event.get(order["order_status"])
        out.append({"key": order["order_status"], "label": STATUS_LABELS[order["order_status"]],
                    "at": at, "state": "stopped", "note": order["cancel_reason"]})
    return out


def _delivery_performance(order) -> dict:
    promised = parse_ts(order["order_estimated_delivery_date"])
    delivered = parse_ts(order["order_delivered_customer_date"])
    purchased = parse_ts(order["order_purchase_timestamp"])
    out = {"promised_date": order["order_estimated_delivery_date"],
           "promised_days": (promised.date() - purchased.date()).days if promised else None}
    if delivered and promised:
        diff = (delivered.date() - promised.date()).days
        out.update(delivered_days=round((delivered - purchased).total_seconds() / 86400, 1),
                   days_vs_promise=diff, on_time=diff <= 0)
    return out


# ---------------------------------------------------------------------------
# Registration of a new order
# ---------------------------------------------------------------------------

def resolve_address(conn: sqlite3.Connection, cust) -> tuple:
    """Returns (address, error). A returning customer keeps their latest address
    unless a new one is given; a new customer must give zip, city and state."""
    if cust.customer_unique_id:
        known = conn.execute(
            """SELECT c.* FROM customers c JOIN orders o ON o.customer_id = c.customer_id
               WHERE c.customer_unique_id = ? ORDER BY o.order_purchase_timestamp DESC LIMIT 1""",
            (cust.customer_unique_id,)).fetchone()
        if known is None:
            return None, f"Customer {cust.customer_unique_id} not found"
        return {"zip": cust.zip_code_prefix or known["customer_zip_code_prefix"],
                "city": (cust.city or known["customer_city"]).lower(),
                "state": cust.state or known["customer_state"]}, None
    if not (cust.zip_code_prefix and cust.city and cust.state):
        return None, "New customer needs zip_code_prefix, city and state"
    return {"zip": cust.zip_code_prefix, "city": cust.city.strip().lower(), "state": cust.state}, None


def create_order(conn: sqlite3.Connection, payload: OrderCreate, now: datetime = None) -> dict:
    now = now or datetime.now()
    errors, warnings = [], []

    # 1. customer: reuse a known person or register a new one
    address, error = resolve_address(conn, payload.customer)
    if error:
        errors.append(error)
    cust = payload.customer

    # 2. items: products and sellers must exist
    for n, line in enumerate(payload.items, start=1):
        if not conn.execute("SELECT 1 FROM products WHERE product_id = ?", (line.product_id,)).fetchone():
            errors.append(f"Line {n}: product {line.product_id} not found")
        if not conn.execute("SELECT 1 FROM sellers WHERE seller_id = ?", (line.seller_id,)).fetchone():
            errors.append(f"Line {n}: seller {line.seller_id} not found")
        if line.freight_value > line.unit_price:
            warnings.append(
                f"Line {n}: freight (R$ {line.freight_value:.2f}) is higher than the product price "
                f"(R$ {line.unit_price:.2f}). 4,124 historical items had this problem.")

    products_total = round(sum(l.unit_price * l.quantity for l in payload.items), 2)
    freight_total = round(sum(l.freight_value * l.quantity for l in payload.items), 2)
    order_total = round(products_total + freight_total, 2)

    # 3. payments: installments only on credit card, and they must cover the total exactly
    for n, p in enumerate(payload.payments, start=1):
        if p.payment_type != "credit_card" and p.installments != 1:
            errors.append(f"Payment {n}: only credit cards can be split into installments")
    paid = round(sum(p.value for p in payload.payments), 2)
    if abs(paid - order_total) > MONEY_TOLERANCE:
        errors.append(f"Payments add up to R$ {paid:.2f} but the order total is R$ {order_total:.2f}")

    if errors:
        raise ValidationFailed(errors)

    sellers_in_order = {l.seller_id for l in payload.items}
    if len(sellers_in_order) > 1:
        warnings.append(f"{len(sellers_in_order)} sellers in this order: each one will issue its own NF-e.")
    instant = all(p.payment_type in INSTANT_PAYMENT_TYPES for p in payload.payments)
    if not instant:
        warnings.append("Boleto payment: the order waits for payment confirmation "
                        "(historically a median of 29 hours).")

    # 4. promised delivery date. With the Module 2 models trained, the promise comes from
    #    the ETA model; without them, we fall back to Olist's historical promise per state.
    quote = predictor.quote(conn, address["state"], address["zip"],
                            [l.model_dump() for l in payload.items],
                            [p.payment_type for p in payload.payments], now)
    if quote["available"]:
        promised_days, promise_source = quote["promise_days"], "model"
        _model_warnings(quote, payload, warnings)
    else:
        ref = catalog.delivery_reference(conn, address["state"])
        promised_days, promise_source = (math.ceil(ref["median_promised_days"]) if ref else 24), "olist_history"
    estimated = (now + timedelta(days=promised_days)).replace(hour=0, minute=0, second=0, microsecond=0)

    order_id, customer_id = uuid.uuid4().hex, uuid.uuid4().hex
    unique_id = cust.customer_unique_id or uuid.uuid4().hex
    ts = now_str(now)

    with conn:  # all inserts succeed together or none are saved
        conn.execute(
            """INSERT INTO customers (customer_id, customer_unique_id, customer_zip_code_prefix,
                                      customer_city, customer_state) VALUES (?, ?, ?, ?, ?)""",
            (customer_id, unique_id, address["zip"], address["city"], address["state"]))
        conn.execute(
            """INSERT INTO orders (order_id, customer_id, order_status, order_purchase_timestamp,
                                   order_estimated_delivery_date, source)
               VALUES (?, ?, 'created', ?, ?, 'system')""",
            (order_id, customer_id, ts, now_str(estimated)))
        log_event(conn, order_id, "created", f"Order registered, total R$ {order_total:.2f}", ts)

        item_no = 0
        for line in payload.items:
            for _ in range(line.quantity):          # dataset convention: one row per unit
                item_no += 1
                conn.execute(
                    """INSERT INTO order_items (order_id, order_item_id, product_id, seller_id, price, freight_value)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (order_id, item_no, line.product_id, line.seller_id,
                     round(line.unit_price, 2), round(line.freight_value, 2)))
        for seq, p in enumerate(payload.payments, start=1):
            conn.execute(
                """INSERT INTO order_payments (order_id, payment_sequential, payment_type,
                                               payment_installments, payment_value) VALUES (?, ?, ?, ?, ?)""",
                (order_id, seq, p.payment_type, p.installments, round(p.value, 2)))

        if quote["available"]:
            conn.execute(
                """INSERT INTO order_predictions (order_id, eta_days, promise_days, promise_source,
                       legacy_promise_days, late_risk, risk_level, risk_reasons, distance_km,
                       model_trained_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (order_id, quote["eta_days"], promised_days, promise_source, quote["legacy_promise_days"],
                 quote["risk"]["probability"], quote["risk"]["level"], json.dumps(quote["risk"]["reasons"]),
                 quote["distance_km"], predictor.metrics()["trained_at"], ts))

        status = "created"
        if instant:  # card / voucher payments are confirmed on the spot
            status = "approved"
            conn.execute("UPDATE orders SET order_status = 'approved', order_approved_at = ? WHERE order_id = ?",
                         (ts, order_id))
            log_event(conn, order_id, "approved", "Payment confirmed instantly", ts)

    return {"order_id": order_id, "status": status, "total": order_total,
            "estimated_delivery_date": now_str(estimated), "promised_days": promised_days,
            "promise_source": promise_source,
            "late_risk": quote["risk"] if quote["available"] else None,
            "warnings": warnings}


FREIGHT_ALERT_RATIO = 1.5   # entered freight 50% above the model's estimate (and R$ 5+ above) is flagged


def _model_warnings(quote: dict, payload: OrderCreate, warnings: list) -> None:
    risk = quote["risk"]
    if risk["level"] == "high":
        why = "; ".join(risk["reasons"]) or "a mix of route, seller and season"
        warnings.append(f"High late-delivery risk ({risk['probability']:.0%}): {why}.")
    for est in quote["freight_estimates"]:
        line = payload.items[est["line"]]
        if line.freight_value > est["per_unit"] * FREIGHT_ALERT_RATIO and line.freight_value - est["per_unit"] > 5:
            warnings.append(f"Line {est['line'] + 1}: freight R$ {line.freight_value:.2f} is "
                            f"{line.freight_value / est['per_unit']:.1f}x the expected R$ {est['per_unit']:.2f} for this route.")
