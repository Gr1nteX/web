import heapq
import statistics

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import config
from .models import DONE, QUEUED, RUNNING, Server, Task, server_alive

START_OVERHEAD = 0.5
DEFAULT_SECONDS_PER_UNIT = 1e-9


def seconds_per_unit(db: Session) -> float:
    rows = db.execute(
        select(Task.n, Task.started_at, Task.finished_at)
        .where(Task.status == DONE, Task.n >= 300)
        .order_by(Task.id.desc())
        .limit(20)
    ).all()
    samples = [
        ((finished - started).total_seconds() - START_OVERHEAD) / n**3
        for n, started, finished in rows
        if started and finished
    ]
    samples = [s for s in samples if s > 0]
    return statistics.median(samples) if samples else DEFAULT_SECONDS_PER_UNIT


def duration(n: int, rate: float) -> float:
    return min(START_OVERHEAD + rate * n**3, config.TIME_LIMIT_SECONDS)


def queue_estimates(db: Session) -> dict[int, tuple[int, float | None]]:
    queued = db.execute(select(Task.id, Task.n).where(Task.status == QUEUED).order_by(Task.id)).all()
    if not queued:
        return {}

    slots = db.scalar(select(func.coalesce(func.sum(Server.slots), 0)).where(server_alive()))
    if not slots:
        return {task_id: (position, None) for position, (task_id, _) in enumerate(queued, 1)}

    rate = seconds_per_unit(db)
    running = db.execute(select(Task.n, Task.progress).where(Task.status == RUNNING)).all()
    free_at = sorted(duration(n, rate) * (1 - progress / 100) for n, progress in running)[:slots]
    free_at += [0.0] * (slots - len(free_at))
    heapq.heapify(free_at)

    estimates = {}
    for position, (task_id, n) in enumerate(queued, 1):
        start = heapq.heappop(free_at)
        estimates[task_id] = (position, round(start, 1))
        heapq.heappush(free_at, start + duration(n, rate))
    return estimates
