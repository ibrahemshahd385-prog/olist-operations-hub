"""Module 3: seller performance.

Olist's real customer is the seller, and 10% of sellers bring ~67% of revenue,
so knowing which sellers are healthy, slipping or about to leave is core to the business.

Everything is computed from the dataset's history up to AS_OF (the last day of
normal activity in the data) and cached in memory: the history does not change.
"""
import sqlite3
from datetime import datetime

import numpy as np
import pandas as pd

from ..db import rows_to_dicts
from ..errors import NotFoundError

AS_OF = pd.Timestamp("2018-09-01")   # "today" for the dataset (activity stops at the end of August 2018)
MIN_ORDERS_FOR_SCORE = 10            # below this, a score would be mostly noise
KEY_ACCOUNT_SHARE = 0.10             # top 10% of sellers by revenue

# The health score: four parts, each turned into 0-100, then weighted.
# Delivery weighs most because late orders drop the review score from 4.3 to 2.3 (Task 1).
WEIGHTS = {"delivery": 0.35, "rating": 0.30, "speed": 0.20, "reliability": 0.15}
COMPONENTS = {
    "delivery": "On-time deliveries: 75% or less scores 0, 100% scores 100",
    "rating": "Average review: 1 star scores 0, 5 stars scores 100",
    "speed": "Days from payment to carrier: 1 day or less scores 100, 6 days or more scores 0",
    "reliability": "Canceled or unavailable orders: 0% scores 100, 5% or more scores 0",
}
TIERS = [(85, "A"), (70, "B"), (55, "C"), (0, "D")]

_cache = {}


def _scale(value, worst, best):
    """Linear 0-100 between a worst and a best value (works in both directions)."""
    if value is None or pd.isna(value):
        return np.nan
    return float(np.clip((value - worst) / (best - worst), 0, 1) * 100)


def _tier(score):
    if pd.isna(score):
        return None
    return next(t for cut, t in TIERS if score >= cut)


