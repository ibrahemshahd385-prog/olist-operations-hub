"""Train every model in the system and save them to data/models/

  Module 2 (logistics.joblib): delivery ETA + promise, late risk, freight
  Module 4 (reviews.joblib):   review sentiment + complaint topics

Run from the backend folder (after build_database):
    python -m scripts.train_models

Three models, all trained ONLY on data available when an order is placed:
  1. ETA      - how many days will delivery really take?  -> a shorter, honest promise
  2. Risk     - probability the order arrives after its promised date (Task 1 idea)
  3. Freight  - what should shipping cost for this item and route?

How we test honestly (time split, never random):
  train        orders placed before 2018-04-01
  calibration  2018-04-01 .. 2018-05-31   (used to tune the promise and risk levels)
  test         2018-06-01 .. 2018-08-31   (never seen; every number we report comes from here)
"""
import json
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.metrics import average_precision_score, mean_absolute_error, roc_auc_score

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import snapshot  # noqa: E402
from app.config import DB_PATH, MODELS_DIR  # noqa: E402
from app.db import ensure_schema  # noqa: E402
from app.ml import features as F  # noqa: E402
from app.ml import reviews  # noqa: E402

TRAIN_END = "2018-04-01"
CALIB_END = "2018-06-01"
TEST_END = "2018-09-01"
TARGET_ON_TIME = 0.95   # the promise must be kept for 95% of orders (Olist kept 93.2% overall)
RANDOM_STATE = 42


def load(conn):
    orders = pd.read_sql(
        """SELECT o.order_id, o.order_status, o.order_purchase_timestamp AS purchase_ts,
                  o.order_approved_at, o.order_delivered_carrier_date, o.order_delivered_customer_date,
                  o.order_estimated_delivery_date, c.customer_zip_code_prefix AS customer_zip, c.customer_state,
                  EXISTS (SELECT 1 FROM order_payments p WHERE p.order_id = o.order_id
                          AND p.payment_type = 'boleto') AS is_boleto
           FROM orders o JOIN customers c ON c.customer_id = o.customer_id
           WHERE o.source = 'historical'""", conn)
    for col in ["purchase_ts", "order_approved_at", "order_delivered_carrier_date",
                "order_delivered_customer_date", "order_estimated_delivery_date"]:
        orders[col] = pd.to_datetime(orders[col])
    items = pd.read_sql(
        """SELECT i.order_id, i.seller_id, i.price, i.freight_value,
                  p.product_weight_g, p.product_length_cm, p.product_height_cm, p.product_width_cm,
                  COALESCE(p.product_category_name_english, 'unknown') AS category,
                  s.seller_zip_code_prefix AS seller_zip, s.seller_state
           FROM order_items i JOIN orders o ON o.order_id = i.order_id AND o.source = 'historical'
           LEFT JOIN products p ON p.product_id = i.product_id
           LEFT JOIN sellers s ON s.seller_id = i.seller_id""", conn)
    return orders, items


def seller_history_as_of_purchase(frame: pd.DataFrame, global_late: float) -> pd.DataFrame:
    """For each order, the main seller's track record using ONLY orders delivered
    before this order was placed (merge_asof = 'latest known value at that time')."""
    done = frame.dropna(subset=["order_delivered_customer_date"]).copy()
    done["handling"] = ((done["order_delivered_carrier_date"] - done["order_approved_at"])
                        .dt.total_seconds() / 86400).clip(0, 60)
    done = done.sort_values("order_delivered_customer_date")
    g = done.groupby("seller_id")
    done["cum_orders"] = g.cumcount() + 1
    done["cum_late"] = g["late"].cumsum()
    done["cum_handling"] = g["handling"].transform(lambda s: s.fillna(s.median()).cumsum())
    events = done[["seller_id", "order_delivered_customer_date", "cum_orders", "cum_late", "cum_handling"]] \
        .rename(columns={"order_delivered_customer_date": "known_at"}).sort_values("known_at")

    left = frame[["order_id", "seller_id", "purchase_ts"]].sort_values("purchase_ts")
    merged = pd.merge_asof(left, events, left_on="purchase_ts", right_on="known_at", by="seller_id",
                           direction="backward", allow_exact_matches=False)
    merged["seller_prior_orders"] = merged["cum_orders"].fillna(0)
    merged["seller_late_rate"] = F.smoothed_late_rate(merged["cum_late"].fillna(0), merged["seller_prior_orders"], global_late)
    merged["seller_handling_days"] = (merged["cum_handling"] / merged["cum_orders"])  # NaN for a new seller
    return frame.drop(columns=[c for c in ["seller_prior_orders", "seller_late_rate", "seller_handling_days"] if c in frame]) \
        .merge(merged[["order_id", "seller_prior_orders", "seller_late_rate", "seller_handling_days"]], on="order_id")


