import os
import socket
from pathlib import Path


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://solver:solver@localhost:5432/solver")
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-me-in-production")
TOKEN_TTL_MINUTES = _int("TOKEN_TTL_MINUTES", 720)
SERVER_NAME = os.getenv("SERVER_NAME") or socket.gethostname()
FRONTEND_DIR = Path(os.getenv("FRONTEND_DIR", Path(__file__).resolve().parents[2] / "frontend"))

MAX_N = _int("MAX_N", 3000)
MAX_N_MANUAL = _int("MAX_N_MANUAL", 20)
TIME_LIMIT_SECONDS = _int("TIME_LIMIT_SECONDS", 60)
MAX_ACTIVE_TASKS = _int("MAX_ACTIVE_TASKS", 3)
MAX_HISTORY = _int("MAX_HISTORY", 50)
WORKER_SLOTS = _int("WORKER_SLOTS", 2)