def metrics(conn: sqlite3.Connection) -> pd.DataFrame:
    """One row per seller with every number the screens need."""
    if "frame" in _cache:
        return _cache["frame"]

    so = pd.read_sql(
        """SELECT i.seller_id, i.order_id, SUM(i.price) AS revenue, SUM(i.freight_value) AS freight,
                  COUNT(*) AS items, o.order_status, o.order_purchase_timestamp AS ts,
                  o.order_approved_at AS approved, o.order_delivered_carrier_date AS carrier,
                  o.order_delivered_customer_date AS delivered, o.order_estimated_delivery_date AS estimated,
                  c.customer_state
           FROM order_items i
           JOIN orders o ON o.order_id = i.order_id AND o.source = 'historical'
           JOIN customers c ON c.customer_id = o.customer_id
           GROUP BY i.seller_id, i.order_id""", conn)
    for col in ["ts", "approved", "carrier", "delivered", "estimated"]:
        so[col] = pd.to_datetime(so[col])
    reviews = pd.read_sql("SELECT order_id, AVG(review_score) AS score FROM order_reviews GROUP BY order_id", conn)
    so = so.merge(reviews, on="order_id", how="left")
    so["late"] = np.where(so["delivered"].notna(), so["delivered"].dt.normalize() > so["estimated"].dt.normalize(), np.nan)
    so["handling"] = ((so["carrier"] - so["approved"]).dt.total_seconds() / 86400).clip(0, 60)
    so["canceled"] = so["order_status"].isin(["canceled", "unavailable"]).astype(float)
    so["recent90"] = np.where((so.ts >= AS_OF - pd.Timedelta(days=90)) & (so.ts < AS_OF), so.revenue, 0)
    so["prev90"] = np.where((so.ts >= AS_OF - pd.Timedelta(days=180)) & (so.ts < AS_OF - pd.Timedelta(days=90)), so.revenue, 0)

    g = so.sort_values("ts").groupby("seller_id")
    m = g.agg(orders=("order_id", "size"), revenue=("revenue", "sum"), freight=("freight", "sum"),
              items=("items", "sum"), late_rate=("late", "mean"), rating=("score", "mean"),
              reviews=("score", "count"), handling_days=("handling", "median"), cancel_rate=("canceled", "mean"),
              first_sale=("ts", "min"), last_sale=("ts", "max"), revenue_recent90=("recent90", "sum"),
              revenue_prev90=("prev90", "sum"), states_served=("customer_state", "nunique"),
              active_months=("ts", lambda s: s.dt.to_period("M").nunique()))
    m["typical_gap_days"] = g["ts"].apply(lambda s: s.diff().dt.total_seconds().median() / 86400 if len(s) > 1 else np.nan)

    sellers = pd.read_sql("SELECT seller_id, seller_city AS city, seller_state AS state FROM sellers", conn)
    m = sellers.merge(m.reset_index(), on="seller_id", how="left")
    m["orders"] = m["orders"].fillna(0).astype(int)
    m["revenue"] = m["revenue"].fillna(0.0)

    # --- health score
    m["score_delivery"] = [_scale(1 - v, 0.75, 1.0) for v in m.late_rate]
    m["score_rating"] = [_scale(v, 1, 5) for v in m.rating]
    m["score_speed"] = [_scale(v, 6, 1) for v in m.handling_days]
    m["score_reliability"] = [_scale(v, 0.05, 0) for v in m.cancel_rate]
    parts = m[[f"score_{k}" for k in WEIGHTS]]
    weights = np.array(list(WEIGHTS.values()))
    # if one part is missing (e.g. no delivered order yet), the others share its weight
    m["health"] = [(np.nansum(r * weights) / weights[~np.isnan(r)].sum()) if (~np.isnan(r)).any() else np.nan
                   for r in parts.to_numpy(dtype=float)]
    m.loc[m.orders < MIN_ORDERS_FOR_SCORE, "health"] = np.nan
    m["health"] = m["health"].round(0)
    m["tier"] = [_tier(s) for s in m.health]

    # --- key accounts: the top 10% by revenue
    m = m.sort_values("revenue", ascending=False).reset_index(drop=True)
    m["revenue_rank"] = np.arange(1, len(m) + 1)
    m["key_account"] = m["revenue_rank"] <= int(len(m) * KEY_ACCOUNT_SHARE)
    m["revenue_share"] = m["revenue"] / m["revenue"].sum()

    # --- trend and activity
    m["revenue_change"] = np.where(m.revenue_prev90 > 0, (m.revenue_recent90 - m.revenue_prev90) / m.revenue_prev90, np.nan)
    m["days_since_last_sale"] = (AS_OF - m["last_sale"]).dt.days
    m["freight_share"] = m["freight"] / m["revenue"].replace(0, np.nan)
    m["alerts"] = [_alerts(r) for r in m.itertuples()]
    m["credit_ready"] = [_credit_ready(r) for r in m.itertuples()]
    _cache["frame"] = m
    _cache["network"] = {
        "late_rate": float(so["late"].mean()),
        "rating": float(so["score"].mean()),
        "handling_days": float(so["handling"].median()),
        "freight_share": float(so["freight"].sum() / so["revenue"].sum()),
        "handling_p25_key": float(m[m.key_account].handling_days.quantile(0.25)),
    }
    return m


def _alerts(r) -> list:
    """Rules an account manager would act on. Each returns (type, message)."""
    out = []
    if r.orders >= MIN_ORDERS_FOR_SCORE:
        quiet_limit = max(45, 3 * (r.typical_gap_days or 0))
        if r.days_since_last_sale > quiet_limit:
            every = "every day" if (r.typical_gap_days or 0) < 1.5 else f"every {r.typical_gap_days:.0f} days"
            out.append(("gone_quiet", f"No sale in {r.days_since_last_sale} days; used to sell {every}"))
        if r.revenue_prev90 >= 3000 and r.revenue_change is not None and r.revenue_change < -0.5:
            out.append(("revenue_drop", f"Revenue down {-r.revenue_change:.0%} in the last 90 days"))
    if r.key_account and r.tier in ("C", "D"):
        out.append(("key_account_at_risk", f"Key account with health score {r.health:.0f} (tier {r.tier})"))
    if r.orders >= MIN_ORDERS_FOR_SCORE and r.handling_days and r.handling_days > 3:
        out.append(("slow_shipping", f"Takes {r.handling_days:.1f} days to hand orders to the carrier"))
    if r.reviews >= 20 and r.rating < 3.5:
        out.append(("low_rating", f"Average rating {r.rating:.2f} over {r.reviews} reviews"))
    return out


def _credit_ready(r) -> bool:
    """A first filter for Olist's credit offer (one of its fastest-growing products):
    healthy, steady sellers with recent sales. A screening signal, not a credit decision."""
    return bool(r.tier in ("A", "B") and r.active_months >= 6 and r.cancel_rate < 0.02
                and r.revenue_recent90 > 0 and (pd.isna(r.revenue_change) or r.revenue_change >= 0))


