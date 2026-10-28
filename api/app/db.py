import os

from sqlmodel import Session, SQLModel, create_engine

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./comat.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)


def init_db() -> None:
    import app.models  # noqa: F401  (register tables with SQLModel metadata)

    SQLModel.metadata.create_all(engine)


def get_session() -> Session:
    return Session(engine)
