from app.db.sessions import engine
from app.db.base import Base
from app.models.users import User


def init_db():
    Base.metadata.create_all(bind=engine)
