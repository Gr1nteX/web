import io
import logging
import signal
import socket
import tarfile
import threading
import time

import docker
from sqlalchemy import func, select

from . import config
from .db import SessionLocal, init_db
from .estimate import queue_estimates
from .models import RUNNING, Server, Task, server_alive

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s scaler: %(message)s")
log = logging.getLogger("scaler")

PROJECT_LABEL = "com.docker.compose.project"
SERVICE_LABEL = "com.docker.compose.service"
AUTO_LABEL = "linsolve.autoscaled"
NGINX_DYNAMIC_DIR = "/etc/nginx/dynamic"


class Scaler:
    def __init__(self):
        self.client = docker.from_env()
        self.project = self.client.containers.get(socket.gethostname()).labels[PROJECT_LABEL]
        template = self.service_containers(config.TEMPLATE_SERVICE, all=True)[0]
        self.image = template.image.id
        self.network = next(iter(template.attrs["NetworkSettings"]["Networks"]))
        self.env = [e for e in template.attrs["Config"]["Env"] if not e.startswith(("SERVER_NAME=", "AUTO_SCALED="))]
        self.routes: dict[str, str] = {}
        self.synced_nginx: str | None = None
        self.last_start = 0.0
        self.idle_since: dict[str, float] = {}
        self.stop_event = threading.Event()

    def service_containers(self, service: str, all: bool = False) -> list:
        return self.client.containers.list(
            all=all, filters={"label": [f"{PROJECT_LABEL}={self.project}", f"{SERVICE_LABEL}={service}"]}
        )

    def auto_containers(self) -> list:
        return self.client.containers.list(
            all=True, filters={"label": [f"{PROJECT_LABEL}={self.project}", AUTO_LABEL]}
        )

    def update_nginx(self) -> None:
        nginx = next(iter(self.service_containers(config.NGINX_SERVICE)), None)
        if nginx is None:
            return
        data = "".join(f"server {ip}:8000 max_fails=1 fail_timeout=10s;\n" for ip in self.routes.values()).encode()
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w") as tar:
            info = tarfile.TarInfo("auto.conf")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        try:
            nginx.put_archive(NGINX_DYNAMIC_DIR, archive.getvalue())
            reloaded = nginx.exec_run(["nginx", "-s", "reload"]).exit_code == 0
        except docker.errors.APIError:
            reloaded = False
        if reloaded:
            self.synced_nginx = nginx.id
            log.info("Балансувальник: базові сервери + %s", ", ".join(self.routes) or "без додаткових")
        else:
            log.warning("Не вдалося оновити конфігурацію nginx")

    def start_server(self, name: str) -> None:
        self.client.containers.run(
            self.image,
            name=f"{self.project}-{name}",
            hostname=name,
            environment=self.env + [f"SERVER_NAME={name}", "AUTO_SCALED=1"],
            labels={PROJECT_LABEL: self.project, SERVICE_LABEL: name, AUTO_LABEL: name},
            network=self.network,
            detach=True,
        )
        self.last_start = time.monotonic()
        log.info("Запущено новий сервер %s", name)

    def stop_server(self, container) -> None:
        name = container.labels[AUTO_LABEL]
        if self.routes.pop(name, None):
            self.update_nginx()
            time.sleep(2)
        container.stop(timeout=20)
        container.remove()
        self.idle_since.pop(name, None)
        log.info("Зупинено сервер %s", name)

    def sync_routes(self, autos: list, alive: set[str]) -> None:
        running = {c.labels[AUTO_LABEL]: c for c in autos}
        changed = False
        for name in list(self.routes):
            if name not in running:
                del self.routes[name]
                changed = True
        for name, container in running.items():
            if name not in self.routes and name in alive:
                self.routes[name] = container.attrs["NetworkSettings"]["Networks"][self.network]["IPAddress"]
                changed = True
        nginx = next(iter(self.service_containers(config.NGINX_SERVICE)), None)
        if changed or (nginx is not None and nginx.id != self.synced_nginx):
            self.update_nginx()

    def step(self) -> None:
        with SessionLocal() as db:
            waiting = sum(1 for _, wait in queue_estimates(db).values() if wait != 0)
            alive = set(db.scalars(select(Server.name).where(server_alive())))
            busy = dict(
                db.execute(select(Task.server, func.count()).where(Task.status == RUNNING).group_by(Task.server)).all()
            )

        autos = []
        for container in self.auto_containers():
            if container.status in ("exited", "dead"):
                container.remove()
            else:
                autos.append(container)
        self.sync_routes(autos, alive)
        names = alive | {c.labels[AUTO_LABEL] for c in autos}

        cooled = time.monotonic() - self.last_start > config.SCALE_COOLDOWN_SECONDS
        if waiting and len(names) < config.MAX_SERVERS and cooled:
            number = next(i for i in range(1, config.MAX_SERVERS + 1) if f"auto{i}" not in names)
            self.start_server(f"auto{number}")
            return

        now = time.monotonic()
        for container in autos:
            name = container.labels[AUTO_LABEL]
            if waiting or busy.get(name) or name not in alive:
                self.idle_since.pop(name, None)
                continue
            if now - self.idle_since.setdefault(name, now) >= config.IDLE_SECONDS_BEFORE_STOP:
                self.stop_server(container)

    def run(self) -> None:
        for container in self.auto_containers():
            container.remove(force=True)
        self.update_nginx()
        log.info("Автомасштабування: максимум %d серверів", config.MAX_SERVERS)
        while not self.stop_event.wait(config.SCALE_INTERVAL_SECONDS):
            try:
                self.step()
            except Exception:
                log.exception("Помилка автомасштабування")
        for container in self.auto_containers():
            self.stop_server(container)


def main() -> None:
    init_db()
    scaler = Scaler()
    signal.signal(signal.SIGTERM, lambda *_: scaler.stop_event.set())
    signal.signal(signal.SIGINT, lambda *_: scaler.stop_event.set())
    scaler.run()


if __name__ == "__main__":
    main()
