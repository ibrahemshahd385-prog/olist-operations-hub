"""Module 3: the health score is bounded and explainable, and key accounts match Task 1."""
from app.services import sellers


def test_key_accounts_hold_two_thirds_of_revenue(conn):
    s = sellers.summary(conn)
    assert s["key_accounts"] == 309                       # top 10% of 3,095 sellers
    assert abs(s["key_revenue_share"] - 0.675) < 0.005    # Task 1: 67.5%
    assert abs(s["pareto"][9]["revenue_share"] - s["key_revenue_share"]) < 0.01   # the curve's 10% point


def test_scores_are_bounded_and_tiers_follow_cutoffs(conn):
    m = sellers.metrics(conn)
    scored = m[m.health.notna()]
    assert scored.health.between(0, 100).all()
    assert (scored[scored.tier == "A"].health >= 85).all()
    assert (scored[scored.tier == "D"].health < 55).all()
    assert (m[m.orders < sellers.MIN_ORDERS_FOR_SCORE].health.isna()).all()   # too few orders -> no score


def test_seller_detail_explains_itself(conn):
    top = sellers.list_sellers(conn, page_size=1)["items"][0]
    d = sellers.get_seller(conn, top["seller_id"])
    assert d["revenue_rank"] == 1
    assert {c["key"] for c in d["components"]} == set(sellers.WEIGHTS)
    weighted = sum(c["score"] * c["weight"] for c in d["components"])
    assert abs(weighted - d["health"]) <= 1                 # the score is exactly the weighted parts
    assert d["recommendations"]


def test_filters(conn):
    at_risk = sellers.list_sellers(conn, alert="key_account_at_risk", page_size=100)
    assert at_risk["total"] > 0
    assert all(r["key_account"] and r["tier"] in ("C", "D") for r in at_risk["items"])
    assert all(r["tier"] == "A" for r in sellers.list_sellers(conn, tier="A")["items"])
