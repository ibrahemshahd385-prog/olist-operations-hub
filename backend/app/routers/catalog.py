"""Look-up endpoints used by the order form, plus invoice retrieval."""
import sqlite3

from fastapi import APIRouter, Depends, Query

from ..db import get_conn
from ..services import catalog, invoices

router = APIRouter(prefix="/api", tags=["Catalog"])


@router.get("/meta")
def meta(conn: sqlite3.Connection = Depends(get_conn)):
    return catalog.meta(conn)


@router.get("/customers/search")
def search_customers(q: str = "", limit: int = Query(20, ge=1, le=50),
                     conn: sqlite3.Connection = Depends(get_conn)):
    return catalog.search_customers(conn, q, limit)


@router.get("/sellers/search")
def search_sellers(q: str = "", limit: int = Query(20, ge=1, le=50),
                   conn: sqlite3.Connection = Depends(get_conn)):
    return catalog.search_sellers(conn, q, limit)


@router.get("/sellers/{seller_id}/products")
def seller_products(seller_id: str, q: str = "", limit: int = Query(50, ge=1, le=100),
                    conn: sqlite3.Connection = Depends(get_conn)):
    return catalog.seller_products(conn, seller_id, q, limit)


@router.get("/delivery-reference/{state}")
def delivery_reference(state: str, conn: sqlite3.Connection = Depends(get_conn)):
    return catalog.delivery_reference(conn, state.upper())


@router.get("/invoices/{invoice_id}", tags=["Orders & Invoices"])
def get_invoice(invoice_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    return invoices.get_invoice(conn, invoice_id)