# ---------------------------------------------------------------------------

def _row_out(r: dict) -> dict:
    keep = ["seller_id", "city", "state", "orders", "revenue", "revenue_share", "revenue_rank", "key_account",
            "late_rate", "rating", "reviews", "handling_days", "cancel_rate", "health", "tier",
            "revenue_change", "days_since_last_sale", "credit_ready"]
    out = {k: r[k] for k in keep}
    out["alerts"] = [{"type": t, "message": msg} for t, msg in r["alerts"]]
    for k, v in out.items():
        if isinstance(v, float) and np.isnan(v):
            out[k] = None
        elif isinstance(v, (np.integer,)):
            out[k] = int(v)
        elif isinstance(v, (np.floating,)):
            out[k] = None if np.isnan(v) else round(float(v), 4)
        elif isinstance(v, np.bool_):
            out[k] = bool(v)
    return out


def summary(conn: sqlite3.Connection) -> dict:
    m = metrics(conn)
    scored = m[m.health.notna()]
    by_tier = []
    for t in ["A", "B", "C", "D"]:
        part = m[m.tier == t]
        by_tier.append({"tier": t, "sellers": int(len(part)), "revenue_share": round(float(part.revenue.sum() / m.revenue.sum()), 4)})
    unscored = m[m.tier.isna()]
    by_tier.append({"tier": None, "sellers": int(len(unscored)), "revenue_share": round(float(unscored.revenue.sum() / m.revenue.sum()), 4)})
    alert_counts = pd.Series([t for a in m.alerts for t, _ in a]).value_counts().to_dict()
    key = m[m.key_account]
    # Pareto curve: share of revenue held by the top X% of sellers (m is sorted by revenue)
    cum = m["revenue"].cumsum() / m["revenue"].sum()
    pareto = [{"sellers_pct": p, "revenue_share": round(float(cum.iloc[max(0, int(round(len(m) * p / 100)) - 1)]), 4)}
              for p in range(1, 101)]
    return {
        "sellers": int(len(m)), "scored": int(len(scored)), "as_of": str(AS_OF.date()),
        "key_accounts": int(len(key)), "key_revenue_share": round(float(key.revenue.sum() / m.revenue.sum()), 4),
        "by_tier": by_tier, "alert_counts": {k: int(v) for k, v in alert_counts.items()},
        "credit_ready": int(m.credit_ready.sum()),
        "credit_ready_revenue_share": round(float(m[m.credit_ready].revenue.sum() / m.revenue.sum()), 4),
        "weights": WEIGHTS, "components": COMPONENTS, "network": _cache["network"],
        "min_orders": MIN_ORDERS_FOR_SCORE, "pareto": pareto,
    }


