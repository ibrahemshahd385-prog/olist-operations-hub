"""Feature engineering shared by training (scripts/train_models.py) and live
predictions (app/ml/predictor.py).

The same functions turn an order into model inputs whether it is one of the
99k historical orders or an order being typed right now. One code path for
both is what keeps the models honest in production.

Only information known AT PURCHASE TIME is used: where the seller and the
customer are, what is shipped, when, how it is paid, the seller's record from
orders delivered BEFORE this one, and how fast the network was delivering in
the days before the purchase. Nothing about the delivery itself.
"""
import sqlite3

import numpy as np
import pandas as pd

CATEGORICAL = ["customer_state", "seller_state", "category"]

_ORDER_NUMERIC = [
    "distance_km", "same_state", "weight_kg", "cubic_kg", "n_items", "n_sellers",
    "products_total", "freight_total", "month", "weekday", "is_boleto",
    "seller_prior_orders", "seller_late_rate", "seller_handling_days",
]
ETA_FEATURES = _ORDER_NUMERIC + CATEGORICAL
RISK_FEATURES = _ORDER_NUMERIC + ["promised_days", "promise_ratio"] + CATEGORICAL
FREIGHT_FEATURES = ["distance_km", "same_state", "weight_kg", "cubic_kg", "price"] + CATEGORICAL

CUBIC_DIVISOR = 6000      # volumetric weight (kg) = L x W x H (cm) / 6000, the usual carrier rule
LATE_PRIOR_WEIGHT = 10    # a seller with few deliveries is pulled towards the network's late rate
RECENT_WINDOW_DAYS = 30   # "how is the network doing lately" looks at the last 30 days of deliveries
RECENT_MIN_ORDERS = 20    # fewer deliveries than this in the window -> not enough to trust


# ---------------------------------------------------------------------------
# Geography
# ---------------------------------------------------------------------------

class GeoLookup:
    """Zip prefix -> (lat, lng). Falls back to the state's average point."""

    def __init__(self, conn: sqlite3.Connection):
        g = pd.read_sql("SELECT zip_code_prefix, lat, lng, state FROM geolocation", conn)
        self.by_zip = {z: (la, ln) for z, la, ln in zip(g["zip_code_prefix"], g["lat"], g["lng"])}
        c = g.groupby("state")[["lat", "lng"]].mean()
        self.by_state = {s: (r.lat, r.lng) for s, r in c.iterrows()}

    def point(self, zip_prefix, state):
        return self.by_zip.get(zip_prefix) or self.by_state.get(state) or (np.nan, np.nan)


