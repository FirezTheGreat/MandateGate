"""GET /tools, POST /tools/{name}: brokered tool calls (see broker.py)."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app import broker
from app.clock import utc_now
from app.deps import ConnDep, FixturesDep, SettingsDep
from app.errors import api_error
from app.models import ToolCallRequest, ToolCallResult, ToolInfo

router = APIRouter(tags=["tools"])


@router.get("/tools", response_model=list[ToolInfo])
def list_tools() -> list[ToolInfo]:
    return broker.tool_infos()


@router.post("/tools/{name}", response_model=ToolCallResult)
def call_tool(name: str, req: ToolCallRequest, settings: SettingsDep, fixtures: FixturesDep, conn: ConnDep) -> ToolCallResult | JSONResponse:
    try:
        return broker.execute(conn, settings=settings, fixtures=fixtures, name=name, req=req, now=utc_now())
    except broker.BrokerError as e:
        return api_error(e.status, e.error, e.detail)
