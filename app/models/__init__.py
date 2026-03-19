# Import all models here in dependency order.
# SQLAlchemy resolves relationship() string references (e.g. "Project")
# only after all models are registered in Base.metadata.
# Importing everything here guarantees they're all visible before
# any relationship wiring happens — regardless of which file imports first.

from app.models.users import User, UserRole
from app.models.token import RefreshToken
from app.models.project import Project, ProjectStatus
from app.models.task import Task, TaskStatus, TaskPriority
from app.models.session import CodingSession
from app.models.journal import JournalEntry

__all__ = [
    "User",
    "UserRole",
    "RefreshToken",
    "Project",
    "ProjectStatus",
    "Task",
    "TaskStatus",
    "TaskPriority",
    "CodingSession",
    "JournalEntry",
]
