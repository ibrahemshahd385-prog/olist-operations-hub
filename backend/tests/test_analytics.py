"""Module 4: the management numbers match Task 1, and the review topics read Portuguese correctly."""
import pytest

from app.ml import reviews
from app.services import analytics


def test_overview_matches_task_1(conn):
    k = analytics.overview(conn)["kpi"]
    assert k["orders"] == 99441
    assert abs(k["repeat_rate"] - 0.0312) < 0.0005          # Task 1: 3.12%
    assert abs(k["on_time_rate"] - (1 - 0.0677)) < 0.001    # Task 1: 6.77% late


def test_reviews_collapse_after_the_promise(conn):
    d = {b["bucket"]: b["avg_review"] for b in analytics.overview(conn)["delay_vs_review"]}
    assert d["1-7 early"] > 4 and d["4-7 late"] < 2.5


@pytest.mark.parametrize("text, topic", [
    ("Ainda não recebi o produto", "not_received"),
    ("Chegou com atraso de uma semana", "late"),
    ("veio só um dos produtos", "incomplete"),
    ("Produto veio quebrado", "damaged"),
    ("Recebi um produto diferente do que pedi", "wrong_item"),
    ("Não veio a nota fiscal", "invoice"),
    ("Chegou antes do prazo, recomendo!", "praise_speed"),
])
def test_topics_in_portuguese(text, topic):
    assert topic in reviews.topics_of(text)


def test_praise_is_not_a_complaint():
    assert not set(reviews.topics_of("Excelente produto, chegou antes do prazo")) & set(reviews.COMPLAINTS)


@pytest.mark.skipif(not reviews.available(), reason="Train first: python -m scripts.train_models")
def test_sentiment_model():
    assert reviews.analyze("Péssimo, não recebi e ninguém responde")["sentiment"] > 0.8
    assert reviews.analyze("Excelente, chegou antes do prazo. Recomendo!")["sentiment"] < 0.2
