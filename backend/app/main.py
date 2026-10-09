"""Olist Operations Hub - API entry point.

Run (from the backend folder):
    uvicorn app.main:app --reload
Interactive API docs: http://localhost:8000/docs
"""
import threading

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import snapshot
from .config import DB_PATH, FRONTEND_DIST
from .db import connect, ensure_schema
from .errors import BusinessRuleError, NotFoundError, ValidationFailed
from .routers import analytics, catalog, logistics, orders, sellers

# Upgrade an existing database with tables added by later modules (safe to repeat).
if DB_PATH.exists():
    _conn = connect()
    ensure_schema(_conn)
    _conn.close()

# On the live demo server the heavy history numbers are saved at build time (app/snapshot.py).
snapshot.load()


def _load_models_in_background():
    """Read the trained models from disk while the first pages load, so the first
    delivery quote or review analysis does not wait for them."""
    from .ml import predictor, reviews
    try:
        reviews.available()
        if DB_PATH.exists():
            conn = connect()
            predictor.warm_up(conn)
            conn.close()
    except Exception:
        pass  # a missing model is reported by the screens that use it


threading.Thread(target=_load_models_in_background, daemon=True).start()

app = FastAPI(
    title="Olist Operations Hub",
    description="Order-to-cash system for Olist sellers, built on the public Olist dataset. "
                "Modules: orders & NF-e invoices, smart logistics, seller performance, analytics & AI.",
    version="1.0.0",
)

# The React dev server runs on port 5173 and calls this API on port 8000.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- one place that turns business errors into HTTP responses -------------
@app.exception_handler(NotFoundError)
async def not_found(_: Request, exc: NotFoundError):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(BusinessRuleError)
async def rule_broken(_: Request, exc: BusinessRuleError):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(ValidationFailed)
async def invalid(_: Request, exc: ValidationFailed):
    return JSONResponse(status_code=422, content={"detail": exc.errors})


@app.get("/api/health", tags=["System"])
def health():
    return {"status": "ok", "database": DB_PATH.exists()}


app.include_router(orders.router)
app.include_router(catalog.router)
app.include_router(logistics.router)
# after catalog, so /api/sellers/search is matched before /api/sellers/{seller_id}
app.include_router(sellers.router)
app.include_router(analytics.router)

# If the React app was built (npm run build), serve it from the same server,
# so the whole system runs on http://localhost:8000 with one command.
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
