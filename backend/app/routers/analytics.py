"""HTTP endpoints for Module 4 (analytics & AI)."""
import sqlite3

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..db import get_conn
from ..ml import reviews
from ..services import analytics

router = APIRouter(prefix="/api/analytics", tags=["Analytics & AI"])


class ReviewText(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


@router.get("/overview")
def overview(conn: sqlite3.Connection = Depends(get_conn)):
    """Headline numbers, monthly sales, delay vs review, categories, states, payment mix."""
    return analytics.overview(conn)


@router.get("/reviews")
def review_insights(conn: sqlite3.Connection = Depends(get_conn)):
    """Complaint topics, hidden complaints and the sentiment model's test results."""
    return analytics.review_insights(conn)


@router.post("/reviews/analyze")
def analyze_review(body: ReviewText):
    """Score a review written in Portuguese: topics, how negative it reads, and why."""
    return reviews.analyze(body.text)
