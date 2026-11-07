from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=6, max_length=64)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    is_admin: bool


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    is_admin: bool


class LimitsOut(BaseModel):
    max_n: int
    max_n_manual: int
    time_limit_seconds: int
    max_active_tasks: int
    max_history: int


class TaskCreate(BaseModel):
    mode: Literal["random", "manual"]
    n: int | None = None
    seed: int | None = None
    a: list[list[float]] | None = None
    b: list[float] | None = None


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    n: int
    mode: str
    status: str
    progress: float
    stage: str
    error: str | None
    server: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class TaskDetail(TaskOut):
    seed: int | None
    result: dict | None
