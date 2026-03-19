import enum
from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Boolean,
    Enum as SAEnum,
    ForeignKey,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import relationship
from app.db.base import Base


class ProjectStatus(str, enum.Enum):
    planning = "planning"
    in_progress = "in_progress"
    completed = "completed"
    on_hold = "on_hold"


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(
        SAEnum(ProjectStatus), nullable=False, default=ProjectStatus.planning
    )
    tech_stack = Column(ARRAY(String), nullable=False, default=list)
    github_url = Column(String(500), nullable=True)
    live_url = Column(String(500), nullable=True)
    is_public = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships — SQLAlchemy loads these on access
    owner = relationship("User", back_populates="projects")
    tasks = relationship("Task", back_populates="project", cascade="all, delete-orphan")
    sessions = relationship("CodingSession", back_populates="project")
