from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from config import DATABASE_URL

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
    echo=False
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Dependency для FastAPI"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Инициализировать БД (создать таблицы)"""
    Base.metadata.create_all(bind=engine)
