from datetime import date
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional

from app.core.deps import get_db, get_current_user
from app.models.users import User
from app.schemas.analytics import (
    AnalyticsSummary,
    DailyActivity,
    WeeklyActivity,
    ProjectBreakdown,
    StreakData,
)
from app.services import analytics_service

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary", response_model=AnalyticsSummary)
def get_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Lifetime totals for the dashboard header:
    total hours, sessions, projects, tasks completed, and streak.
    """
    return analytics_service.get_summary(current_user, db)


@router.get("/daily", response_model=list[DailyActivity])
def get_daily(
    date_from: date = Query(description="Start date (YYYY-MM-DD)"),
    date_to: date = Query(description="End date (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Day-by-day coding activity for a date range.
    Only days with at least one session are returned.
    Used for line charts, bar charts, and calendar heatmaps.
    """
    return analytics_service.get_daily(current_user, db, date_from, date_to)


@router.get("/weekly", response_model=list[WeeklyActivity])
def get_weekly(
    date_from: date = Query(description="Start date (YYYY-MM-DD)"),
    date_to: date = Query(description="End date (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Week-by-week coding activity. Each week starts on Monday.
    Used for the main productivity trend chart.
    """
    return analytics_service.get_weekly(current_user, db, date_from, date_to)


@router.get("/projects", response_model=list[ProjectBreakdown])
def get_project_breakdown(
    date_from: Optional[date] = Query(
        default=None, description="Start date (YYYY-MM-DD)"
    ),
    date_to: Optional[date] = Query(default=None, description="End date (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Per-project time breakdown — minutes and sessions per project.
    Date range is optional: omit both for all-time breakdown.
    Sessions with no project linked are excluded.
    Used for pie charts and project comparison views.
    """
    return analytics_service.get_project_breakdown(current_user, db, date_from, date_to)


@router.get("/streak", response_model=StreakData)
def get_streak(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Current coding streak and all-time longest streak.
    Streak breaks if no session is logged today or yesterday.
    """
    return analytics_service.get_streak(current_user, db)
