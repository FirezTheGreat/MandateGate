"""FastAPI dependencies for the gate: validated settings, fixtures, mode, and a per-request DB connection."""

import sqlite3
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request

from app import db
from app.config import Settings
from app.fixtures import Fixtures
from app.models import GateMode


def get_settings(request: Request) -> Settings:
    return request.app.state.settings  # loaded and validated once, at startup


def get_fixtures(request: Request) -> Fixtures:
    return request.app.state.fixtures  # reloaded by POST /admin/reset


def get_mode(request: Request) -> GateMode:
    return request.app.state.mode  # set by POST /admin/mode; starts from GATE_MODE


def get_conn(settings: Annotated[Settings, Depends(get_settings)]) -> Iterator[sqlite3.Connection]:
    conn = db.connect(settings.gate_db_path)
    try:
        yield conn
    finally:
        conn.close()


SettingsDep = Annotated[Settings, Depends(get_settings)]
FixturesDep = Annotated[Fixtures, Depends(get_fixtures)]
ModeDep = Annotated[GateMode, Depends(get_mode)]
ConnDep = Annotated[sqlite3.Connection, Depends(get_conn)]
