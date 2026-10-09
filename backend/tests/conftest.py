"""Shared test setup: every test gets a fresh in-memory copy of the real database,
so tests never change data/olist.db and never affect each other."""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import DB_PATH  # noqa: E402
from app.db import ensure_schema  # noqa: E402
from app.schemas import OrderCreate  # noqa: E402

_source = None


@pytest.fixture()
def conn():
    global _source
    if not DB_PATH.exists():
        pytest.skip("Build the database first: python -m scripts.build_database")
    if _source is None:  # load the file into memory once per test run
        _source = sqlite3.connect(":memory:", check_same_thread=False)
        disk = sqlite3.connect(DB_PATH)
        disk.backup(_source)
        disk.close()
    c = sqlite3.connect(":memory:", check_same_thread=False)
    _source.backup(c)
    c.row_factory = sqlite3.Row
    ensure_schema(c)
    yield c
    c.close()


@pytest.fixture()
def two_sellers(conn):
    """Two real (seller, product) pairs from different sellers."""
    rows = conn.execute(
        """SELECT seller_id, product_id, ROUND(AVG(price), 2) AS price, ROUND(AVG(freight_value), 2) AS freight
           FROM order_items GROUP BY seller_id, product_id ORDER BY COUNT(*) DESC LIMIT 50"""
    ).fetchall()
    first = rows[0]
    second = next(r for r in rows if r["seller_id"] != first["seller_id"])
    return [dict(first), dict(second)]


def make_order(lines, payments=None, customer=None) -> OrderCreate:
    total = round(sum(l["price"] * l.get("qty", 1) + l["freight"] * l.get("qty", 1) for l in lines), 2)
    return OrderCreate.model_validate({
        "customer": customer or {"zip_code_prefix": "01310", "city": "sao paulo", "state": "SP"},
        "items": [{"product_id": l["product_id"], "seller_id": l["seller_id"], "unit_price": l["price"],
                   "quantity": l.get("qty", 1), "freight_value": l["freight"]} for l in lines],
        "payments": payments or [{"payment_type": "credit_card", "installments": 3, "value": total}],
    })
