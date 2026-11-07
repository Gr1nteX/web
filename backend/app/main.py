import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import config
from .db import init_db
from .routers import auth, tasks
from .worker import Worker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    worker = Worker(config.WORKER_SLOTS)
    worker.start()
    yield
    worker.stop()


app = FastAPI(title="Розв'язування СЛАР", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(tasks.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "server": config.SERVER_NAME}


if config.FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=config.FRONTEND_DIR, html=True), name="frontend")
