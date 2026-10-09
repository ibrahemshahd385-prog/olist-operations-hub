"""HTTP endpoints for Module 3 (seller performance)."""
import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, Query

from ..db import get_conn
from ..services import sellers

router = APIRouter(prefix="/api/sellers", tags=["Seller performance"])


@router.get("")
def list_sellers(
    q: Optional[str] = None,
    tier: Optional[str] = None,
    state: Optional[str] = None,
    key_only: bool = False,
    alert: Optional[str] = None,
    credit_ready: bool = False,
    sort: str = "revenue",
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    conn: sqlite3.Connection = Depends(get_conn),
):
    return sellers.list_sellers(conn, q, tier, state, key_only, alert, credit_ready, sort, page, page_size)


@router.get("/summary")
def sellers_summary(conn: sqlite3.Connection = Depends(get_conn)):
    """Health tiers, key-account share, alert counts and how the score is built."""
    return sellers.summary(conn)


@router.get("/{seller_id}")
def get_seller(seller_id: str, conn: sqlite3.Connection = Depends(get_conn)):
    """Scorecard, monthly sales, weak spots and recommended next steps for one seller."""
    return sellers.get_seller(conn, seller_id)
