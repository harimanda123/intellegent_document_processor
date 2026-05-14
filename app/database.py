from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.config import settings


# ── Engine ─────────────────────────────────────────────────────────────────
# SQLite by default.
# To switch to PostgreSQL, just change DATABASE_URL in .env:
# DATABASE_URL=postgresql://user:password@localhost/idp
# No code change needed.

connect_args = {}
if "sqlite" in settings.database_url:
    # SQLite needs this for FastAPI background tasks
    connect_args = {"check_same_thread": False}

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    echo=False,  # Set True to see SQL queries in terminal (useful for debugging)
)

# ── Session ─────────────────────────────────────────────────────────────────
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


# ── Base ────────────────────────────────────────────────────────────────────
class Base(DeclarativeBase):
    pass


# ── Dependency ──────────────────────────────────────────────────────────────
def get_db():
    """
    FastAPI dependency.
    Yields a DB session and always closes it after the request.
    Usage in router:
        db: Session = Depends(get_db)
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Init ────────────────────────────────────────────────────────────────────
def init_db():
    """
    Creates all tables on startup.
    Called once from app lifespan in main.py.
    """
    from app.models import document, schema  # noqa: F401 — registers models    Base.metadata.create_all(bind=engine)