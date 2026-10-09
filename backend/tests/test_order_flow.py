"""End-to-end business rules of Module 1, run against a copy of the real data."""
from datetime import datetime, timedelta

import pytest

from app.errors import BusinessRuleError, ValidationFailed
from app.services import invoices, orders, workflow
from conftest import make_order


def test_card_order_full_lifecycle(conn, two_sellers):
    s = two_sellers[0]
    created = orders.create_order(conn, make_order([{**s, "qty": 2}]))
    assert created["status"] == "approved"            # card payments are approved instantly
    oid = created["order_id"]

    # dataset convention kept: 2 units -> 2 rows
    assert conn.execute("SELECT COUNT(*) FROM order_items WHERE order_id = ?", (oid,)).fetchone()[0] == 2

    workflow.apply_action(conn, oid, "start_processing")
    inv = invoices.issue_invoice(conn, oid, s["seller_id"])
    assert inv["access_key_valid"] and inv["items_count"] == 2
    assert orders.get_order(conn, oid)["order_status"] == "invoiced"

    workflow.apply_action(conn, oid, "ship")
    workflow.apply_action(conn, oid, "deliver")
    detail = orders.get_order(conn, oid)
    assert detail["order_status"] == "delivered"
    assert [t["state"] for t in detail["timeline"]] == ["done"] * 6
    assert detail["delivery"]["on_time"] is True
    assert detail["actions"] == []


def test_cannot_ship_without_invoice(conn, two_sellers):
    oid = orders.create_order(conn, make_order([two_sellers[0]]))["order_id"]
    workflow.apply_action(conn, oid, "start_processing")
    with pytest.raises(BusinessRuleError):
        workflow.apply_action(conn, oid, "ship")


def test_boleto_waits_for_payment(conn, two_sellers):
    s = two_sellers[0]
    total = round(s["price"] + s["freight"], 2)
    res = orders.create_order(conn, make_order([s], [{"payment_type": "boleto", "installments": 1, "value": total}]))
    assert res["status"] == "created"
    assert any("Boleto" in w for w in res["warnings"])
    with pytest.raises(BusinessRuleError):
        workflow.apply_action(conn, res["order_id"], "start_processing")
    workflow.apply_action(conn, res["order_id"], "approve_payment")


def test_multi_seller_needs_one_invoice_per_seller(conn, two_sellers):
    a, b = two_sellers
    oid = orders.create_order(conn, make_order([a, b]))["order_id"]
    workflow.apply_action(conn, oid, "start_processing")
    invoices.issue_invoice(conn, oid, a["seller_id"])
    assert orders.get_order(conn, oid)["order_status"] == "processing"   # still waiting for seller b
    with pytest.raises(BusinessRuleError):
        invoices.issue_invoice(conn, oid, a["seller_id"])                # no duplicate NF-e
    invoices.issue_invoice(conn, oid, b["seller_id"])
    assert orders.get_order(conn, oid)["order_status"] == "invoiced"


def test_invoice_numbers_are_sequential_per_seller(conn, two_sellers):
    s = two_sellers[0]
    numbers = []
    for _ in range(3):
        oid = orders.create_order(conn, make_order([s]))["order_id"]
        workflow.apply_action(conn, oid, "start_processing")
        numbers.append(invoices.issue_invoice(conn, oid, s["seller_id"])["number"])
    assert numbers == [1, 2, 3]


def test_cancel_window_for_invoiced_orders(conn, two_sellers):
    s = two_sellers[0]
    t0 = datetime(2026, 10, 1, 10, 0, 0)

    # within 24h: the order and its NF-e are cancelled together
    oid = orders.create_order(conn, make_order([s]), now=t0)["order_id"]
    workflow.apply_action(conn, oid, "start_processing", now=t0)
    invoices.issue_invoice(conn, oid, s["seller_id"], now=t0)
    workflow.apply_action(conn, oid, "cancel", "customer gave up", now=t0 + timedelta(hours=2))
    detail = orders.get_order(conn, oid)
    assert detail["order_status"] == "canceled"
    assert detail["sellers"][0]["invoice"]["status"] == "canceled"

    # after 24h: blocked, a return invoice would be needed
    oid2 = orders.create_order(conn, make_order([s]), now=t0)["order_id"]
    workflow.apply_action(conn, oid2, "start_processing", now=t0)
    invoices.issue_invoice(conn, oid2, s["seller_id"], now=t0)
    with pytest.raises(BusinessRuleError, match="return invoice"):
        workflow.apply_action(conn, oid2, "cancel", "too late", now=t0 + timedelta(hours=30))


def test_cancel_requires_reason(conn, two_sellers):
    oid = orders.create_order(conn, make_order([two_sellers[0]]))["order_id"]
    with pytest.raises(BusinessRuleError):
        workflow.apply_action(conn, oid, "cancel")


def test_historical_orders_are_read_only(conn):
    oid = conn.execute("SELECT order_id FROM orders WHERE source = 'historical' LIMIT 1").fetchone()[0]
    assert orders.get_order(conn, oid)["actions"] == []
    with pytest.raises(BusinessRuleError):
        workflow.apply_action(conn, oid, "cancel", "x")


def test_payments_must_match_total(conn, two_sellers):
    s = two_sellers[0]
    with pytest.raises(ValidationFailed) as err:
        orders.create_order(conn, make_order([s], [{"payment_type": "credit_card", "installments": 1, "value": 1.0}]))
    assert "add up" in err.value.errors[0]


def test_installments_only_on_credit_card(conn, two_sellers):
    s = two_sellers[0]
    total = round(s["price"] + s["freight"], 2)
    with pytest.raises(ValidationFailed):
        orders.create_order(conn, make_order([s], [{"payment_type": "boleto", "installments": 3, "value": total}]))


def test_freight_above_price_is_flagged(conn, two_sellers):
    s = {**two_sellers[0], "price": 10.0, "freight": 25.0}
    res = orders.create_order(conn, make_order([s]))
    assert any("higher than the product price" in w for w in res["warnings"])


def test_returning_customer_keeps_unique_id(conn, two_sellers):
    uid = conn.execute("SELECT customer_unique_id FROM customers LIMIT 1").fetchone()[0]
    res = orders.create_order(conn, make_order([two_sellers[0]], customer={"customer_unique_id": uid}))
    detail = orders.get_order(conn, res["order_id"])
    assert detail["customer"]["customer_unique_id"] == uid
    assert detail["customer_previous_orders"] >= 1


def test_list_and_summary(conn, two_sellers):
    orders.create_order(conn, make_order([two_sellers[0]]))
    page = orders.list_orders(conn, source="system")
    assert page["total"] == 1 and page["items"][0]["source"] == "system"
    assert orders.list_orders(conn, state="SP", page_size=10)["total"] > 40000
    summary = orders.summary(conn)
    assert summary["orders"] == 99442 and summary["work_queue"]["approved"] == 1
