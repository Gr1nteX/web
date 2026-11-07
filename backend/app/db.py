import logging
import time

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from . import config

log = logging.getLogger(__name__)

engine = create_engine(config.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    with SessionLocal() as db:
        yield db


def init_db(attempts: int = 30) -> None:
    from . import models  # noqa: F401

    for attempt in range(1, attempts + 1):
        try:
            with engine.begin() as conn:
                conn.execute(text("SELECT pg_advisory_xact_lock(1)"))
                Base.metadata.create_all(conn)
            return
        except OperationalError:
            log.warning("База даних недоступна, спроба %d/%d", attempt, attempts)
            time.sleep(2)
    raise RuntimeError("Не вдалося підключитися до бази даних")
