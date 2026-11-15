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
HEARTBEAT_SECONDS = _int("HEARTBEAT_SECONDS", 3)
SERVER_TIMEOUT_SECONDS = _int("SERVER_TIMEOUT_SECONDS", 15)
AUTO_SCALED = os.getenv("AUTO_SCALED") == "1"
MAX_SERVERS = _int("MAX_SERVERS", 3)
TEMPLATE_SERVICE = os.getenv("TEMPLATE_SERVICE", "app1")
NGINX_SERVICE = os.getenv("NGINX_SERVICE", "nginx")
SCALE_INTERVAL_SECONDS = _int("SCALE_INTERVAL_SECONDS", 5)
SCALE_COOLDOWN_SECONDS = _int("SCALE_COOLDOWN_SECONDS", 20)
IDLE_SECONDS_BEFORE_STOP = _int("IDLE_SECONDS_BEFORE_STOP", 30)
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
