from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import config
from ..auth import require_admin
from ..db import get_db
from ..estimate import queue_estimates
from ..models import ACTIVE_STATUSES, RUNNING, Server, Task, User, server_alive

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/overview")
def overview(db: Session = Depends(get_db)):
    servers = db.scalars(select(Server).where(server_alive()).order_by(Server.auto, Server.name)).all()
    busy = dict(db.execute(select(Task.server, func.count()).where(Task.status == RUNNING).group_by(Task.server)).all())
    active = db.execute(
        select(Task, User.username).join(User).where(Task.status.in_(ACTIVE_STATUSES)).order_by(Task.id)
    ).all()
    estimates = queue_estimates(db)
    counts = dict(db.execute(select(Task.status, func.count()).group_by(Task.status)).all())

    return {
        "max_servers": config.MAX_SERVERS,
        "users": db.scalar(select(func.count()).select_from(User)),
        "counts": counts,
        "servers": [
            {
                "name": s.name,
                "auto": s.auto,
                "slots": s.slots,
                "busy": busy.get(s.name, 0),
                "cpu": s.cpu,
                "memory_mb": s.memory_mb,
                "started_at": s.started_at,
                "last_seen": s.last_seen,
            }
            for s in servers
        ],
        "tasks": [
            {
                "id": t.id,
                "user": username,
                "n": t.n,
                "status": t.status,
                "server": t.server,
                "progress": t.progress,
                "stage": t.stage,
                "created_at": t.created_at,
                "started_at": t.started_at,
                "queue_position": estimates.get(t.id, (None, None))[0],
                "wait_seconds": estimates.get(t.id, (None, None))[1],
            }
            for t, username in active
        ],
    }
