"""Look-ups used while registering an order: customers, sellers, products,
and the reference values (states, payment types, statuses)."""
import sqlite3

from ..config import BRAZIL_STATES, PAYMENT_TYPES
from ..db import row_to_dict, rows_to_dicts
from ..errors import NotFoundError
from .workflow import STATUS_LABELS


def meta(conn: sqlite3.Connection) -> dict:
    categories = conn.execute(
        "SELECT product_category_name_english AS name FROM category_translation ORDER BY 1"
    ).fetchall()
    return {
        "states": BRAZIL_STATES,
        "payment_types": PAYMENT_TYPES,
        "statuses": [{"value": k, "label": v} for k, v in STATUS_LABELS.items()],
        "categories": [r["name"] for r in categories],
    }


def search_customers(conn: sqlite3.Connection, q: str = "", limit: int = 20) -> list:
    """Find real customers (customer_unique_id), not per-order customer_ids.
    Matches the start of the id or the city name."""
    q = (q or "").strip().lower()
    rows = conn.execute(
        """
        SELECT c.customer_unique_id,
               c.customer_zip_code_prefix AS zip_code_prefix,
               c.customer_city            AS city,
               c.customer_state           AS state,
               COUNT(o.order_id)          AS orders,
               MAX(o.order_purchase_timestamp) AS last_order_at
        FROM customers c
        JOIN orders o ON o.customer_id = c.customer_id
        WHERE (:q = '' OR c.customer_unique_id LIKE :q || '%' OR c.customer_city LIKE :q || '%')
        GROUP BY c.customer_unique_id
        ORDER BY orders DESC, last_order_at DESC
        LIMIT :limit
        """,
        {"q": q, "limit": limit},
    ).fetchall()
    return rows_to_dicts(rows)


def search_sellers(conn: sqlite3.Connection, q: str = "", limit: int = 20) -> list:
    """Sellers with their headline numbers, biggest first."""
    q = (q or "").strip().lower()
    rows = conn.execute(
        """
        SELECT s.seller_id, s.seller_city AS city, s.seller_state AS state,
               COUNT(DISTINCT i.order_id)  AS orders,
               ROUND(COALESCE(SUM(i.price), 0), 2) AS revenue
        FROM sellers s
        LEFT JOIN order_items i ON i.seller_id = s.seller_id
        WHERE (:q = '' OR s.seller_id LIKE :q || '%' OR s.seller_city LIKE :q || '%')
        GROUP BY s.seller_id
        ORDER BY revenue DESC
        LIMIT :limit
        """,
        {"q": q, "limit": limit},
    ).fetchall()
    return rows_to_dicts(rows)


def get_seller(conn: sqlite3.Connection, seller_id: str) -> dict:
    row = conn.execute("SELECT * FROM sellers WHERE seller_id = ?", (seller_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"Seller {seller_id} not found")
    return dict(row)


def seller_products(conn: sqlite3.Connection, seller_id: str, q: str = "", limit: int = 50) -> list:
    """The seller's catalogue, learned from what they actually sold.
    Products in the dataset have no names, only a category and dimensions,
    so we show category + weight + a short id.
    avg_price / avg_freight are used to pre-fill the order form."""
    get_seller(conn, seller_id)
    q = (q or "").strip().lower()
    rows = conn.execute(
        """
        SELECT p.product_id,
               COALESCE(p.product_category_name_english, 'uncategorized') AS category,
               p.product_weight_g AS weight_g,
               p.product_length_cm AS length_cm, p.product_height_cm AS height_cm,
               p.product_width_cm AS width_cm,
               COUNT(*)                    AS units_sold,
               ROUND(AVG(i.price), 2)      AS avg_price,
               ROUND(AVG(i.freight_value), 2) AS avg_freight
        FROM order_items i
        JOIN products p ON p.product_id = i.product_id
        WHERE i.seller_id = :seller_id
          AND (:q = '' OR p.product_id LIKE :q || '%'
               OR p.product_category_name_english LIKE '%' || :q || '%')
        GROUP BY p.product_id
        ORDER BY units_sold DESC
        LIMIT :limit
        """,
        {"seller_id": seller_id, "q": q, "limit": limit},
    ).fetchall()
    return rows_to_dicts(rows)


def get_product(conn: sqlite3.Connection, product_id: str) -> dict:
    row = conn.execute("SELECT * FROM products WHERE product_id = ?", (product_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"Product {product_id} not found")
    return dict(row)


def delivery_reference(conn: sqlite3.Connection, state: str):
    """Historical promised vs. actual delivery days for a destination state."""
    return row_to_dict(conn.execute(
        "SELECT * FROM ref_state_delivery WHERE customer_state = ?", (state,)
    ).fetchone())
