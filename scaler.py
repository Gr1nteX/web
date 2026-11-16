import os
import signal
import sys
import time

import docker
import psycopg

DATABASE_URL = os.environ["DATABASE_URL"]
BASE_WORKERS = 2
MAX_WORKERS = 4

client = docker.from_env()
db = psycopg.connect(DATABASE_URL, autocommit=True)


def extra_workers():
    return client.containers.list(all=True, filters={"label": "autoscaled=yes"})


def start_worker():
    names = [container.name for container in extra_workers()]
    number = BASE_WORKERS + 1
    while "worker" + str(number) in names:
        number += 1
    name = "worker" + str(number)
    base = client.containers.list(filters={"label": "com.docker.compose.service=worker1"})[0]
    network = list(base.attrs["NetworkSettings"]["Networks"])[0]
    client.containers.run(
        base.image.id,
        "python worker.py",
        name=name,
        hostname=name,
        environment=base.attrs["Config"]["Env"],
        network=network,
        labels={"autoscaled": "yes"},
        mem_limit="512m",
        nano_cpus=1000000000,
        detach=True,
    )
    print("Запущено додатковий воркер", name)


def stop_worker(container):
    container.remove(force=True)
    db.execute("DELETE FROM workers WHERE name = %s", (container.name,))
    print("Зупинено додатковий воркер", container.name)


def shutdown(signum, frame):
    for container in extra_workers():
        stop_worker(container)
    sys.exit(0)


signal.signal(signal.SIGTERM, shutdown)
for old in extra_workers():
    stop_worker(old)
print("Scaler запущено, максимум воркерів:", MAX_WORKERS)

while True:
    time.sleep(5)
    queued = db.execute("SELECT count(*) FROM tasks WHERE status = 'queued'").fetchone()[0]
    extra = extra_workers()
    if queued > 0 and BASE_WORKERS + len(extra) < MAX_WORKERS:
        start_worker()
    if queued == 0:
        for container in extra:
            worker = db.execute("SELECT task_id FROM workers WHERE name = %s", (container.name,)).fetchone()
            if worker is None or worker[0] is None:
                stop_worker(container)
