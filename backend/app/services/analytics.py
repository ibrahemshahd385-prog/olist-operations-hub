"""Module 4: the management view of the business, and what customers write.

Everything here reads the historical dataset, which never changes, so each
result is computed once per server run and kept in memory.
"""
import json
import sqlite3
from collections import Counter

import pandas as pd

from ..db import rows_to_dicts
from ..ml import reviews

_cache = {}

# Delivery against the promise, in days (negative = early). Labels are what the chart shows.
DELAY_BUCKETS = [
    (-999, -15, "15+ days early"), (-14, -8, "8-14 early"), (-7, -1, "1-7 early"), (0, 0, "On the day"),
    (1, 3, "1-3 late"), (4, 7, "4-7 late"), (8, 14, "8-14 late"), (15, 999, "15+ late"),
]


def overview(conn: sqlite3.Connection) -> dict:
    if "overview" in _cache:
        return _cache["overview"]

    kpi = dict(conn.execute(
        """SELECT COUNT(*) AS orders,
                  SUM(order_status = 'delivered') AS delivered,
                  (SELECT COUNT(DISTINCT customer_unique_id) FROM customers c JOIN orders o2
                     ON o2.customer_id = c.customer_id WHERE o2.source = 'historical') AS customers,
                  (SELECT ROUND(SUM(price), 2) FROM order_items i JOIN orders o3 ON o3.order_id = i.order_id
                     WHERE o3.source = 'historical') AS gmv,
                  (SELECT ROUND(AVG(review_score), 3) FROM order_reviews) AS avg_review
           FROM orders o WHERE source = 'historical'""").fetchone())
    repeat = conn.execute(
        """SELECT AVG(n > 1) FROM (SELECT COUNT(*) AS n FROM orders o JOIN customers c ON c.customer_id = o.customer_id
           WHERE o.source = 'historical' GROUP BY c.customer_unique_id)""").fetchone()[0]
    on_time = conn.execute(
        """SELECT AVG(date(order_delivered_customer_date) <= date(order_estimated_delivery_date))
           FROM orders WHERE source = 'historical' AND order_status = 'delivered'
             AND order_delivered_customer_date IS NOT NULL""").fetchone()[0]
    kpi.update(repeat_rate=round(repeat, 4), on_time_rate=round(on_time, 4),
               avg_ticket=round(kpi["gmv"] / kpi["orders"], 2))

    # 2016 and the last weeks of 2018 have only a handful of orders (data collection edges)
    monthly = rows_to_dicts(conn.execute(
        """SELECT strftime('%Y-%m', o.order_purchase_timestamp) AS month, COUNT(DISTINCT o.order_id) AS orders,
                  ROUND(SUM(i.price), 2) AS revenue
           FROM orders o JOIN order_items i ON i.order_id = o.order_id
           WHERE o.source = 'historical' AND o.order_purchase_timestamp >= '2017-01-01'
             AND o.order_purchase_timestamp < '2018-09-01'
           GROUP BY month ORDER BY month""").fetchall())

    # Average review by how early or late the order arrived (the Task 1 finding, in detail)
    d = pd.read_sql(
        """SELECT CAST(julianday(date(o.order_delivered_customer_date)) - julianday(date(o.order_estimated_delivery_date)) AS INTEGER) AS diff,
                  r.review_score
           FROM orders o JOIN order_reviews r ON r.order_id = o.order_id
           WHERE o.source = 'historical' AND o.order_status = 'delivered' AND o.order_delivered_customer_date IS NOT NULL""", conn)
    delay = []
    for lo, hi, label in DELAY_BUCKETS:
        part = d[(d["diff"] >= lo) & (d["diff"] <= hi)]
        delay.append({"bucket": label, "orders": int(len(part)), "avg_review": round(float(part.review_score.mean()), 2),
                      "one_star": round(float((part.review_score == 1).mean()), 4)})

    categories = rows_to_dicts(conn.execute(
        """WITH per_order AS (
               SELECT i.order_id, COALESCE(p.product_category_name_english, 'uncategorized') AS category,
                      SUM(i.price) AS revenue
               FROM order_items i JOIN products p ON p.product_id = i.product_id
               JOIN orders o ON o.order_id = i.order_id AND o.source = 'historical'
               GROUP BY i.order_id, category)
           SELECT category, COUNT(*) AS orders, ROUND(SUM(revenue), 2) AS revenue,
                  ROUND(AVG((SELECT AVG(review_score) FROM order_reviews r WHERE r.order_id = per_order.order_id)), 2) AS avg_review
           FROM per_order GROUP BY category ORDER BY revenue DESC LIMIT 10""").fetchall())

    states = rows_to_dicts(conn.execute(
        """SELECT c.customer_state AS state, COUNT(*) AS orders,
                  ROUND(AVG(julianday(o.order_delivered_customer_date) - julianday(o.order_purchase_timestamp)), 1) AS avg_days,
                  ROUND(AVG(date(o.order_delivered_customer_date) > date(o.order_estimated_delivery_date)), 4) AS late_rate
           FROM orders o JOIN customers c ON c.customer_id = o.customer_id
           WHERE o.source = 'historical' AND o.order_status = 'delivered' AND o.order_delivered_customer_date IS NOT NULL
           GROUP BY state ORDER BY orders DESC LIMIT 10""").fetchall())

    payments = rows_to_dicts(conn.execute(
        """SELECT payment_type, COUNT(*) AS payments, ROUND(SUM(payment_value), 2) AS value,
                  ROUND(AVG(payment_installments), 2) AS avg_installments
           FROM order_payments p JOIN orders o ON o.order_id = p.order_id
           WHERE o.source = 'historical' AND payment_type != 'not_defined'
           GROUP BY payment_type ORDER BY value DESC""").fetchall())
    total_value = sum(p["value"] for p in payments)
    for p in payments:
        p["share"] = round(p["value"] / total_value, 4)

    _cache["overview"] = {"kpi": kpi, "monthly": monthly, "delay_vs_review": delay,
                          "categories": categories, "states": states, "payments": payments}
    return _cache["overview"]


