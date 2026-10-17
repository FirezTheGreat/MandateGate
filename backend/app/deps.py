"""FastAPI dependencies for the gate: validated settings and a per-request DB connection."""

import sqlite3
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request

from app import db
from app.config import Settings


def get_settings(request: Request) -> Settings:
    return request.app.state.settings  # loaded and validated once, at startup


def get_conn(settings: Annotated[Settings, Depends(get_settings)]) -> Iterator[sqlite3.Connection]:
    conn = db.connect(settings.gate_db_path)
    try:
        yield conn
    finally:
        conn.close()


SettingsDep = Annotated[Settings, Depends(get_settings)]
ConnDep = Annotated[sqlite3.Connection, Depends(get_conn)]
