"""GET /tools, POST /tools/{name}.

STUB: returns fixture data with no token check and no provenance recording yet
(Phase 2 broker).
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app import stub_data
from app.errors import api_error
from app.models import ToolCallRequest, ToolCallResult, ToolInfo

router = APIRouter(tags=["tools"])

TOOL_NAMES = {t.name for t in stub_data.TOOLS}


@router.get("/tools", response_model=list[ToolInfo])
def list_tools() -> list[ToolInfo]:
    return stub_data.TOOLS


@router.post("/tools/{name}", response_model=ToolCallResult)
def call_tool(name: str, req: ToolCallRequest) -> ToolCallResult | JSONResponse:
    if name not in TOOL_NAMES:
        return api_error(404, "unknown_tool", f"no brokered tool named {name!r}")
    result = stub_data.tool_result(name, req.args)
    if result is None:
        return api_error(404, "not_found", f"{name}: no record for the given args")
    return ToolCallResult(
        tool_call_id="tcl_example",
        session_id=req.session_id,
        tool=name,  # type: ignore[arg-type]
        result=result,
        values_recorded=0,
    )
