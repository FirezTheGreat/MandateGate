"""Structured `{error, detail}` responses for both services. Never leak stack traces."""

import logging
from collections.abc import Callable

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.models import ErrorResponse

log = logging.getLogger("mandategate.errors")

InvalidInputHook = Callable[[Request, RequestValidationError], None]


def api_error(status_code: int, error: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=ErrorResponse(error=error, detail=detail).model_dump())


def install_error_handlers(app: FastAPI, on_invalid_input: InvalidInputHook | None = None) -> None:
    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        if on_invalid_input is not None:
            try:
                on_invalid_input(request, exc)
            except Exception:  # logging must never change the response
                log.exception("invalid-input hook failed")
        # Report field locations and messages only; never echo the submitted values back.
        parts = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
        return api_error(422, "invalid_request", "; ".join(parts))

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return api_error(exc.status_code, "http_error", str(exc.detail))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, __: Exception) -> JSONResponse:
        return api_error(500, "internal_error", "internal error")
