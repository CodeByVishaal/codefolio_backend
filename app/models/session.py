from datetime import datetime, date, timezone
from sqlalchemy import Column, Integer, String, DateTime, Date, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.db.base import Base


class CodingSession(Base):
    __tablename__ = "coding_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id = Column(
        Integer,
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    duration_mins = Column(Integer, nullable=False)  # total session length in minutes
    session_date = Column(
        Date, nullable=False, index=True
    )  # the calendar date — used for streak/daily aggregation
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    owner = relationship("User", back_populates="sessions")
    project = relationship("Project", back_populates="sessions")
