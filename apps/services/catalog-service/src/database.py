from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker
from .config import DATABASE_URL

engine_kwargs = {}
if "sqlite" in DATABASE_URL:
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    engine_kwargs.update({
        "pool_size": 10,
        "max_overflow": 20,
        "pool_pre_ping": True,
        "pool_recycle": 300,
    })

engine = create_engine(DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def init_db():
    if "postgresql" in DATABASE_URL:
        with engine.connect() as conn:
            conn.execute(text("CREATE SCHEMA IF NOT EXISTS catalog;"))
            conn.commit()
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
