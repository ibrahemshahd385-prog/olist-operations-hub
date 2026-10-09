"""HTTP endpoints for orders. Each function only translates HTTP <-> service call;
all business logic lives in app/services."""
import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, Query

from ..db import get_conn
from ..schemas import ActionIn, InvoiceIssueIn, OrderCreate
from ..services import invoices, orders, workflow

router = APIRouter(prefix="/api/orders", tags=["Orders & Invoices"])


@router.get("")
def list_orders(
    status: Optional[str] = None,
    state: Optional[str] = None,
    source: Optional[str] = None,
    seller_id: Optional[str] = None,
    q: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    conn: sqlite3.Connection = Depends(get_conn),
):
    return orders.list_orders(conn, status, state, source, seller_id, q, date_from, date_to, page, page_size)


@router.get("/summary")
def orders_summary(conn: sqlite3.Connection = Depends(get_conn)):
    return orders.summary(conn)


@router.post("", status_code=201)
def create_order(payload: OrderCreate, conn: sqlite3.Connection = Depends(get_conn)):
    return orders.create_order(conn, payload)


@router.get("/{order_id}")
def get_order(order_id: str, conn: sqlite3.Connection = Depends(get_conn)):
    return orders.get_order(conn, order_id)


@router.post("/{order_id}/actions/{action}")
def run_action(order_id: str, action: str, body: ActionIn, conn: sqlite3.Connection = Depends(get_conn)):
    """approve_payment | start_processing | ship | deliver | cancel | mark_unavailable"""
    workflow.apply_action(conn, order_id, action, body.note)
    return orders.get_order(conn, order_id)


@router.post("/{order_id}/invoices", status_code=201)
def issue_invoice(order_id: str, body: InvoiceIssueIn, conn: sqlite3.Connection = Depends(get_conn)):
    return invoices.issue_invoice(conn, order_id, body.seller_id)
