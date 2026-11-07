import math
import random

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from .. import config
from ..auth import get_current_user
from ..db import get_db
from ..models import ACTIVE_STATUSES, CANCELLED, FINISHED_STATUSES, Task, User
from ..schemas import LimitsOut, TaskCreate, TaskDetail, TaskOut

router = APIRouter(prefix="/api", tags=["tasks"])


def bad_request(message: str) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, message)


def validate(data: TaskCreate) -> tuple[int, dict]:
    if data.mode == "random":
        if data.n is None:
            raise bad_request("Вкажіть кількість невідомих")
        if not 2 <= data.n <= config.MAX_N:
            raise bad_request(f"Кількість невідомих має бути від 2 до {config.MAX_N}")
        seed = data.seed if data.seed is not None else random.randint(0, 2**31 - 1)
        return data.n, {"mode": "random", "n": data.n, "seed": seed}

    if not data.a or data.b is None:
        raise bad_request("Введіть матрицю коефіцієнтів і стовпець вільних членів")
    n = len(data.a)
    if not 2 <= n <= config.MAX_N_MANUAL:
        raise bad_request(f"При ручному введенні кількість невідомих має бути від 2 до {config.MAX_N_MANUAL}")
    if any(len(row) != n for row in data.a) or len(data.b) != n:
        raise bad_request("Матриця має бути квадратною, а кількість вільних членів дорівнювати кількості рівнянь")
    if not all(math.isfinite(v) for row in data.a for v in row) or not all(math.isfinite(v) for v in data.b):
        raise bad_request("Коефіцієнти мають бути скінченними числами")
    return n, {"mode": "manual", "a": data.a, "b": data.b}


def to_out(task: Task) -> TaskOut:
    return TaskOut.model_validate(task_fields(task))


def task_fields(task: Task) -> dict:
    return {
        "id": task.id,
        "n": task.n,
        "mode": task.params["mode"],
        "status": task.status,
        "progress": task.progress,
        "stage": task.stage,
        "error": task.error,
        "server": task.server,
        "created_at": task.created_at,
        "started_at": task.started_at,
        "finished_at": task.finished_at,
    }


def own_task(task_id: int, user: User, db: Session) -> Task:
    task = db.get(Task, task_id)
    if task is None or task.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Задачу не знайдено")
    return task


def trim_history(db: Session, user_id: int) -> None:
    old_ids = db.scalars(
        select(Task.id)
        .where(Task.user_id == user_id)
        .order_by(Task.id.desc())
        .offset(config.MAX_HISTORY)
    ).all()
    if old_ids:
        db.execute(delete(Task).where(Task.id.in_(old_ids), Task.status.in_(FINISHED_STATUSES)))


@router.get("/limits", response_model=LimitsOut)
def limits():
    return LimitsOut(
        max_n=config.MAX_N,
        max_n_manual=config.MAX_N_MANUAL,
        time_limit_seconds=config.TIME_LIMIT_SECONDS,
        max_active_tasks=config.MAX_ACTIVE_TASKS,
        max_history=config.MAX_HISTORY,
    )


@router.post("/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
def create_task(data: TaskCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    n, params = validate(data)

    db.execute(select(User.id).where(User.id == user.id).with_for_update())
    active = db.scalar(
        select(func.count()).select_from(Task).where(Task.user_id == user.id, Task.status.in_(ACTIVE_STATUSES))
    )
    if active >= config.MAX_ACTIVE_TASKS:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Досягнуто ліміт одночасних задач ({config.MAX_ACTIVE_TASKS}). "
            "Дочекайтеся завершення або скасуйте одну з них",
        )

    task = Task(user_id=user.id, n=n, params=params)
    db.add(task)
    db.flush()
    trim_history(db, user.id)
    db.commit()
    db.refresh(task)
    return to_out(task)


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tasks = db.scalars(select(Task).where(Task.user_id == user.id).order_by(Task.id.desc())).all()
    return [to_out(t) for t in tasks]


@router.get("/tasks/{task_id}", response_model=TaskDetail)
def get_task(task_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = own_task(task_id, user, db)
    return TaskDetail.model_validate({**task_fields(task), "seed": task.params.get("seed"), "result": task.result})


@router.post("/tasks/{task_id}/cancel", response_model=TaskOut)
def cancel_task(task_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = own_task(task_id, user, db)
    result = db.execute(
        update(Task)
        .where(Task.id == task.id, Task.status.in_(ACTIVE_STATUSES))
        .values(status=CANCELLED, stage="Скасовано користувачем", finished_at=func.now())
    )
    db.commit()
    if result.rowcount == 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "Задачу вже завершено")
    db.refresh(task)
    return to_out(task)
