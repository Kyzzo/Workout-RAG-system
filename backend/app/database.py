# engine, SessionLocal, DeclarativeBase
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = "postgresql+psycopg://user:password@localhost:5432/workout_tracker"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()