from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db():
    from backend.db.models import Base
    Base.metadata.create_all(engine)
