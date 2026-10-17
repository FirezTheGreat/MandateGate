"""GET /attacks/results: the attack suite's measured results for the Attacks page.

Serves attacks/results.json as written by `make attacks` (attacks/run_suite.py). Nothing here is
computed or invented: no file → 404, a file that does not match the contract → 503.
"""

import os
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.config import BACKEND_DIR
from app.errors import api_error
from app.models import AttackResults

router = APIRouter(tags=["attacks"])

DEFAULT_RESULTS = BACKEND_DIR / "attacks" / "results.json"


def results_path() -> Path:
    return Path(os.environ.get("ATTACK_RESULTS_PATH", DEFAULT_RESULTS))


@router.get("/attacks/results", response_model=AttackResults)
def attack_results() -> AttackResults | JSONResponse:
    path = results_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return api_error(404, "no_results", "no attack results yet; run `make attacks`")
    try:
        return AttackResults.model_validate_json(raw)
    except ValidationError as e:
        return api_error(503, "bad_results", f"{path.name} does not match the contract ({e.error_count()} errors); re-run `make attacks`")
