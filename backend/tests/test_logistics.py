"""Module 2: features never peek into the future, models beat Olist's promise,
and predictions flow into real orders."""
import numpy as np
import pandas as pd
import pytest

from app.ml import features as F
from app.ml import predictor
from app.schemas import CustomerIn, QuoteIn
from app.services import logistics, orders, workflow
from conftest import make_order

needs_models = pytest.mark.skipif(not predictor.available(), reason="Train first: python -m scripts.train_models")


def test_haversine_sao_paulo_to_rio():
    km = F.haversine_km(-23.55, -46.63, -22.91, -43.17)   # city centres
    assert 350 < km < 370


def test_smoothing_pulls_new_sellers_to_the_average():
    assert F.smoothed_late_rate(1, 1, 0.07) < 0.2          # 1 late out of 1 is not "100% late"
    assert abs(F.smoothed_late_rate(50, 100, 0.07) - 0.5) < 0.05


def test_recent_window_does_not_include_the_same_day():
    daily = pd.DataFrame({"x": [1.0, 10.0]}, index=pd.to_datetime(["2018-01-01", "2018-01-02"]))
    w = F._window_sums(daily, 30)
    assert w.loc["2018-01-02", "x"] == 1.0                  # only the day before is known
    assert np.isnan(w.loc["2018-01-01", "x"])


@needs_models
def test_model_beats_olist_promise_on_unseen_months():
    m = predictor.metrics()["metrics"]["eta"]
    assert m["model_promise_mean_days"] < m["olist_promise_mean_days"]
    assert m["model_on_time"] >= 0.95
    assert predictor.metrics()["metrics"]["risk"]["roc_auc"] > 0.7


@needs_models
def test_quote_gives_shorter_promise_and_freight(conn, two_sellers):
    s = two_sellers[0]
    q = logistics.quote(conn, QuoteIn(
        customer=CustomerIn(zip_code_prefix="01310", city="sao paulo", state="SP"),
        items=[{"product_id": s["product_id"], "seller_id": s["seller_id"], "unit_price": s["price"], "quantity": 2}],
        payment_types=["credit_card"]))
    assert q["available"] and q["promise_days"] <= q["legacy_promise_days"]
    assert 0 <= q["risk"]["probability"] <= 1 and q["risk"]["level"] in ("low", "medium", "high")
    assert len(q["freight_estimates"]) == 1 and q["freight_estimates"][0]["per_unit"] > 0


@needs_models
def test_order_stores_prediction_and_shows_in_queue(conn, two_sellers):
    res = orders.create_order(conn, make_order([two_sellers[0]]))
    assert res["promise_source"] == "model"
    detail = orders.get_order(conn, res["order_id"])
    assert detail["prediction"]["promise_days"] == res["promised_days"]
    queue = logistics.at_risk(conn)
    assert [r["order_id"] for r in queue] == [res["order_id"]]
    workflow.apply_action(conn, res["order_id"], "cancel", "test")
    assert logistics.at_risk(conn) == []                    # closed orders leave the queue


@needs_models
def test_overpriced_freight_is_flagged(conn, two_sellers):
    s = {**two_sellers[0], "freight": 400.0, "price": 500.0}
    res = orders.create_order(conn, make_order([s]))
    assert any("expected" in w for w in res["warnings"])