def list_sellers(conn, q=None, tier=None, state=None, key_only=False, alert=None, credit_ready=False,
                 sort="revenue", page=1, page_size=25) -> dict:
    m = metrics(conn)
    if q:
        q = q.strip().lower()
        m = m[m.seller_id.str.startswith(q) | m.city.str.startswith(q)]
    if tier:
        m = m[m.tier == tier]
    if state:
        m = m[m.state == state]
    if key_only:
        m = m[m.key_account]
    if credit_ready:
        m = m[m.credit_ready]
    if alert:
        m = m[[any(t == alert for t, _ in a) for a in m.alerts]]
    if sort == "health":
        m = m.sort_values(["health", "revenue"], ascending=[True, False], na_position="last")
    elif sort == "late":
        m = m.sort_values("late_rate", ascending=False, na_position="last")
    total = len(m)
    rows = m.iloc[(page - 1) * page_size: page * page_size]
    return {"items": [_row_out(r) for r in rows.to_dict("records")], "total": total, "page": page,
            "page_size": page_size, "pages": max(1, -(-total // page_size))}


def get_seller(conn: sqlite3.Connection, seller_id: str) -> dict:
    m = metrics(conn)
    match = m[m.seller_id == seller_id]
    if match.empty:
        raise NotFoundError(f"Seller {seller_id} not found")
    r = match.iloc[0].to_dict()
    out = _row_out(r)
    out.update({
        "first_sale": str(r["first_sale"])[:19] if pd.notna(r["first_sale"]) else None,
        "last_sale": str(r["last_sale"])[:19] if pd.notna(r["last_sale"]) else None,
        "active_months": None if pd.isna(r["active_months"]) else int(r["active_months"]),
        "states_served": None if pd.isna(r["states_served"]) else int(r["states_served"]),
        "freight_share": None if pd.isna(r["freight_share"]) else round(float(r["freight_share"]), 4),
        "avg_order_value": round(float(r["revenue"] / r["orders"]), 2) if r["orders"] else None,
        "components": [{"key": k, "weight": w, "score": None if pd.isna(r[f"score_{k}"]) else round(float(r[f"score_{k}"]), 0),
                        "rule": COMPONENTS[k]} for k, w in WEIGHTS.items()],
        "network": _cache["network"],
        "sellers_total": int(len(m)),
    })
    out["monthly"] = rows_to_dicts(conn.execute(
        """SELECT strftime('%Y-%m', o.order_purchase_timestamp) AS month, COUNT(DISTINCT o.order_id) AS orders,
                  ROUND(SUM(i.price), 2) AS revenue
           FROM order_items i JOIN orders o ON o.order_id = i.order_id
           WHERE i.seller_id = ? AND o.source = 'historical' GROUP BY month ORDER BY month""", (seller_id,)).fetchall())
    out["categories"] = rows_to_dicts(conn.execute(
        """SELECT COALESCE(p.product_category_name_english, 'uncategorized') AS category, COUNT(*) AS items,
                  ROUND(SUM(i.price), 2) AS revenue
           FROM order_items i LEFT JOIN products p ON p.product_id = i.product_id
           WHERE i.seller_id = ? GROUP BY category ORDER BY revenue DESC LIMIT 5""", (seller_id,)).fetchall())
    out["late_by_state"] = rows_to_dicts(conn.execute(
        """SELECT c.customer_state AS state, COUNT(DISTINCT o.order_id) AS orders,
                  ROUND(AVG(date(o.order_delivered_customer_date) > date(o.order_estimated_delivery_date)), 4) AS late_rate
           FROM order_items i JOIN orders o ON o.order_id = i.order_id
           JOIN customers c ON c.customer_id = o.customer_id
           WHERE i.seller_id = ? AND o.order_delivered_customer_date IS NOT NULL
           GROUP BY c.customer_state ORDER BY orders DESC LIMIT 6""", (seller_id,)).fetchall())
    out["recommendations"] = _recommendations(out)
    return out


def _recommendations(s: dict) -> list:
    """Plain next steps for the account manager, strongest problem first."""
    net = s["network"]
    recs = []
    if s["late_rate"] is not None and s["late_rate"] > 1.5 * net["late_rate"]:
        worst = max(s["late_by_state"], key=lambda x: (x["late_rate"] or 0), default=None)
        where = f" The worst destination is {worst['state']} ({worst['late_rate']:.0%} late)." if worst and worst["late_rate"] else ""
        recs.append(f"{s['late_rate']:.0%} of orders arrive late, against {net['late_rate']:.0%} for the network.{where} "
                    "Late orders average 2.3 stars instead of 4.3, so this is the first thing to fix.")
    if s["handling_days"] is not None and s["handling_days"] > 2:
        recs.append(f"Orders wait {s['handling_days']:.1f} days before reaching the carrier. The fastest quarter of key "
                    f"accounts hands over in {net['handling_p25_key']:.1f} days. Shipping within 2 days is the easiest win.")
    if s["rating"] is not None and s["rating"] < 4 and s["reviews"] >= 10:
        recs.append(f"Average rating is {s['rating']:.2f}. Check the review themes in Analytics to see what customers complain about.")
    if s["cancel_rate"] is not None and s["cancel_rate"] > 0.02:
        recs.append(f"{s['cancel_rate']:.1%} of orders end canceled or unavailable. Keeping stock in sync with the listings avoids this.")
    if s.get("freight_share") and s["freight_share"] > 0.25:
        recs.append(f"Freight is {s['freight_share']:.0%} of the product value (network {net['freight_share']:.0%}). "
                    "Lighter packaging or combined shipping would make the offer more attractive.")
    if any(a["type"] == "gone_quiet" for a in s["alerts"]):
        recs.append("The seller stopped selling. A call from the account team can find out why before they leave for good.")
    if s["credit_ready"]:
        recs.append("Healthy and steady: a candidate for a pre-approved working-capital offer from Olist's credit products.")
    if not recs:
        recs.append("No issues stand out. Keep monitoring the delivery rate as volume grows.")
    return recs
