"""Module 4: review intelligence.

43k customers wrote a comment in Portuguese. Nobody reads 43k comments, so:

  1. Topics: plain keyword rules (below) tag what each comment talks about:
     not received, late, wrong item, damaged, incomplete, quality, service,
     and the two kinds of praise. Rules, not a black box, so anyone can check
     why a comment got a tag.
  2. Sentiment: a small text model (TF-IDF + logistic regression) learns from
     the star ratings which words mean an unhappy customer. It is tested on
     reviews written after the ones it learned from.
  3. Hidden complaints: 4-5 star reviews whose text reads like a complaint.
     Star averages miss them; customer service should not.
"""
import json
import re
import sqlite3
import unicodedata
from datetime import datetime
from functools import lru_cache

import numpy as np
import pandas as pd

from ..config import MODELS_DIR

BUNDLE_PATH = MODELS_DIR / "reviews.joblib"
TEST_FROM = "2018-05-01"          # train on reviews written before, test on reviews after
HIDDEN_COMPLAINT_CUTOFF = 0.8     # negative probability above this on a 4-5 star review

# Each topic: label shown on screen + patterns on accent-free lower-case text.
TOPICS = {
    "not_received": ("Not received", [
        r"\bnao (recebi|recebemos|chegou|chegaram|foi entregue|foram entregues|entregaram|entregue)\b",
        r"\bainda nao\b", r"\bnunca chegou\b", r"\baguardando\b", r"\bcade\b", r"\bnao veio nada\b",
    ]),
    "late": ("Late delivery", [
        r"\batras", r"\bdemor", r"\bfora do prazo\b", r"\b(apos|depois) (do|o) prazo\b",
        r"\bpassou (do|o) prazo\b", r"\bultrapass", r"\bprazo (de entrega )?(vencido|expirado|esgotado)\b",
    ]),
    "wrong_item": ("Wrong item", [
        r"\berrad", r"\bdiferente\b", r"\boutro produto\b", r"\btrocad", r"\bnao (e|era) o (que|produto)\b",
        r"\bcor diferente\b", r"\bmodelo diferente\b",
    ]),
    "damaged": ("Damaged or defective", [
        r"\bdefeit", r"\bquebrad", r"\bdanific", r"\bavariad", r"\bamassad", r"\bnao funciona",
        r"\bparou de funcionar\b", r"\bestragad", r"\briscad", r"\bvazand", r"\brasgad",
    ]),
    "incomplete": ("Missing items", [
        r"\bfalt(a|ou|aram|ando)\b", r"\bincomplet", r"\bso (veio|vieram|recebi|chegou|chegaram) (um|uma|1|2|dois|duas)\b",
        r"\b(apenas|somente) (um|uma|1) (dos|das)\b", r"\bum dos produtos\b", r"\bmetade\b",
        r"\b(recebi|chegou|veio) (apenas|somente|so) (um|uma|1)\b",
    ]),
    "quality": ("Poor quality", [
        r"\bqualidade (ruim|baixa|inferior|pessima)\b", r"\bpessim", r"\bfragil\b", r"\bhorrivel\b",
        r"\bnao gostei\b", r"\bmal acabad", r"\bmaterial (ruim|fraco)\b", r"\bfalsificad", r"\bpirata\b",
    ]),
    "service": ("Service and refunds", [
        r"\batendimento\b", r"\bnao (respond|retorn|da retorno)", r"\bsem (resposta|retorno)\b",
        r"\bninguem (respond|retorn|resolve)",
        r"\bdevolu", r"\breembols", r"\bestorn", r"\bdinheiro de volta\b", r"\breclama",
    ]),
    "invoice": ("Invoice (nota fiscal)", [
        r"\bnota fiscal\b", r"\bnotas fiscais\b", r"\bnfe?\b", r"\bdanfe\b", r"\bcupom fiscal\b",
    ]),
    "praise_speed": ("Praise: fast delivery", [
        r"\bantes do (prazo|previsto|combinado)\b", r"\brapid", r"\bchegou cedo\b", r"\bbem antes\b",
    ]),
    "praise_product": ("Praise: product", [
        r"\bexcelente", r"\botim", r"\bperfeit", r"\brecomendo\b", r"\bamei\b", r"\badorei\b",
        r"\bsatisfeit", r"\bmaravilh", r"\bmuito bom\b", r"\bbom produto\b", r"\bde qualidade\b",
    ]),
}
COMPLAINTS = [k for k in TOPICS if not k.startswith("praise")]
_COMPILED = {k: [re.compile(p) for p in pats] for k, (_, pats) in TOPICS.items()}


