"""Save the heavy, history-only numbers so the API starts fast on a small server.

Run after build_database and train_models (the Dockerfile does it):
    python -m scripts.precompute

Not needed on your own computer. See app/snapshot.py.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import snapshot  # noqa: E402
from app.config import SNAPSHOT_PATH  # noqa: E402
from app.db import connect, ensure_schema  # noqa: E402

if __name__ == "__main__":
    t0 = time.time()
    conn = connect()
    ensure_schema(conn)
    snapshot.save(conn)
    conn.close()
    print(f"Saved {SNAPSHOT_PATH} ({SNAPSHOT_PATH.stat().st_size / 1e6:.1f} MB) in {time.time() - t0:.0f}s")
