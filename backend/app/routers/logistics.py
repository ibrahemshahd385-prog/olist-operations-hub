"""HTTP endpoints for Module 2 (smart logistics)."""
import sqlite3

from fastapi import APIRouter, Depends

from ..db import get_conn
from ..schemas import QuoteIn
from ..services import logistics

router = APIRouter(prefix="/api/logistics", tags=["Smart logistics"])


@router.get("/overview")
def overview(conn: sqlite3.Connection = Depends(get_conn)):
    """How the models perform on orders they never saw, plus the busiest delivery lanes."""
    return logistics.overview(conn)


@router.post("/quote")
def quote(payload: QuoteIn, conn: sqlite3.Connection = Depends(get_conn)):
    """Promise date, late risk and freight estimates for an order that is being typed."""
    return logistics.quote(conn, payload)


@router.get("/at-risk")
def at_risk(conn: sqlite3.Connection = Depends(get_conn)):
    return logistics.at_risk(conn)
