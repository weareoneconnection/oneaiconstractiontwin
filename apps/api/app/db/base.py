from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.core.config import settings


class Base(DeclarativeBase):
    pass


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine_kwargs = {"future": True, "connect_args": connect_args, "pool_pre_ping": True}
if not settings.database_url.startswith("sqlite"):
    engine_kwargs.update({"pool_size": settings.database_pool_size, "max_overflow": settings.database_max_overflow})
engine = create_engine(settings.database_url, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
