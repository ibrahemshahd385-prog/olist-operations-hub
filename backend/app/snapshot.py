"""A saved copy of the heavy, history-only numbers, so a small server starts fast.

The analytics page, the seller scores and the busiest delivery lanes all read the
whole history (about 100k orders). The services compute them on first use and keep
them in memory. On a laptop that first visit takes a few seconds; on a small free
server (a tenth of a CPU) it takes close to a minute.

    python -m scripts.precompute

computes them once and saves them here. The API loads the file when it starts. The
Dockerfile runs it at build time; locally nobody needs to, and without the file
everything works exactly as before.

build_database and train_models delete the file, so it can never be out of date.
"""
import pickle
import sqlite3

from .config import SNAPSHOT_PATH


def _caches() -> dict:
    """The in-memory caches of the services, by name."""
    from .services import analytics, logistics, sellers
    return {"analytics": analytics._cache, "lanes": logistics._lanes_cache, "sellers": sellers._cache}


def save(conn: sqlite3.Connection, path=SNAPSHOT_PATH) -> None:
    from .services import analytics, logistics, sellers
    analytics.overview(conn)
    analytics.review_insights(conn)
    logistics.lanes(conn)
    sellers.metrics(conn)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump({name: dict(cache) for name, cache in _caches().items()}, f)


def load(path=SNAPSHOT_PATH) -> bool:
    """Fill the caches from the saved file. Returns False (and changes nothing) if there is none."""
    if not path.exists():
        return False
    try:
        with open(path, "rb") as f:
            saved = pickle.load(f)
    except Exception:  # unreadable or made by another library version: just compute on first use
        return False
    for name, cache in _caches().items():
        cache.update(saved.get(name, {}))
    return True


def clear(path=SNAPSHOT_PATH) -> None:
    path.unlink(missing_ok=True)