def haversine_km(lat1, lng1, lat2, lng2):
    """Straight-line distance on the globe, in km."""
    lat1, lng1, lat2, lng2 = (np.radians(np.asarray(v, dtype=float)) for v in (lat1, lng1, lat2, lng2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lng2 - lng1) / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


# ---------------------------------------------------------------------------
# Items and orders
# ---------------------------------------------------------------------------

def item_physics(items: pd.DataFrame) -> pd.DataFrame:
    """Real weight and volumetric weight of each unit (carriers charge the larger one)."""
    it = items.copy()
    it["weight_kg"] = it["product_weight_g"] / 1000
    it["cubic_kg"] = it["product_length_cm"] * it["product_height_cm"] * it["product_width_cm"] / CUBIC_DIVISOR
    return it


def order_frame_from_items(items: pd.DataFrame, orders: pd.DataFrame, geo: GeoLookup) -> pd.DataFrame:
    """One row per order.
    items  (one row per unit): order_id, seller_id, price, freight_value, product_weight_g,
           product_length_cm, product_height_cm, product_width_cm, category, seller_zip, seller_state
    orders: order_id, purchase_ts, customer_zip, customer_state, is_boleto (+ any other columns, kept)
    The order's "main" seller and category are the ones carrying most of its value."""
    it = item_physics(items)
    agg = it.groupby("order_id").agg(
        n_items=("seller_id", "size"), n_sellers=("seller_id", "nunique"),
        products_total=("price", "sum"), freight_total=("freight_value", "sum"),
        weight_kg=("weight_kg", "sum"), cubic_kg=("cubic_kg", "sum"),
    ).reset_index()

    by_seller = it.groupby(["order_id", "seller_id"], as_index=False).agg(
        value=("price", "sum"), seller_zip=("seller_zip", "first"), seller_state=("seller_state", "first"))
    main_seller = by_seller.sort_values(["order_id", "value"], ascending=[True, False]) \
        .drop_duplicates("order_id")[["order_id", "seller_id", "seller_zip", "seller_state"]]
    main_cat = it.sort_values(["order_id", "price"], ascending=[True, False]) \
        .drop_duplicates("order_id")[["order_id", "category"]]

    f = orders.merge(agg, on="order_id").merge(main_seller, on="order_id").merge(main_cat, on="order_id")
    c = np.array([geo.point(z, s) for z, s in zip(f["customer_zip"], f["customer_state"])], dtype=float).reshape(-1, 2)
    s = np.array([geo.point(z, st) for z, st in zip(f["seller_zip"], f["seller_state"])], dtype=float).reshape(-1, 2)
    f["distance_km"] = haversine_km(c[:, 0], c[:, 1], s[:, 0], s[:, 1])
    f["same_state"] = (f["customer_state"] == f["seller_state"]).astype(int)
    ts = pd.to_datetime(f["purchase_ts"])
    f["month"] = ts.dt.month
    f["weekday"] = ts.dt.dayofweek
    f["is_boleto"] = f["is_boleto"].astype(int)
    return f


def smoothed_late_rate(late_count, n_orders, global_late: float, k: int = LATE_PRIOR_WEIGHT):
    """(late + k x network rate) / (orders + k): one bad delivery does not brand a new seller."""
    return (late_count + k * global_late) / (n_orders + k)


# ---------------------------------------------------------------------------
# "How fast is the network delivering right now?"
# ---------------------------------------------------------------------------
# Delivery speed in this dataset changes a lot over time (Black Friday, Carnival,
# the May 2018 truckers' strike, and a faster network in mid-2018). A model that
# only knows the order itself would be stuck with the average of the past. So the
# ETA model predicts how much faster or slower THIS order is than the recent
# network speed, which is known on the day of purchase.

def _window_sums(daily: pd.DataFrame, window_days: int) -> pd.DataFrame:
    """For every day D: totals over the `window_days` days BEFORE D (D itself excluded,
    because on the day of purchase we only know deliveries up to yesterday)."""
    full = daily.asfreq("D", fill_value=0)
    return full.rolling(window_days, min_periods=1).sum().shift(1)


def recent_network_stats(delivered: pd.DataFrame):
    """delivered: actual_days, late, customer_state, delivered_at.
    For every calendar day: average delivery time (and late rate) of the orders
    delivered in the previous RECENT_WINDOW_DAYS days, overall and per state."""
    d = delivered.dropna(subset=["delivered_at", "actual_days"]).copy()
    d["day"] = pd.to_datetime(d["delivered_at"]).dt.normalize()
    d["late"] = d["late"].fillna(0)

    daily = d.groupby("day").agg(days=("actual_days", "sum"), late=("late", "sum"), n=("actual_days", "size"))
    w = _window_sums(daily, RECENT_WINDOW_DAYS)
    enough = w["n"] >= RECENT_MIN_ORDERS
    overall = pd.DataFrame({
        "recent_days": (w["days"] / w["n"]).where(enough),
        "recent_late_rate": (w["late"] / w["n"]).where(enough),
    }).dropna().rename_axis("day").reset_index()

    parts = []
    for state, g in d.groupby("customer_state"):
        ds = g.groupby("day").agg(days=("actual_days", "sum"), n=("actual_days", "size"))
        ws = _window_sums(ds, RECENT_WINDOW_DAYS)
        parts.append(pd.DataFrame({"customer_state": state,
                                   "recent_state_days": (ws["days"] / ws["n"]).where(ws["n"] >= RECENT_MIN_ORDERS)}))
    by_state = pd.concat(parts).dropna().rename_axis("day").reset_index()
    return overall, by_state


def attach_recent_stats(frame: pd.DataFrame, overall: pd.DataFrame, by_state: pd.DataFrame) -> pd.DataFrame:
    """Each order gets the network numbers known on its purchase day (deliveries up to the day before)."""
    f = frame.drop(columns=[c for c in ["recent_days", "recent_late_rate", "recent_state_days"] if c in frame])
    f["_day"] = pd.to_datetime(f["purchase_ts"]).dt.normalize()
    f = f.merge(overall.rename(columns={"day": "_day"}), on="_day", how="left")
    f = f.merge(by_state.rename(columns={"day": "_day"}), on=["_day", "customer_state"], how="left")
    return f.drop(columns="_day")


def fill_recent(frame: pd.DataFrame, fallback_days: float) -> pd.DataFrame:
    """No recent numbers (start of the data, or a quiet state): use the next best value."""
    f = frame.copy()
    if "recent_days" not in f:
        f["recent_days"] = np.nan
    if "recent_state_days" not in f:
        f["recent_state_days"] = np.nan
    f["recent_days"] = f["recent_days"].fillna(fallback_days)
    f["recent_state_days"] = f["recent_state_days"].fillna(f["recent_days"])
    return f


def eta_anchor(frame: pd.DataFrame) -> np.ndarray:
    """log(recent delivery days for this customer's state): the ETA model predicts the
    difference from this value."""
    anchor = frame["recent_state_days"] if "recent_state_days" in frame else frame["recent_days"]
    anchor = anchor.fillna(frame["recent_days"]) if "recent_days" in frame else anchor
    return np.log1p(anchor.astype(float).values)


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------

def fit_encoders(frame: pd.DataFrame) -> dict:
    """Category text -> code, most frequent first (learned on training data only)."""
    return {c: frame[c].value_counts().index.tolist() for c in CATEGORICAL if c in frame}


def categorical_mask(features: list) -> list:
    return [f in CATEGORICAL for f in features]


def transform(frame: pd.DataFrame, encoders: dict, features: list) -> pd.DataFrame:
    """Model input in the exact column order the model was trained with.
    Unknown categories (a state never seen in training) become 'missing'."""
    f = frame.copy()
    if "promise_ratio" in features:
        # how generous the promise is compared with how fast the network delivers right now
        f["promise_ratio"] = f["promised_days"] / np.expm1(eta_anchor(f))
    out = pd.DataFrame(index=f.index)
    for col in features:
        if col in CATEGORICAL:
            codes = {v: i for i, v in enumerate(encoders.get(col, []))}
            out[col] = f[col].map(codes).astype(float) if col in f else np.nan
        else:
            out[col] = pd.to_numeric(f[col], errors="coerce").astype(float) if col in f else np.nan
    return out
