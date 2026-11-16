import hashlib
import json
import math
import os
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.environ["DATABASE_URL"]
SERVER_NAME = os.environ["SERVER_NAME"]
MAX_N = 3000
MAX_N_MANUAL = 20
MAX_ACTIVE_TASKS = 3
SECONDS_PER_N3 = 0.000000002


class ApiError(Exception):
    def __init__(self, status, message):
        self.status = status
        self.message = message


def hash_password(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000).hex()


def register(db, data):
    username = str(data.get("username", ""))
    password = str(data.get("password", ""))
    if len(username) < 3 or len(username) > 30 or not username.isalnum():
        raise ApiError(400, "Логін має містити від 3 до 30 літер або цифр")
    if len(password) < 6 or len(password) > 100:
        raise ApiError(400, "Пароль має містити від 6 до 100 символів")
    salt = secrets.token_hex(8)
    try:
        db.execute(
            "INSERT INTO users (username, password_hash) VALUES (%s, %s)",
            (username, salt + "$" + hash_password(password, salt)),
        )
    except psycopg.errors.UniqueViolation:
        raise ApiError(409, "Такий логін уже зайнятий")
    return login(db, data)


def login(db, data):
    username = str(data.get("username", ""))
    password = str(data.get("password", ""))
    user = db.execute("SELECT * FROM users WHERE username = %s", (username,)).fetchone()
    if user is None:
        raise ApiError(401, "Неправильний логін або пароль")
    salt, saved_hash = user["password_hash"].split("$")
    if hash_password(password, salt) != saved_hash:
        raise ApiError(401, "Неправильний логін або пароль")
    token = secrets.token_hex(16)
    db.execute("INSERT INTO sessions (token, user_id) VALUES (%s, %s)", (token, user["id"]))
    return {"token": token, "username": username, "is_admin": user["is_admin"]}


def get_token(headers):
    return headers.get("Authorization", "").replace("Bearer ", "")


def current_user(db, headers):
    user = db.execute(
        "SELECT users.id, users.is_admin FROM sessions JOIN users ON users.id = sessions.user_id "
        "WHERE sessions.token = %s AND sessions.created_at > now() - interval '12 hours'",
        (get_token(headers),),
    ).fetchone()
    if user is None:
        raise ApiError(401, "Потрібно увійти")
    return user


def logout(db, headers):
    db.execute("DELETE FROM sessions WHERE token = %s", (get_token(headers),))
    return {}


def count(db, sql, params=()):
    return db.execute(sql, params).fetchone()["count"]


def queue_info(db, task_id):
    position = count(db, "SELECT count(*) FROM tasks WHERE status = 'queued' AND id <= %s", (task_id,))
    running = count(db, "SELECT count(*) FROM tasks WHERE status = 'running'")
    workers = count(db, "SELECT count(*) FROM workers WHERE last_seen > now() - interval '15 seconds'")
    if position <= workers - running:
        return position, 0
    speed = db.execute(
        "SELECT avg(extract(epoch FROM finished_at - started_at) / (n::float * n * n)) AS speed "
        "FROM tasks WHERE status = 'done' AND n >= 500"
    ).fetchone()["speed"]
    if speed is None:
        speed = SECONDS_PER_N3
    work = db.execute(
        "SELECT coalesce(sum(n::float * n * n), 0) AS work FROM tasks "
        "WHERE status = 'running' OR (status = 'queued' AND id < %s)",
        (task_id,),
    ).fetchone()["work"]
    return position, round(float(speed) * work / max(workers, 1))


def check_matrix(matrix):
    if type(matrix) is not list or len(matrix) < 2 or len(matrix) > MAX_N_MANUAL:
        raise ApiError(400, f"Своя система має містити від 2 до {MAX_N_MANUAL} рівнянь")
    n = len(matrix)
    for row in matrix:
        if type(row) is not list or len(row) != n + 1:
            raise ApiError(400, f"У кожному рядку має бути {n + 1} чисел: {n} коефіцієнтів і вільний член")
        for value in row:
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ApiError(400, "Усі коефіцієнти мають бути числами")
    return n


def create_task(db, user_id, data):
    matrix = data.get("matrix")
    if matrix is None:
        n = data.get("n")
        if type(n) is not int or n < 2 or n > MAX_N:
            raise ApiError(400, f"Кількість невідомих має бути цілим числом від 2 до {MAX_N}")
    else:
        n = check_matrix(matrix)
        matrix = json.dumps(matrix)
    with db.transaction():
        db.execute("SELECT id FROM users WHERE id = %s FOR UPDATE", (user_id,))
        active = count(
            db, "SELECT count(*) FROM tasks WHERE user_id = %s AND status IN ('queued', 'running')", (user_id,)
        )
        if active >= MAX_ACTIVE_TASKS:
            raise ApiError(429, f"Можна мати не більше {MAX_ACTIVE_TASKS} активних задач")
        task = db.execute(
            "INSERT INTO tasks (user_id, n, matrix) VALUES (%s, %s, %s) RETURNING id", (user_id, n, matrix)
        ).fetchone()
    position, wait = queue_info(db, task["id"])
    return {"id": task["id"], "position": position, "wait": wait}


