"""Live predictions for one order (Module 2).

Loads the bundle saved by scripts/train_models.py once, then answers:
  - how long will this order really take, and what should we promise?
  - how likely is it to be late, and why?
  - what should the freight cost for each line?

If the models were not trained yet, `available()` is False and the rest of
the system falls back to Olist's historical promise (Module 1 behaviour).
"""
import math
import sqlite3
from datetime import datetime, timedelta
from functools import lru_cache

import numpy as np
import pandas as pd

from ..config import MODELS_DIR
from . import features as F

BUNDLE_PATH = MODELS_DIR / "logistics.joblib"
HIGH_RISK_MONTHS = {2, 3, 11, 12}  # months with the most late deliveries in the data (Black Friday, Carnival, rains)


@lru_cache(maxsize=1)
def _bundle():
    if not BUNDLE_PATH.exists():
        return None
    import joblib
    return joblib.load(BUNDLE_PATH)


def reload():
    """Forget the cached bundle (after retraining)."""
    _bundle.cache_clear()
    _GEO_CACHE.clear()


def available() -> bool:
    return _bundle() is not None


def metrics():
    b = _bundle()
    if b is None:
        return None
    return {"metrics": b["metrics"], "trained_at": b["trained_at"], "split": b["split"],
            "network_as_of": b["latest_recent"]["as_of"], "sklearn_version": b["sklearn_version"]}


_GEO_CACHE = {}


def _geo(conn: sqlite3.Connection) -> F.GeoLookup:
    """19k zip points, loaded once per database file and kept in memory."""
    path = conn.execute("PRAGMA database_list").fetchone()[2]
    if not path:                      # in-memory database (tests): no caching
        return F.GeoLookup(conn)
    if path not in _GEO_CACHE:
        _GEO_CACHE[path] = F.GeoLookup(conn)
    return _GEO_CACHE[path]


def _item_rows(conn, lines) -> pd.DataFrame:
    """One row per unit, with product size/weight and the seller's location (like training)."""
    rows = []
    for n, line in enumerate(lines):
        p = conn.execute(
            """SELECT p.product_weight_g, p.product_length_cm, p.product_height_cm, p.product_width_cm,
                      COALESCE(p.product_category_name_english, 'unknown') AS category,
                      s.seller_zip_code_prefix AS seller_zip, s.seller_state
               FROM products p, sellers s WHERE p.product_id = ? AND s.seller_id = ?""",
            (line["product_id"], line["seller_id"])).fetchone()
        if p is None:
            continue
        for _ in range(int(line.get("quantity", 1))):
            rows.append({"order_id": "quote", "line": n, "seller_id": line["seller_id"],
                         "price": float(line["unit_price"]),
                         "freight_value": float(line.get("freight_value") or 0), **dict(p)})
    return pd.DataFrame(rows)


