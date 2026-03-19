from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

# ── Import your app's config and Base ────────────────────────────────────────
from app.core.config import settings
from app.db.base import Base

# Import every model so Alembic can see them in Base.metadata.
# If you add a new model later and forget to import it here,
# Alembic's autogenerate will not detect it.
from app.models.users import User  # noqa: F401
from app.models.token import RefreshToken  # noqa: F401
from app.models.project import Project  # noqa: F401
from app.models.task import Task  # noqa: F401
from app.models.session import CodingSession  # noqa: F401
from app.models.journal import JournalEntry  # noqa: F401

# ── Alembic config object ─────────────────────────────────────────────────────
config = context.config

# Inject the real DATABASE_URL from your .env — overrides alembic.ini
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# Set up Python logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# This is the metadata Alembic diffs against your database
target_metadata = Base.metadata


# ── Offline mode (generates SQL without connecting) ───────────────────────────
def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


# ── Online mode (connects to DB and runs migrations) ─────────────────────────
def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # NullPool: don't reuse connections during migrations
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Tells Alembic to also detect column type changes, not just additions/removals
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