def review_insights(conn: sqlite3.Connection) -> dict:
    """What customers complain about, where the model and the stars disagree, and how good the model is."""
    if "reviews" in _cache:
        return _cache["reviews"]
    rows = pd.read_sql(
        """SELECT ri.review_rowid, ri.order_id, ri.review_score, ri.sentiment, ri.topics,
                  date(o.order_delivered_customer_date) > date(o.order_estimated_delivery_date) AS late
           FROM review_insights ri LEFT JOIN orders o ON o.order_id = ri.order_id""", conn)
    if rows.empty:
        return {"available": False}
    rows["topics"] = rows["topics"].map(json.loads)
    neg, pos = rows[rows.review_score <= 2], rows[rows.review_score >= 4]

    def shares(part):
        c = Counter(t for ts in part.topics for t in ts)
        return {k: round(c.get(k, 0) / max(1, len(part)), 4) for k in reviews.TOPICS}

    neg_shares, pos_shares = shares(neg), shares(pos)
    topics = [{"key": k, "label": label, "negative_share": neg_shares[k], "positive_share": pos_shares[k],
               "complaint": k in reviews.COMPLAINTS}
              for k, (label, _) in reviews.TOPICS.items()]
    delivery_related = neg.topics.map(lambda ts: bool({"not_received", "late"} & set(ts))).mean()

    hidden = rows[(rows.review_score >= 4) & (rows.sentiment >= reviews.HIDDEN_COMPLAINT_CUTOFF)] \
        .sort_values("sentiment", ascending=False)
    examples = []
    if len(hidden):
        ids = ",".join(str(int(i)) for i in hidden.review_rowid.head(12))
        texts = {r["rowid"]: r for r in rows_to_dicts(conn.execute(
            f"""SELECT rowid, review_comment_title AS title, review_comment_message AS message, review_creation_date AS created
                FROM order_reviews WHERE rowid IN ({ids})""").fetchall())}
        for r in hidden.head(12).itertuples():
            t = texts.get(r.review_rowid, {})
            examples.append({"order_id": r.order_id, "stars": int(r.review_score), "negative": round(float(r.sentiment), 3),
                             "title": t.get("title"), "message": t.get("message"), "created": t.get("created"),
                             "topics": [reviews.TOPICS[k][0] for k in r.topics]})

    b = reviews._bundle()
    _cache["reviews"] = {
        "available": True,
        "with_text": int(len(rows)), "negative_reviews": int(len(neg)),
        "negative_no_topic": round(float((neg.topics.map(len) == 0).mean()), 4),
        "delivery_share_of_negative": round(float(delivery_related), 4),
        "topics": topics,
        "hidden_complaints": int(len(hidden)), "hidden_examples": examples,
        "model": b["metrics"] if b else None,
    }
    return _cache["reviews"]