def quote(conn: sqlite3.Connection, customer_state: str, customer_zip: str, lines: list,
          payment_types=(), purchase_ts: datetime = None) -> dict:
    b = _bundle()
    if b is None or not lines:
        return {"available": False}
    purchase_ts = purchase_ts or datetime.now()
    geo = _geo(conn)

    items = _item_rows(conn, lines)
    if items.empty:
        return {"available": False}
    orders = pd.DataFrame([{"order_id": "quote", "purchase_ts": pd.Timestamp(purchase_ts),
                            "customer_zip": customer_zip, "customer_state": customer_state,
                            "is_boleto": int("boleto" in payment_types)}])

    # --- freight estimate for every unit (uses the item's own route) ---
    it = F.item_physics(items)
    c_lat, c_lng = geo.point(customer_zip, customer_state)
    s_pts = np.array([geo.point(z, s) for z, s in zip(it.seller_zip, it.seller_state)])
    it["distance_km"] = F.haversine_km(c_lat, c_lng, s_pts[:, 0], s_pts[:, 1])
    it["same_state"] = (it.seller_state == customer_state).astype(int)
    it["customer_state"] = customer_state
    it["freight_estimate"] = np.expm1(b["freight"].predict(F.transform(it, b["encoders"], F.FREIGHT_FEATURES))).clip(0)
    # if a freight was not typed yet, the estimate stands in for it
    items["freight_value"] = np.where(items["freight_value"] > 0, items["freight_value"], it["freight_estimate"])

    # --- order-level features ---
    frame = F.order_frame_from_items(items, orders, geo)
    seller = conn.execute("SELECT * FROM ref_seller_logistics WHERE seller_id = ?",
                          (frame.at[0, "seller_id"],)).fetchone()
    frame["seller_prior_orders"] = seller["orders"] if seller else 0
    frame["seller_late_rate"] = seller["late_rate"] if seller else b["global_late_rate"]
    frame["seller_handling_days"] = (seller["handling_days"] if seller and seller["handling_days"] is not None
                                     else b["defaults"]["seller_handling_days"])
    recent = b["latest_recent"]
    frame["recent_days"] = recent["recent_days"]
    frame["recent_state_days"] = recent["recent_state_days"].get(customer_state, recent["recent_days"])

    # --- ETA and promise ---
    log_days = b["eta"].predict(F.transform(frame, b["encoders"], F.ETA_FEATURES))[0] + F.eta_anchor(frame)[0]
    eta_days = float(np.expm1(log_days))
    promise_days = int(max(1, math.ceil(np.expm1(log_days + b["safety_margin_log"]))))

    legacy = conn.execute("SELECT median_promised_days FROM ref_state_delivery WHERE customer_state = ?",
                          (customer_state,)).fetchone()
    legacy_days = int(math.ceil(legacy[0])) if legacy else 24

    def risk_for(days):
        f = frame.assign(promised_days=days)
        f = F.fill_recent(f, recent["fallback_days"])
        return float(b["risk"].predict_proba(F.transform(f, b["encoders"], F.RISK_FEATURES))[0, 1])

    risk = risk_for(promise_days)
    day0 = purchase_ts.replace(hour=0, minute=0, second=0, microsecond=0)
    per_line = it.groupby("line")["freight_estimate"].mean().round(2)
    return {
        "available": True,
        "eta_days": round(eta_days, 1),
        "promise_days": promise_days,
        "promise_date": (day0 + timedelta(days=promise_days)).strftime("%Y-%m-%d %H:%M:%S"),
        "legacy_promise_days": legacy_days,
        "risk": {"probability": round(risk, 4), "level": risk_level(risk, b),
                 "with_legacy_promise": round(risk_for(legacy_days), 4),
                 "reasons": _reasons(frame.iloc[0], b, promise_days)},
        "distance_km": round(float(frame.at[0, "distance_km"]), 0),
        "freight_estimates": [{"line": int(k), "per_unit": float(v)} for k, v in per_line.items()],
        "network_as_of": recent["as_of"],
    }


def risk_level(p: float, b=None) -> str:
    b = b or _bundle()
    cut = b["risk_cutoffs"]
    return "high" if p >= cut["high"] else "medium" if p >= cut["medium"] else "low"


def _reasons(row, b, promise_days) -> list:
    """Plain-language drivers, so an operator knows WHY an order is flagged.
    These are simple rules on the same inputs the model sees, not the model's internals."""
    out = []
    if row["distance_km"] > 1500:
        out.append(f"Long route: {row['distance_km']:,.0f} km from the seller")
    if row["seller_late_rate"] > 2 * b["global_late_rate"]:
        out.append(f"Seller's past late rate is {row['seller_late_rate']:.0%} (network {b['global_late_rate']:.0%})")
    if row["seller_handling_days"] > 3:
        out.append(f"Seller usually takes {row['seller_handling_days']:.1f} days to hand over to the carrier")
    if row["is_boleto"]:
        out.append("Boleto: about 29 hours before payment clears")
    if max(row["weight_kg"], row["cubic_kg"]) > 15:
        out.append("Heavy or bulky package")
    if int(row["month"]) in HIGH_RISK_MONTHS:
        out.append("Peak month: historically more late deliveries")
    if row["n_sellers"] > 1:
        out.append(f"{int(row['n_sellers'])} sellers must all ship")
    return out
