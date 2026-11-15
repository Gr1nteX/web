import logging
import multiprocessing
import threading
import time

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert

from . import config
from .db import SessionLocal
from .metrics import Metrics
from .models import DONE, FAILED, QUEUED, RUNNING, Server, Task, server_alive
from .solver import SolverError, solve

log = logging.getLogger(__name__)
mp = multiprocessing.get_context("spawn")


def own_running(task_id: int) -> tuple:
    return Task.id == task_id, Task.status == RUNNING, Task.server == config.SERVER_NAME


def requeue(db, *condition) -> None:
    db.execute(
        update(Task)
        .where(*condition)
        .values(status=QUEUED, progress=0.0, stage="Очікує в черзі", server=None, started_at=None)
    )


def finish_task(task_id: int, **values) -> None:
    with SessionLocal() as db:
        db.execute(update(Task).where(*own_running(task_id)).values(finished_at=func.now(), **values))
        db.commit()


def run_task(task_id: int) -> None:
    with SessionLocal() as db:
        params = db.get(Task, task_id).params

    last_write = 0.0
    last_stage = None

    def report(progress: float, stage: str) -> None:
        nonlocal last_write, last_stage
        now = time.monotonic()
        if stage == last_stage and now - last_write < 0.5:
            return
        last_write, last_stage = now, stage
        with SessionLocal() as db:
            db.execute(update(Task).where(*own_running(task_id)).values(progress=round(progress, 1), stage=stage))
            db.commit()

    try:
        result = solve(params, report)
    except SolverError as exc:
        finish_task(task_id, status=FAILED, stage="Помилка", error=str(exc))
        return
    finish_task(task_id, status=DONE, progress=100.0, stage="Готово", result=result)


class Worker:
    def __init__(self, slots: int):
        self.slots = slots
        self.metrics = Metrics()
        self.stop_event = threading.Event()
        self.threads: list[threading.Thread] = []

    def start(self) -> None:
        with SessionLocal() as db:
            requeue(db, Task.status == RUNNING, Task.server == config.SERVER_NAME)
            db.execute(delete(Server).where(Server.name == config.SERVER_NAME))
            db.commit()
        self.beat()

        targets = [self.heartbeat] + [self.loop] * self.slots
        for target in targets:
            thread = threading.Thread(target=target, daemon=True)
            thread.start()
            self.threads.append(thread)
        log.info("Сервер %s: обчислювальних слотів %d", config.SERVER_NAME, self.slots)

    def stop(self) -> None:
        self.stop_event.set()
        for thread in self.threads:
            thread.join(timeout=10)
        with SessionLocal() as db:
            db.execute(delete(Server).where(Server.name == config.SERVER_NAME))
            db.commit()

    def beat(self) -> None:
        with SessionLocal() as db:
            stmt = insert(Server).values(
                name=config.SERVER_NAME,
                slots=self.slots,
                auto=config.AUTO_SCALED,
                cpu=self.metrics.cpu_percent(),
                memory_mb=self.metrics.memory_mb(),
            )
            db.execute(
                stmt.on_conflict_do_update(
                    index_elements=[Server.name],
                    set_={
                        "slots": stmt.excluded.slots,
                        "cpu": stmt.excluded.cpu,
                        "memory_mb": stmt.excluded.memory_mb,
                        "last_seen": func.now(),
                    },
                )
            )
            requeue(db, Task.status == RUNNING, Task.server.not_in(select(Server.name).where(server_alive())))
            db.execute(delete(Server).where(~server_alive()))
            db.commit()

    def heartbeat(self) -> None:
        while not self.stop_event.wait(config.HEARTBEAT_SECONDS):
            try:
                self.beat()
            except Exception:
                log.exception("Помилка heartbeat")

    def claim(self) -> int | None:
        with SessionLocal() as db:
            task = db.scalars(
                select(Task)
                .where(Task.status == QUEUED)
                .order_by(Task.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            ).first()
            if task is None:
                return None
            task.status = RUNNING
            task.server = config.SERVER_NAME
            task.started_at = func.now()
            task.progress = 0.0
            task.stage = "Запуск"
            db.commit()
            return task.id

    def is_mine(self, task_id: int) -> bool:
        with SessionLocal() as db:
            return db.scalar(select(Task.id).where(*own_running(task_id))) is not None

    def loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                task_id = self.claim()
                if task_id is None:
                    self.stop_event.wait(1)
                    continue
                self.execute(task_id)
            except Exception:
                log.exception("Помилка обчислювального слота")
                self.stop_event.wait(3)

    def execute(self, task_id: int) -> None:
        log.info("Задача %d: старт на %s", task_id, config.SERVER_NAME)
        process = mp.Process(target=run_task, args=(task_id,), daemon=True)
        started = time.monotonic()
        process.start()

        while True:
            process.join(0.5)
            if not process.is_alive():
                break
            if not self.is_mine(task_id):
                self.kill(process)
                log.info("Задача %d: скасована", task_id)
                return
            if time.monotonic() - started > config.TIME_LIMIT_SECONDS:
                self.kill(process)
                finish_task(
                    task_id,
                    status=FAILED,
                    stage="Перевищено ліміт часу",
                    error=f"Перевищено максимальний час обчислення ({config.TIME_LIMIT_SECONDS} с)",
                )
                log.info("Задача %d: перевищено ліміт часу", task_id)
                return
            if self.stop_event.is_set():
                self.kill(process)
                with SessionLocal() as db:
                    requeue(db, *own_running(task_id))
                    db.commit()
                return

        if process.exitcode != 0:
            finish_task(task_id, status=FAILED, stage="Помилка", error="Обчислення завершилось аварійно")
        log.info("Задача %d: завершена", task_id)

    @staticmethod
    def kill(process) -> None:
        process.terminate()
        process.join(5)
        if process.is_alive():
            process.kill()
            process.join()
