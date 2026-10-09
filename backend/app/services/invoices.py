"""NF-e (Nota Fiscal Eletrônica) simulator.

In Brazil every sale that is shipped needs an authorised NF-e, and its printed
summary (the DANFE) must travel with the package. This module reproduces the
parts of that process that matter for operations:

  * one invoice per seller in the order (each seller is a separate issuer)
  * sequential numbering per seller and series
  * the real 44-digit access key format with its módulo-11 check digit

It does NOT talk to SEFAZ (the tax authority), so every invoice is marked
"SEM VALOR FISCAL" (no tax value) - exactly how test-environment NF-e are labelled.

Access key layout (44 digits):
  cUF(2) AAMM(4) CNPJ(14) model(2) series(3) number(9) emission type(1) code(8) DV(1)
"""
import secrets
import sqlite3
from datetime import datetime

from ..config import IBGE_STATE_CODES, NFE_EMISSION_TYPE, NFE_MODEL, NFE_SERIES
from ..db import row_to_dict, rows_to_dicts
from ..errors import BusinessRuleError, NotFoundError
from .workflow import load_order, log_event, now_str


def mod11_check_digit(digits: str) -> str:
    """Weights 2,3,4,...,9 applied from right to left (repeating), sum, divide by 11.
    DV = 11 - remainder; if the remainder is 0 or 1 the DV is 0."""
    total, weight = 0, 2
    for d in reversed(digits):
        total += int(d) * weight
        weight = 2 if weight == 9 else weight + 1
    remainder = total % 11
    return "0" if remainder in (0, 1) else str(11 - remainder)


def build_access_key(state: str, issued: datetime, cnpj: str, series: int, number: int,
                     numeric_code: str, model: str = NFE_MODEL,
                     emission_type: str = NFE_EMISSION_TYPE) -> str:
    body = (
        IBGE_STATE_CODES[state]
        + issued.strftime("%y%m")
        + cnpj.zfill(14)
        + model
        + str(series).zfill(3)
        + str(number).zfill(9)
        + emission_type
        + numeric_code.zfill(8)
    )
    assert len(body) == 43, body
    return body + mod11_check_digit(body)


def is_valid_access_key(key: str) -> bool:
    return len(key) == 44 and key.isdigit() and mod11_check_digit(key[:43]) == key[43]


def _random_numeric_code(number: int) -> str:
    # the 8-digit code must not repeat the invoice number (official rule)
    while True:
        code = str(secrets.randbelow(10**8)).zfill(8)
        if code != str(number).zfill(8):
            return code


def issue_invoice(conn: sqlite3.Connection, order_id: str, seller_id: str, now: datetime = None) -> dict:
    order = load_order(conn, order_id)
    if order["source"] == "historical":
        raise BusinessRuleError("Historical orders from the dataset are read-only.")
    if order["order_status"] != "processing":
        raise BusinessRuleError(
            f"An NF-e can only be issued while the order is 'processing' (it is '{order['order_status']}')."
        )

    seller = conn.execute("SELECT * FROM sellers WHERE seller_id = ?", (seller_id,)).fetchone()
    if seller is None:
        raise NotFoundError(f"Seller {seller_id} not found")

    totals = conn.execute(
        """SELECT COUNT(*) AS items, ROUND(SUM(price), 2) AS products, ROUND(SUM(freight_value), 2) AS freight
           FROM order_items WHERE order_id = ? AND seller_id = ?""",
        (order_id, seller_id),
    ).fetchone()
    if totals["items"] == 0:
        raise BusinessRuleError("This seller has no items in the order.")

    already = conn.execute(
        "SELECT number FROM invoices WHERE order_id = ? AND seller_id = ? AND status = 'authorized'",
        (order_id, seller_id),
    ).fetchone()
    if already:
        raise BusinessRuleError(f"This seller already issued NF-e nº {already['number']} for this order.")

    issued = now or datetime.now()
    with conn:
        number = conn.execute(
            "SELECT COALESCE(MAX(number), 0) + 1 FROM invoices WHERE seller_id = ? AND series = ?",
            (seller_id, NFE_SERIES),
        ).fetchone()[0]
        key = build_access_key(seller["seller_state"], issued, seller["cnpj_simulated"],
                               NFE_SERIES, number, _random_numeric_code(number))
        cur = conn.execute(
            """INSERT INTO invoices (order_id, seller_id, number, series, access_key, status, issued_at,
                                     products_total, freight_total, total, items_count)
               VALUES (?, ?, ?, ?, ?, 'authorized', ?, ?, ?, ?, ?)""",
            (order_id, seller_id, number, NFE_SERIES, key, now_str(issued),
             totals["products"], totals["freight"], round(totals["products"] + totals["freight"], 2),
             totals["items"]),
        )
        log_event(conn, order_id, "invoice_issued",
                  f"NF-e nº {number} issued by seller {seller_id[:8]}", now_str(issued))

        # when every seller in the order has a valid NF-e, the order is "invoiced"
        missing = conn.execute(
            """SELECT COUNT(DISTINCT i.seller_id) FROM order_items i
               WHERE i.order_id = ? AND NOT EXISTS (
                   SELECT 1 FROM invoices v WHERE v.order_id = i.order_id
                   AND v.seller_id = i.seller_id AND v.status = 'authorized')""",
            (order_id,),
        ).fetchone()[0]
        if missing == 0:
            conn.execute("UPDATE orders SET order_status = 'invoiced' WHERE order_id = ?", (order_id,))
            log_event(conn, order_id, "invoiced", "All sellers invoiced - ready to ship", now_str(issued))

    return get_invoice(conn, cur.lastrowid)


def get_invoice(conn: sqlite3.Connection, invoice_id: int) -> dict:
    """Everything the DANFE (printable invoice) needs: issuer, recipient, items, totals."""
    inv = row_to_dict(conn.execute("SELECT * FROM invoices WHERE invoice_id = ?", (invoice_id,)).fetchone())
    if inv is None:
        raise NotFoundError(f"Invoice {invoice_id} not found")
    inv["issuer"] = row_to_dict(conn.execute(
        "SELECT seller_id, seller_city AS city, seller_state AS state, seller_zip_code_prefix AS zip_code_prefix, "
        "cnpj_simulated AS cnpj FROM sellers WHERE seller_id = ?", (inv["seller_id"],)).fetchone())
    inv["recipient"] = row_to_dict(conn.execute(
        """SELECT c.customer_unique_id, c.customer_city AS city, c.customer_state AS state,
                  c.customer_zip_code_prefix AS zip_code_prefix
           FROM orders o JOIN customers c ON c.customer_id = o.customer_id WHERE o.order_id = ?""",
        (inv["order_id"],)).fetchone())
    inv["items"] = rows_to_dicts(conn.execute(
        """SELECT i.product_id, COALESCE(p.product_category_name_english, 'uncategorized') AS category,
                  COUNT(*) AS quantity, i.price AS unit_price, ROUND(SUM(i.price), 2) AS total,
                  ROUND(SUM(i.freight_value), 2) AS freight
           FROM order_items i LEFT JOIN products p ON p.product_id = i.product_id
           WHERE i.order_id = ? AND i.seller_id = ?
           GROUP BY i.product_id, i.price ORDER BY MIN(i.order_item_id)""",
        (inv["order_id"], inv["seller_id"])).fetchall())
    inv["access_key_valid"] = is_valid_access_key(inv["access_key"])
    inv["interstate"] = inv["issuer"]["state"] != inv["recipient"]["state"]
    return inv