def normalize(text: str) -> str:
    """'Não RECEBI!' -> 'nao recebi!' : lower case, no accents, single spaces."""
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", text.lower()).strip()


def topics_of(text: str) -> list:
    t = normalize(text)
    return [k for k, pats in _COMPILED.items() if any(p.search(t) for p in pats)]


# ---------------------------------------------------------------------------
# Training (called by scripts/train_models.py)
# ---------------------------------------------------------------------------

def _load(conn):
    r = pd.read_sql(
        """SELECT rowid AS review_rowid, order_id, review_score, review_comment_title AS title,
                  review_comment_message AS message, review_creation_date AS created
           FROM order_reviews
           WHERE review_comment_message IS NOT NULL OR review_comment_title IS NOT NULL""", conn)
    r["text"] = (r["title"].fillna("") + ". " + r["message"].fillna("")).str.strip(". ")
    r["norm"] = r["text"].map(normalize)
    return r[r["norm"].str.len() > 1].reset_index(drop=True)


def train_and_store(conn: sqlite3.Connection) -> dict:
    import joblib
    import sklearn
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, roc_auc_score

    r = _load(conn)
    labeled = r[r.review_score != 3].copy()
    labeled["negative"] = (labeled.review_score <= 2).astype(int)
    tr, te = labeled[labeled.created < TEST_FROM], labeled[labeled.created >= TEST_FROM]

    def make():
        vec = TfidfVectorizer(ngram_range=(1, 2), min_df=3, max_features=60000, sublinear_tf=True)
        clf = LogisticRegression(C=4.0, max_iter=2000, class_weight="balanced")
        return vec, clf

    vec, clf = make()
    clf.fit(vec.fit_transform(tr.norm), tr.negative)
    p = clf.predict_proba(vec.transform(te.norm))[:, 1]
    metrics = {
        "train_reviews": int(len(tr)), "test_reviews": int(len(te)), "test_from": TEST_FROM,
        "roc_auc": round(float(roc_auc_score(te.negative, p)), 3),
        "accuracy": round(float(accuracy_score(te.negative, p >= 0.5)), 3),
        "negative_share_test": round(float(te.negative.mean()), 3),
    }

    # final model: learn from every labeled review, then score all of them
    vec, clf = make()
    clf.fit(vec.fit_transform(labeled.norm), labeled.negative)
    r["sentiment"] = clf.predict_proba(vec.transform(r.norm))[:, 1]
    r["topics"] = r["text"].map(topics_of)

    words = np.array(vec.get_feature_names_out())
    order = np.argsort(clf.coef_[0])
    metrics["negative_words"] = words[order[::-1][:15]].tolist()
    metrics["positive_words"] = words[order[:15]].tolist()

    conn.execute("DELETE FROM review_insights")
    conn.executemany(
        "INSERT INTO review_insights (review_rowid, order_id, review_score, sentiment, topics) VALUES (?, ?, ?, ?, ?)",
        [(int(a), b, int(c), round(float(d), 4), json.dumps(e))
         for a, b, c, d, e in zip(r.review_rowid, r.order_id, r.review_score, r.sentiment, r.topics)])
    conn.commit()

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    bundle = {"vectorizer": vec, "model": clf, "metrics": metrics,
              "trained_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "sklearn_version": sklearn.__version__}
    joblib.dump(bundle, BUNDLE_PATH)
    reload()
    return metrics


# ---------------------------------------------------------------------------
# Live use
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _bundle():
    if not BUNDLE_PATH.exists():
        return None
    import joblib
    return joblib.load(BUNDLE_PATH)


def reload():
    _bundle.cache_clear()


def available() -> bool:
    return _bundle() is not None


def analyze(text: str) -> dict:
    """Topics, how negative the text reads, and the words that pushed it that way."""
    norm = normalize(text)
    out = {"topics": [{"key": k, "label": TOPICS[k][0]} for k in topics_of(text)], "sentiment": None, "drivers": []}
    b = _bundle()
    if b is None or not norm:
        return out
    x = b["vectorizer"].transform([norm])
    out["sentiment"] = round(float(b["model"].predict_proba(x)[0, 1]), 4)
    # contribution of each word present = its tf-idf weight x the model's coefficient
    coefs = b["model"].coef_[0]
    idx = x.nonzero()[1]
    contrib = sorted(((float(x[0, i] * coefs[i]), i) for i in idx), key=lambda c: -abs(c[0]))[:6]
    names = b["vectorizer"].get_feature_names_out()
    out["drivers"] = [{"term": names[i], "push": "negative" if v > 0 else "positive", "weight": round(v, 3)} for v, i in contrib]
    return out
