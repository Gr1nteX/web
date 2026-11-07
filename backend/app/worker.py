import logging
import multiprocessing
import threading
import time

from sqlalchemy import func, select, update

from . import config
from .db import SessionLocal
from .models import DONE, FAILED, QUEUED, RUNNING, Task
from .solver import SolverError, solve

log = logging.getLogger(__name__)
mp = multiprocessing.get_context("spawn")


def finish_task(task_id: int, **values) -> bool:
    with SessionLocal() as db:
        result = db.execute(
            update(Task)
            .where(Task.id == task_id, Task.status == RUNNING)
            .values(finished_at=func.now(), **values)
        )
        db.commit()
        return result.rowcount > 0


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
            db.execute(
                update(Task)
                .where(Task.id == task_id, Task.status == RUNNING)
                .values(progress=round(progress, 1), stage=stage)
            )
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
        self.stop_event = threading.Event()
        self.threads: list[threading.Thread] = []

    def start(self) -> None:
        self.requeue_orphans()
        for i in range(self.slots):
            thread = threading.Thread(target=self.loop, name=f"slot-{i + 1}", daemon=True)
            thread.start()
            self.threads.append(thread)
        log.info("Сервер %s: запущено %d обчислювальних слоти", config.SERVER_NAME, self.slots)

    def stop(self) -> None:
        self.stop_event.set()
        for thread in self.threads:
            thread.join(timeout=10)

    def requeue_orphans(self, task_id: int | None = None) -> None:
        condition = [Task.status == RUNNING, Task.server == config.SERVER_NAME]
        if task_id is not None:
            condition.append(Task.id == task_id)
        with SessionLocal() as db:
            db.execute(
                update(Task)
                .where(*condition)
                .values(status=QUEUED, progress=0.0, stage="Очікує в черзі", server=None, started_at=None)
            )
            db.commit()

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

    def status_of(self, task_id: int) -> str | None:
        with SessionLocal() as db:
            return db.scalar(select(Task.status).where(Task.id == task_id))

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
            if self.status_of(task_id) != RUNNING:
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
                self.requeue_orphans(task_id)
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
