import json
import os
import socket
import time

import numpy as np
import psycopg

DATABASE_URL = os.environ["DATABASE_URL"]
NAME = socket.gethostname()
TIME_LIMIT = 60


class Cancelled(Exception):
    pass


def beat(db, task_id):
    db.execute(
        "INSERT INTO workers (name, task_id) VALUES (%s, %s) "
        "ON CONFLICT (name) DO UPDATE SET task_id = %s, last_seen = now()",
        (NAME, task_id, task_id),
    )


def requeue_lost_tasks(db):
    db.execute(
        "UPDATE tasks SET status = 'queued', progress = 0, worker = NULL "
        "WHERE status = 'running' AND worker NOT IN "
        "(SELECT name FROM workers WHERE last_seen > now() - interval '15 seconds')"
    )


def claim_task(db):
    with db.transaction():
        task = db.execute(
            "SELECT id, n, matrix FROM tasks WHERE status = 'queued' ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED"
        ).fetchone()
        if task is not None:
            db.execute(
                "UPDATE tasks SET status = 'running', worker = %s, started_at = now() WHERE id = %s",
                (NAME, task[0]),
            )
    return task


def report(db, task_id, progress, started):
    if time.time() - started > TIME_LIMIT:
        raise TimeoutError
    beat(db, task_id)
    updated = db.execute(
        "UPDATE tasks SET progress = %s WHERE id = %s AND status = 'running' AND worker = %s RETURNING id",
        (progress, task_id, NAME),
    ).fetchone()
    if updated is None:
        raise Cancelled


def solve(db, task_id, n, matrix):
    started = time.time()
    if matrix is None:
        a = np.random.default_rng(task_id).uniform(-10, 10, (n, n + 1))
    else:
        a = np.array(json.loads(matrix), dtype=float)
    original = a.copy()

    for k in range(n):
        p = k + np.argmax(np.abs(a[k:, k]))
        if abs(a[p, k]) < 1e-12:
            raise ValueError("Матриця вироджена, розв'язок не єдиний")
        a[[k, p]] = a[[p, k]]
        factors = a[k + 1:, k] / a[k, k]
        a[k + 1:, k:] -= np.outer(factors, a[k, k:])
        if k % 10 == 0:
            report(db, task_id, int(100 * (1 - ((n - k) / n) ** 3)), started)

    x = np.zeros(n)
    for i in range(n - 1, -1, -1):
        x[i] = (a[i, n] - a[i, i + 1:n] @ x[i + 1:]) / a[i, i]
    report(db, task_id, 100, started)

    residual = np.max(np.abs(original[:, :n] @ x - original[:, n]))
    return x, residual


def finish(db, task_id, status, result, error):
    db.execute(
        "UPDATE tasks SET status = %s, result = %s, error = %s, finished_at = now() "
        "WHERE id = %s AND status = 'running' AND worker = %s",
        (status, result, error, task_id, NAME),
    )


def run(db, task_id, n, matrix):
    try:
        x, residual = solve(db, task_id, n, matrix)
    except Cancelled:
        print("Задачу", task_id, "скасовано")
        return
    except TimeoutError:
        finish(db, task_id, "failed", None, f"Перевищено ліміт часу {TIME_LIMIT} с")
        return
    except ValueError as error:
        finish(db, task_id, "failed", None, str(error))
        return
    result = json.dumps({"residual": float(residual), "x": x.round(6).tolist()})
    finish(db, task_id, "done", result, None)
    print("Задачу", task_id, "розв'язано")


db = psycopg.connect(DATABASE_URL, autocommit=True)
db.execute("UPDATE tasks SET status = 'queued', progress = 0, worker = NULL WHERE status = 'running' AND worker = %s", (NAME,))
print("Воркер", NAME, "запущено")

while True:
    beat(db, None)
    requeue_lost_tasks(db)
    task = claim_task(db)
    if task is None:
        time.sleep(1)
        continue
    print("Воркер", NAME, "взяв задачу", task[0], "n =", task[1])
    run(db, task[0], task[1], task[2])