def promise_days_from_log(pred_log, offset):
    return np.ceil(np.expm1(pred_log + offset)).clip(1, None)


def on_time_rate(actual_days, promised_days):
    # the dataset's estimated date is a calendar day; "on time" = delivered on or before that day
    return float((np.floor(actual_days) <= promised_days).mean())


def calibrate_offset(pred_log, actual_days, target):
    """Smallest safety margin (in log-days) that keeps `target` of calibration orders on time."""
    lo, hi = -1.0, 3.0
    for _ in range(50):
        mid = (lo + hi) / 2
        if on_time_rate(actual_days, promise_days_from_log(pred_log, mid)) >= target:
            hi = mid
        else:
            lo = mid
    return hi


def main():
    t0 = time.time()
    snapshot.clear()   # the saved review numbers come from the models about to be replaced
    conn = sqlite3.connect(DB_PATH)
    ensure_schema(conn)
    geo = F.GeoLookup(conn)
    orders, items = load(conn)

    print("Building features...")
    frame = F.order_frame_from_items(items, orders, geo)
    frame["actual_days"] = (frame["order_delivered_customer_date"] - frame["purchase_ts"]).dt.total_seconds() / 86400
    est_day = frame["order_estimated_delivery_date"].dt.normalize()
    frame["olist_promised_days"] = (est_day - frame["purchase_ts"].dt.normalize()).dt.days
    frame["late"] = (frame["order_delivered_customer_date"].dt.normalize() > est_day).astype(float)
    frame.loc[frame["order_delivered_customer_date"].isna(), "late"] = np.nan

    delivered = frame[(frame["order_status"] == "delivered") & frame["actual_days"].notna()
                      & frame["olist_promised_days"].notna()]
    global_late = float(delivered["late"].mean())
    frame = seller_history_as_of_purchase(frame, global_late)
    delivered = frame[frame["order_id"].isin(delivered["order_id"])].copy()
    delivered["promised_days"] = delivered["olist_promised_days"]

    # "how is the network doing lately?" - known on the purchase day, from already-delivered orders
    overall, by_state = F.recent_network_stats(delivered.assign(delivered_at=delivered["order_delivered_customer_date"]))
    delivered = F.attach_recent_stats(delivered, overall, by_state)
    fallback_days = float(delivered["actual_days"].median())
    delivered = F.fill_recent(delivered, fallback_days)
    # Live orders use the network numbers from the last day with normal activity. After that,
    # the dataset only contains a tail of very delayed orders, which would make the network look
    # far slower than it was.
    as_of = pd.Timestamp(TEST_END) - pd.Timedelta(days=1)
    last = overall[overall["day"] <= as_of].iloc[-1]
    states_then = by_state[by_state["day"] <= as_of].sort_values("day").groupby("customer_state")["recent_state_days"].last()
    latest_recent = {
        "recent_days": float(last["recent_days"]), "recent_late_rate": float(last["recent_late_rate"]),
        "recent_state_days": states_then.dropna().round(3).to_dict(),
        "as_of": str(last["day"].date()), "fallback_days": fallback_days,
    }

    tr = delivered[delivered.purchase_ts < TRAIN_END]
    ca = delivered[(delivered.purchase_ts >= TRAIN_END) & (delivered.purchase_ts < CALIB_END)]
    te = delivered[(delivered.purchase_ts >= CALIB_END) & (delivered.purchase_ts < TEST_END)]
    print(f"  train {len(tr):,}  calibration {len(ca):,}  test {len(te):,} orders")

    encoders = F.fit_encoders(tr)

    # ---------------- 1. ETA ----------------
    print("Training ETA model...")
    eta = HistGradientBoostingRegressor(max_iter=400, learning_rate=0.06, max_leaf_nodes=31,
                                        categorical_features=F.categorical_mask(F.ETA_FEATURES),
                                        random_state=RANDOM_STATE)
    # target = log(days) MINUS log(recent network speed): the model learns how much slower or
    # faster THIS order is than the network right now, not an absolute number of days
    eta.fit(F.transform(tr, encoders, F.ETA_FEATURES), np.log1p(tr["actual_days"]) - F.eta_anchor(tr))
    ca_log = eta.predict(F.transform(ca, encoders, F.ETA_FEATURES)) + F.eta_anchor(ca)
    offset = calibrate_offset(ca_log, ca["actual_days"].values, TARGET_ON_TIME)

    te_log = eta.predict(F.transform(te, encoders, F.ETA_FEATURES)) + F.eta_anchor(te)
    te = te.assign(eta_days=np.expm1(te_log), model_promise=promise_days_from_log(te_log, offset))
    eta_metrics = {
        "test_orders": int(len(te)),
        "mae_days": round(float(mean_absolute_error(te.actual_days, te.eta_days)), 2),
        "olist_mae_days": round(float(mean_absolute_error(te.actual_days, te.olist_promised_days)), 2),
        "actual_median_days": round(float(te.actual_days.median()), 1),
        "model_promise_mean_days": round(float(te.model_promise.mean()), 1),
        "olist_promise_mean_days": round(float(te.olist_promised_days.mean()), 1),
        "model_on_time": round(on_time_rate(te.actual_days.values, te.model_promise.values), 4),
        "olist_on_time": round(on_time_rate(te.actual_days.values, te.olist_promised_days.values), 4),
        "target_on_time": TARGET_ON_TIME,
        "safety_margin_log": round(offset, 4),
    }
    te = te.assign(olist_ok=(np.floor(te.actual_days) <= te.olist_promised_days).astype(float),
                   model_ok=(np.floor(te.actual_days) <= te.model_promise).astype(float))
    by_state = te.groupby("customer_state").agg(
        orders=("order_id", "size"), actual_median=("actual_days", "median"),
        olist_promise=("olist_promised_days", "mean"), model_promise=("model_promise", "mean"),
        olist_on_time=("olist_ok", "mean"), model_on_time=("model_ok", "mean"),
    ).round(3).reset_index()
    eta_metrics["by_state"] = by_state.sort_values("orders", ascending=False).to_dict("records")
    print(f"  promise {eta_metrics['model_promise_mean_days']} days (Olist {eta_metrics['olist_promise_mean_days']}), "
          f"on time {eta_metrics['model_on_time']:.1%} (Olist {eta_metrics['olist_on_time']:.1%})")

    # ---------------- 2. Late risk ----------------
    print("Training late-risk model...")
    risk = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_leaf_nodes=31,
                                          categorical_features=F.categorical_mask(F.RISK_FEATURES),
                                          random_state=RANDOM_STATE)
    risk.fit(F.transform(tr, encoders, F.RISK_FEATURES), tr["late"].astype(int))
    ca_p = risk.predict_proba(F.transform(ca, encoders, F.RISK_FEATURES))[:, 1]
    te_p = risk.predict_proba(F.transform(te, encoders, F.RISK_FEATURES))[:, 1]
    high_cut, medium_cut = float(np.quantile(ca_p, 0.90)), float(np.quantile(ca_p, 0.70))
    y = te["late"].astype(int).values
    order = np.argsort(-te_p)
    top10 = order[: len(order) // 10]
    deciles = pd.qcut(pd.Series(te_p).rank(method="first"), 10, labels=False)
    risk_metrics = {
        "test_orders": int(len(te)),
        "late_rate": round(float(y.mean()), 4),
        "roc_auc": round(float(roc_auc_score(y, te_p)), 3),
        "average_precision": round(float(average_precision_score(y, te_p)), 3),
        "top10_late_rate": round(float(y[top10].mean()), 4),
        "top10_capture": round(float(y[top10].sum() / max(1, y.sum())), 3),
        "high_cutoff": round(high_cut, 4), "medium_cutoff": round(medium_cut, 4),
        "late_rate_by_decile": [round(float(y[deciles.values == d].mean()), 4) for d in range(9, -1, -1)],
    }
    print(f"  AUC {risk_metrics['roc_auc']}, top 10% riskiest orders hold "
          f"{risk_metrics['top10_capture']:.0%} of late deliveries")

    # ---------------- 3. Freight ----------------
    print("Training freight model...")
    it = F.item_physics(items.merge(orders[["order_id", "purchase_ts", "customer_zip", "customer_state"]], on="order_id"))
    c_pts = np.array([geo.point(z, s) for z, s in zip(it.customer_zip, it.customer_state)])
    s_pts = np.array([geo.point(z, s) for z, s in zip(it.seller_zip, it.seller_state)])
    it["distance_km"] = F.haversine_km(c_pts[:, 0], c_pts[:, 1], s_pts[:, 0], s_pts[:, 1])
    it["same_state"] = (it.customer_state == it.seller_state).astype(int)
    it_tr, it_te = it[it.purchase_ts < TRAIN_END], it[(it.purchase_ts >= CALIB_END) & (it.purchase_ts < TEST_END)]
    freight = HistGradientBoostingRegressor(max_iter=400, learning_rate=0.06, max_leaf_nodes=63,
                                            categorical_features=F.categorical_mask(F.FREIGHT_FEATURES),
                                            random_state=RANDOM_STATE)
    freight.fit(F.transform(it_tr, encoders, F.FREIGHT_FEATURES), np.log1p(it_tr["freight_value"]))
    pred = np.expm1(freight.predict(F.transform(it_te, encoders, F.FREIGHT_FEATURES)))
    lane_median = it_tr.groupby(["seller_state", "customer_state"])["freight_value"].median()
    baseline = it_te.set_index(["seller_state", "customer_state"]).index.map(lane_median).fillna(it_tr.freight_value.median())
    freight_metrics = {
        "test_items": int(len(it_te)),
        "mae": round(float(mean_absolute_error(it_te.freight_value, pred)), 2),
        "baseline_mae": round(float(mean_absolute_error(it_te.freight_value, baseline)), 2),
        "median_freight": round(float(it_te.freight_value.median()), 2),
    }
    print(f"  MAE R$ {freight_metrics['mae']} (route-average baseline R$ {freight_metrics['baseline_mae']})")

    # ---------------- reference data for live predictions ----------------
    # Live orders use each seller's FULL track record (everything up to the end of the dataset).
    full = delivered.copy()
    full["handling"] = ((full["order_delivered_carrier_date"] - full["order_approved_at"]).dt.total_seconds() / 86400).clip(0, 60)
    ref = full.groupby("seller_id").agg(orders=("order_id", "size"), late=("late", "sum"),
                                        handling_days=("handling", "median")).reset_index()
    ref["late_rate"] = F.smoothed_late_rate(ref["late"], ref["orders"], global_late)
    conn.execute("DROP TABLE IF EXISTS ref_seller_logistics")
    ref[["seller_id", "orders", "late_rate", "handling_days"]].to_sql("ref_seller_logistics", conn, index=False)
    conn.execute("CREATE UNIQUE INDEX ux_ref_seller_logistics ON ref_seller_logistics(seller_id)")
    conn.commit()

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    bundle = {
        "eta": eta, "risk": risk, "freight": freight, "encoders": encoders,
        "safety_margin_log": offset, "risk_cutoffs": {"high": high_cut, "medium": medium_cut},
        "global_late_rate": global_late,
        "defaults": {"seller_handling_days": float(full["handling"].median())},
        "latest_recent": latest_recent,  # live orders use the most recent network numbers we have
        "trained_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sklearn_version": sklearn.__version__,
        "split": {"train_before": TRAIN_END, "calibration": [TRAIN_END, CALIB_END], "test": [CALIB_END, TEST_END]},
        "metrics": {"eta": eta_metrics, "risk": risk_metrics, "freight": freight_metrics},
    }
    joblib.dump(bundle, MODELS_DIR / "logistics.joblib")
    (MODELS_DIR / "logistics_metrics.json").write_text(json.dumps(bundle["metrics"], indent=2))
    print(f"Saved {MODELS_DIR / 'logistics.joblib'}")

    # ---------------- 4. Reviews (Module 4) ----------------
    print("Training review model...")
    rm = reviews.train_and_store(conn)
    print(f"  sentiment AUC {rm['roc_auc']} on {rm['test_reviews']:,} reviews written from {rm['test_from']}")
    print(f"\nAll models saved in {MODELS_DIR} ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
