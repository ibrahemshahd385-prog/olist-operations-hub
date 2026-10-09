"""Database connection helpers.

We use Python's built-in sqlite3 with plain SQL on purpose: every query in the
project is readable as-is, there is no ORM "magic", and nothing extra to install.
Moving to PostgreSQL later would mean changing this file and a few SQL details.
"""
import sqlite3
from pathlib import Path
from typing import Iterator

from .config import DB_PATH

MIGRATIONS = Path(__file__).resolve().parent / "migrations.sql"


def connect(path=DB_PATH) -> sqlite3.Connection:
    # check_same_thread=False: FastAPI may open the connection in one worker
    # thread and use it in another during the same request.
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row          # rows behave like dicts: row["order_id"]
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_conn() -> Iterator[sqlite3.Connection]:
    """FastAPI dependency: one connection per request, always closed afterwards."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create any table added after the database was first built (safe to repeat)."""
    conn.executescript(MIGRATIONS.read_text(encoding="utf-8"))
    conn.commit()


def rows_to_dicts(rows) -> list:
    return [dict(r) for r in rows]


def row_to_dict(row):
    return dict(row) if row is not None else None
