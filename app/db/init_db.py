from app.db.sessions import engine
from app.db.base import Base

# Every model must be imported here so SQLAlchemy registers it
# before Base.metadata.create_all() runs.
# Missing an import = missing table in the database.
from app.models.users import User  # noqa: F401
from app.models.token import RefreshToken  # noqa: F401
from app.models.project import Project  # noqa: F401
from app.models.task import Task  # noqa: F401
from app.models.session import CodingSession  # noqa: F401
from app.models.journal import JournalEntry  # noqa: F401


def init_db():
    Base.metadata.create_all(bind=engine)
