from pydantic import BaseModel
from datetime import date
from typing import Optional


class DailyActivity(BaseModel):
    """One row in the daily breakdown — one entry per day that has sessions."""

    date: date
    total_mins: int
    total_hours: float
    total_sessions: int


class WeeklyActivity(BaseModel):
    """One row in the weekly breakdown — one entry per calendar week."""

    week_start: date  # Monday of that week
    total_mins: int
    total_hours: float
    total_sessions: int


class ProjectBreakdown(BaseModel):
    """Time breakdown for one project."""

    project_id: int
    project_title: str
    total_mins: int
    total_hours: float
    total_sessions: int


class StreakData(BaseModel):
    """Coding streak metrics."""

    current_streak: int  # consecutive days coded up to today/yesterday
    longest_streak: int  # longest consecutive run ever
    last_coded_date: Optional[date]  # most recent session_date — None if no sessions


class AnalyticsSummary(BaseModel):
    """
    Lifetime totals for the authenticated user.
    The top-level dashboard numbers — the first thing the user sees.
    """

    total_mins: int
    total_hours: float
    total_sessions: int
    total_projects: int
    total_tasks_completed: int
    streak: StreakData
