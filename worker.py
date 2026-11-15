import json
import os
import random
import socket
import time

import psycopg

DATABASE_URL = os.environ["DATABASE_URL"]
NAME = socket.gethostname()
TIME_LIMIT = 30


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
            "SELECT id, n FROM tasks WHERE status = 'queued' ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED"
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


def solve(db, task_id, n):
    started = time.time()
    generator = random.Random(task_id)
    a = [[generator.uniform(-10, 10) for j in range(n + 1)] for i in range(n)]
    original = [row[:] for row in a]

    for k in range(n):
        p = k
        for i in range(k + 1, n):
            if abs(a[i][k]) > abs(a[p][k]):
                p = i
        if abs(a[p][k]) < 1e-12:
            raise ValueError("Матриця вироджена, розв'язок не єдиний")
        a[k], a[p] = a[p], a[k]
        for i in range(k + 1, n):
            factor = a[i][k] / a[k][k]
            for j in range(k, n + 1):
                a[i][j] -= factor * a[k][j]
        report(db, task_id, (k + 1) * 100 // n, started)

    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        total = 0.0
        for j in range(i + 1, n):
            total += a[i][j] * x[j]
        x[i] = (a[i][n] - total) / a[i][i]

    residual = 0.0
    for row in original:
        total = 0.0
        for j in range(n):
            total += row[j] * x[j]
        residual = max(residual, abs(total - row[n]))
    return x, residual


def finish(db, task_id, status, result, error):
    db.execute(
        "UPDATE tasks SET status = %s, result = %s, error = %s, finished_at = now() "
        "WHERE id = %s AND status = 'running' AND worker = %s",
        (status, result, error, task_id, NAME),
    )


def run(db, task_id, n):
    try:
        x, residual = solve(db, task_id, n)
    except Cancelled:
        print("Задачу", task_id, "скасовано")
        return
    except TimeoutError:
        finish(db, task_id, "failed", None, f"Перевищено ліміт часу {TIME_LIMIT} с")
        return
    except ValueError as error:
        finish(db, task_id, "failed", None, str(error))
        return
    result = json.dumps({"residual": residual, "x": [round(value, 6) for value in x]})
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
    run(db, task[0], task[1])
