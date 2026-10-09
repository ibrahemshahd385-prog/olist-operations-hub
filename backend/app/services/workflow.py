"""Order lifecycle as a state machine.

The dataset contains 8 statuses. Reading which timestamps are filled for each
status gives the real flow Olist used:

    created -> approved -> processing -> invoiced -> shipped -> delivered
                  |            |            |
                  +------------+------------+--> canceled
                  +------------+---------------> unavailable

Each user action below is allowed only from specific statuses. That is the
whole point of a state machine: an order can never be "shipped" before it is
"invoiced", because the action simply does not exist in that state.
"""
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

from ..errors import BusinessRuleError, NotFoundError

NFE_CANCEL_WINDOW_HOURS = 24  # general NF-e rule: cancellation allowed within 24h of authorisation

STATUS_LABELS = {
    "created": "Awaiting payment",
    "approved": "Payment approved",
    "processing": "Processing",
    "invoiced": "Invoiced (NF-e)",
    "shipped": "With carrier",
    "delivered": "Delivered",
    "canceled": "Canceled",
    "unavailable": "Unavailable",
}

OPEN_STATUSES = ("created", "approved", "processing", "invoiced", "shipped")

# action -> (statuses it can start from, status it leads to, timestamp column to fill, button label)
ACTIONS = {
    "approve_payment": (("created",), "approved", "order_approved_at", "Confirm payment"),
    "start_processing": (("approved",), "processing", None, "Start processing"),
    # issuing invoices is per seller and lives in invoices.py; when the last
    # seller's NF-e is issued the order moves to "invoiced" automatically.
    "ship": (("invoiced",), "shipped", "order_delivered_carrier_date", "Hand over to carrier"),
    "deliver": (("shipped",), "delivered", "order_delivered_customer_date", "Confirm delivery"),
    "cancel": (("created", "approved", "processing", "invoiced"), "canceled", "canceled_at", "Cancel order"),
    "mark_unavailable": (("approved", "processing"), "unavailable", None, "Mark unavailable"),
}


def now_str(now: Optional[datetime] = None) -> str:
    return (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")


def parse_ts(value: Optional[str]) -> Optional[datetime]:
    return datetime.strptime(value[:19], "%Y-%m-%d %H:%M:%S") if value else None


def log_event(conn: sqlite3.Connection, order_id: str, status: str, note: str = None, at: str = None) -> None:
    conn.execute(
        "INSERT INTO order_events (order_id, status, occurred_at, note) VALUES (?, ?, ?, ?)",
        (order_id, status, at or now_str(), note),
    )


def load_order(conn: sqlite3.Connection, order_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"Order {order_id} not found")
    return row


def allowed_actions(order) -> list:
    """Buttons the screen should show for this order right now."""
    if order["source"] == "historical":
        return []  # Kaggle records are kept read-only so the analysis stays truthful
    return [
        {"action": name, "label": label}
        for name, (from_states, _to, _col, label) in ACTIONS.items()
        if order["order_status"] in from_states
    ]


def apply_action(conn: sqlite3.Connection, order_id: str, action: str,
                 note: str = None, now: datetime = None) -> dict:
    if action not in ACTIONS:
        raise BusinessRuleError(f"Unknown action '{action}'")
    order = load_order(conn, order_id)
    if order["source"] == "historical":
        raise BusinessRuleError("Historical orders from the dataset are read-only.")

    from_states, to_status, ts_column, _label = ACTIONS[action]
    current = order["order_status"]
    if current not in from_states:
        raise BusinessRuleError(
            f"Cannot '{action}' an order that is '{current}'. "
            f"Allowed from: {', '.join(from_states)}."
        )

    timestamp = now_str(now)
    with conn:  # one transaction: either everything below is saved, or nothing
        if action == "cancel":
            if not note:
                raise BusinessRuleError("A cancellation reason is required.")
            _cancel_invoices_if_allowed(conn, order_id, now or datetime.now())
            conn.execute("UPDATE orders SET cancel_reason = ? WHERE order_id = ?", (note, order_id))

        conn.execute("UPDATE orders SET order_status = ? WHERE order_id = ?", (to_status, order_id))
        if ts_column:
            conn.execute(f"UPDATE orders SET {ts_column} = ? WHERE order_id = ?", (timestamp, order_id))
        log_event(conn, order_id, to_status, note, timestamp)

    return {"order_id": order_id, "status": to_status}


def _cancel_invoices_if_allowed(conn: sqlite3.Connection, order_id: str, now: datetime) -> None:
    """An authorised NF-e can only be cancelled within the legal window.
    After that, the seller must issue a return invoice instead, so we block."""
    invoices = conn.execute(
        "SELECT invoice_id, number, issued_at FROM invoices WHERE order_id = ? AND status = 'authorized'",
        (order_id,),
    ).fetchall()
    limit = timedelta(hours=NFE_CANCEL_WINDOW_HOURS)
    for inv in invoices:
        if now - parse_ts(inv["issued_at"]) > limit:
            raise BusinessRuleError(
                f"NF-e nº {inv['number']} was issued more than {NFE_CANCEL_WINDOW_HOURS}h ago and can no "
                "longer be cancelled. A return invoice (nota de devolução) is required instead."
            )
    for inv in invoices:
        conn.execute(
            "UPDATE invoices SET status = 'canceled', canceled_at = ? WHERE invoice_id = ?",
            (now_str(now), inv["invoice_id"]),
        )
        log_event(conn, order_id, "invoice_canceled", f"NF-e nº {inv['number']} canceled", now_str(now))
