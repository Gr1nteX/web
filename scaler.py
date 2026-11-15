import os
import signal
import sys
import time

import docker
import psycopg

DATABASE_URL = os.environ["DATABASE_URL"]
MAX_WORKERS = 4

client = docker.from_env()
db = psycopg.connect(DATABASE_URL, autocommit=True)


def live_workers():
    return db.execute(
        "SELECT count(*) FROM workers WHERE last_seen > now() - interval '15 seconds'"
    ).fetchone()[0]


def extra_workers():
    return client.containers.list(all=True, filters={"label": "autoscaled=yes"})


def start_worker():
    base = client.containers.list(filters={"label": "com.docker.compose.service=worker"})[0]
    network = list(base.attrs["NetworkSettings"]["Networks"])[0]
    container = client.containers.run(
        base.image.id,
        "python worker.py",
        environment=base.attrs["Config"]["Env"],
        network=network,
        labels={"autoscaled": "yes"},
        mem_limit="512m",
        nano_cpus=1000000000,
        detach=True,
    )
    print("Запущено додатковий воркер", container.short_id)


def stop_worker(container):
    container.remove(force=True)
    db.execute("DELETE FROM workers WHERE name = %s", (container.attrs["Config"]["Hostname"],))
    print("Зупинено додатковий воркер", container.short_id)


def shutdown(signum, frame):
    for container in extra_workers():
        stop_worker(container)
    sys.exit(0)


signal.signal(signal.SIGTERM, shutdown)
print("Scaler запущено, максимум воркерів:", MAX_WORKERS)

while True:
    time.sleep(5)
    queued = db.execute("SELECT count(*) FROM tasks WHERE status = 'queued'").fetchone()[0]
    extra = extra_workers()
    if queued > 0 and live_workers() < MAX_WORKERS:
        start_worker()
    if queued == 0:
        for container in extra:
            worker = db.execute(
                "SELECT task_id FROM workers WHERE name = %s", (container.attrs["Config"]["Hostname"],)
            ).fetchone()
            if worker is None or worker[0] is None:
                stop_worker(container)