def list_tasks(db, user_id):
    tasks = db.execute(
        "SELECT id, n, status, progress, error, worker FROM tasks WHERE user_id = %s ORDER BY id DESC LIMIT 20",
        (user_id,),
    ).fetchall()
    for task in tasks:
        if task["status"] == "queued":
            task["position"], task["wait"] = queue_info(db, task["id"])
    return {"tasks": tasks}


def get_result(db, user_id, task_id):
    task = db.execute(
        "SELECT result FROM tasks WHERE id = %s AND user_id = %s AND status = 'done'", (task_id, user_id)
    ).fetchone()
    if task is None:
        raise ApiError(404, "Результат не знайдено")
    return json.loads(task["result"])


def cancel_task(db, user_id, task_id):
    task = db.execute(
        "UPDATE tasks SET status = 'cancelled', finished_at = now() "
        "WHERE id = %s AND user_id = %s AND status IN ('queued', 'running') RETURNING id",
        (task_id, user_id),
    ).fetchone()
    if task is None:
        raise ApiError(409, "Цю задачу вже не можна скасувати")
    return {"id": task_id}


def admin_panel(db, user):
    if not user["is_admin"]:
        raise ApiError(403, "Доступ лише для адміністратора")
    servers = db.execute(
        "SELECT name, requests, last_seen > now() - interval '15 seconds' AS alive FROM servers ORDER BY name"
    ).fetchall()
    workers = db.execute(
        "SELECT name, task_id, last_seen > now() - interval '15 seconds' AS alive FROM workers "
        "WHERE last_seen > now() - interval '1 minute' ORDER BY name"
    ).fetchall()
    counts = db.execute("SELECT status, count(*) FROM tasks GROUP BY status ORDER BY status").fetchall()
    tasks = db.execute(
        "SELECT tasks.id, users.username, tasks.n, tasks.status, tasks.progress, tasks.worker "
        "FROM tasks JOIN users ON users.id = tasks.user_id "
        "WHERE tasks.status IN ('queued', 'running') ORDER BY tasks.id"
    ).fetchall()
    return {"servers": servers, "workers": workers, "counts": counts, "tasks": tasks}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.process()

    def do_POST(self):
        self.process()

    def process(self):
        try:
            with psycopg.connect(DATABASE_URL, autocommit=True, row_factory=dict_row) as db:
                db.execute(
                    "INSERT INTO servers (name, requests) VALUES (%s, 1) ON CONFLICT (name) "
                    "DO UPDATE SET requests = servers.requests + 1, last_seen = now()",
                    (SERVER_NAME,),
                )
                data = self.route(db)
            self.reply(200, data)
        except ApiError as error:
            self.reply(error.status, {"error": error.message})
        except Exception as error:
            print("Помилка:", error)
            self.reply(500, {"error": "Внутрішня помилка сервера"})

    def route(self, db):
        method = self.command
        path = self.path
        parts = path.split("/")
        if method == "POST" and path == "/api/register":
            return register(db, self.read_json())
        if method == "POST" and path == "/api/login":
            return login(db, self.read_json())
        user = current_user(db, self.headers)
        if method == "POST" and path == "/api/logout":
            return logout(db, self.headers)
        if method == "GET" and path == "/api/tasks":
            return list_tasks(db, user["id"])
        if method == "POST" and path == "/api/tasks":
            return create_task(db, user["id"], self.read_json())
        if method == "GET" and path == "/api/admin":
            return admin_panel(db, user)
        if len(parts) == 5 and parts[2] == "tasks" and parts[3].isdigit():
            if method == "GET" and parts[4] == "result":
                return get_result(db, user["id"], int(parts[3]))
            if method == "POST" and parts[4] == "cancel":
                return cancel_task(db, user["id"], int(parts[3]))
        raise ApiError(404, "Не знайдено")

    def read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        if length > 10000:
            raise ApiError(413, "Запит завеликий")
        try:
            data = json.loads(self.rfile.read(length) or "{}")
        except ValueError:
            raise ApiError(400, "Некоректний JSON")
        if type(data) is not dict:
            raise ApiError(400, "Некоректний JSON")
        return data

    def reply(self, status, data):
        data["server"] = SERVER_NAME
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


print("API-сервер", SERVER_NAME, "запущено на порту 8000")
ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
