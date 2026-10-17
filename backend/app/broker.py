"""The broker: the only way agents reach data. Every call is authorised, executed, and its
output recorded with provenance assigned HERE, from this registry (CLAUDE.md §2.2).

    list_inbox / read_email → email, untrusted
    fetch_page              → web, untrusted
    get_invoice             → invoice_db, trusted   (except its free-text `notes`: untrusted, ref invoice:<id>#notes)
    get_vendor              → vendor_registry, trusted

Call flow: session → token chain → session/mandate binding → mandate valid → args → caveats
(tool=<name>) → run → record values + events → result. Denials are recorded too.
"""

import copy
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app import db, events
from app.clock import to_iso
from app.config import Settings
from app.crypto import new_id
from app.delegation import EvalContext, evaluate, verify_chain
from app.fixtures import Fixtures
from app.mandate import verify_mandate
from app.models import SourceType, ToolCallRequest, ToolCallResult, ToolInfo, ToolName, ValueRecord
from app.provenance import Fragment, is_critical, observe


class BrokerError(Exception):
    def __init__(self, status: int, error: str, detail: str) -> None:
        super().__init__(f"{status} {error}: {detail}")
        self.status, self.error, self.detail = status, error, detail


# --------------------------------------------------------------------------- argument schemas


class _Args(BaseModel):
    # LLMs sometimes send ids as numbers; accept them as strings. Unknown keys are rejected.
    model_config = ConfigDict(extra="forbid", coerce_numbers_to_str=True)


class NoArgs(_Args):
    pass


class EmailArgs(_Args):
    email_id: str = Field(pattern=r"^[0-9]{1,10}$")


class InvoiceArgs(_Args):
    invoice_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,32}$")


class VendorArgs(_Args):
    vendor_id: str = Field(pattern=r"^[a-z0-9_]{1,32}$")


# --------------------------------------------------------------------------- handlers (pure)

class UrlArgs(_Args):
    url: str = Field(pattern=r"^https?://\S{1,200}$")


ToolOutput = tuple[Any, list[Fragment]]
Handler = Callable[[Fixtures, str | None, Any], ToolOutput | None]  # (fixtures, session scenario, args); None → not found

SUMMARY_FIELDS = ("email_id", "from", "from_name", "subject", "received_at")


def _list_inbox(fx: Fixtures, scenario: str | None, _: NoArgs) -> ToolOutput:
    items = [{k: fx.emails[i][k] for k in SUMMARY_FIELDS} for i in fx.inbox(scenario)]
    return items, [Fragment(item, f"[{n}]", "email", f"email:{item['email_id']}", "untrusted") for n, item in enumerate(items)]


def _read_email(fx: Fixtures, scenario: str | None, a: EmailArgs) -> ToolOutput | None:
    if a.email_id not in fx.inbox(scenario):
        return None
    email = copy.deepcopy(fx.emails[a.email_id])
    return email, [Fragment(email, "", "email", f"email:{email['email_id']}", "untrusted")]


def _get_invoice(fx: Fixtures, scenario: str | None, a: InvoiceArgs) -> ToolOutput | None:
    inv = fx.invoice(a.invoice_id, scenario)  # scenario may have poisoned the free-text notes
    if inv is None:
        return None
    inv = copy.deepcopy(inv)
    ref = f"invoice:{inv['invoice_id']}"
    core = {k: v for k, v in inv.items() if k != "notes"}
    fragments = [Fragment(core, "", "invoice_db", ref, "trusted")]
    if inv.get("notes"):
        # Free text a vendor can influence: never a trusted source for payees or amounts.
        fragments.append(Fragment(inv["notes"], "notes", "invoice_db", ref + "#notes", "untrusted"))
    return inv, fragments


def _get_vendor(fx: Fixtures, _: str | None, a: VendorArgs) -> ToolOutput | None:
    vendor = fx.vendors.get(a.vendor_id)
    if vendor is None:
        return None
    vendor = copy.deepcopy(vendor)
    return vendor, [Fragment(vendor, "", "vendor_registry", f"vendor:{vendor['vendor_id']}", "trusted")]


def _fetch_page(fx: Fixtures, scenario: str | None, a: UrlArgs) -> ToolOutput | None:
    page = next((p for p in fx.pages(scenario) if p["url"] == a.url), None)
    if page is None:
        return None
    page = copy.deepcopy(page)
    return page, [Fragment(page, "", "web", f"web:{page['page_id']}", "untrusted")]


@dataclass(frozen=True)
class ToolSpec:
    name: ToolName
    description: str
    args_model: type[_Args]
    source_type: SourceType
    handler: Handler


REGISTRY: dict[str, ToolSpec] = {
    t.name: t
    for t in (
        ToolSpec("list_inbox", "List emails in the accounts-payable inbox (sender, subject, date).", NoArgs, "email", _list_inbox),
        ToolSpec("read_email", "Read one email by id.", EmailArgs, "email", _read_email),
        ToolSpec("get_invoice", "Fetch an invoice from the invoice database.", InvoiceArgs, "invoice_db", _get_invoice),
        ToolSpec("get_vendor", "Fetch a vendor record, including registered bank details, from the vendor registry.", VendorArgs, "vendor_registry", _get_vendor),
        ToolSpec("fetch_page", "Fetch a web page (e.g. a vendor portal) by URL.", UrlArgs, "web", _fetch_page),
    )
}


def tool_infos() -> list[ToolInfo]:
    return [
        ToolInfo(name=s.name, description=s.description, args={k: "string" for k in s.args_model.model_fields}, source_type=s.source_type)
        for s in REGISTRY.values()
    ]


def parse_args(spec: ToolSpec, args: dict[str, Any]) -> tuple[_Args | None, list[str], str]:
    """(parsed, unexpected_keys, error_detail). parsed is None when invalid."""
    unexpected = sorted(k for k in args if k not in spec.args_model.model_fields)
    try:
        return spec.args_model.model_validate(args), unexpected, ""
    except ValidationError as e:
        detail = "; ".join(f"{'.'.join(str(p) for p in err['loc']) or 'args'}: {err['msg']}" for err in e.errors())
        return None, unexpected, detail


def invoice_scope(parsed: _Args) -> str | None:
    """The invoice this call touches, for `invoice_id = X` caveats (None: no invoice)."""
    return parsed.invoice_id if isinstance(parsed, InvoiceArgs) else None


# --------------------------------------------------------------------------- execute (I/O)


def execute(
    conn: sqlite3.Connection, *, settings: Settings, fixtures: Fixtures, name: str, req: ToolCallRequest, now: datetime
) -> ToolCallResult:
    ts = to_iso(now)
    session = db.get_session(conn, req.session_id)
    if session is None:
        raise BrokerError(404, "unknown_session", f"no session {req.session_id}; create one with POST /sessions")
    tool_call_id = new_id("tcl")

    def deny(status: int, error: str, detail: str, *, args: dict[str, Any], record_status: str = "denied") -> BrokerError:
        with db.transaction(conn):
            db.insert_tool_call(
                conn, tool_call_id=tool_call_id, session_id=session.session_id, agent_id=req.agent_id, tool=name,
                args=args, result=None, status=record_status, error=error, ts=ts,
            )
            events.emit(conn, "tool_call", session.session_id, {
                "tool_call_id": tool_call_id, "agent_id": req.agent_id, "tool": name, "args": args,
                "status": record_status, "values_recorded": 0, "error": error,
            }, ts)
        return BrokerError(status, error, detail)

    spec = REGISTRY.get(name)
    if spec is None:
        raise deny(404, "unknown_tool", f"no brokered tool named {name!r}", args={})

    chain = verify_chain(req.token, root_key=settings.root_key)
    if not chain.ok:
        raise deny(401, "invalid_token", chain.detail, args={})
    if req.token.mandate_id != session.mandate_id:
        raise deny(403, "session_mismatch", f"token is for {req.token.mandate_id}; session belongs to {session.mandate_id}", args={})
    mandate = db.get_mandate(conn, session.mandate_id)
    if mandate is None:
        raise deny(403, "mandate_invalid", "mandate not found", args={})
    mandate_ok = verify_mandate(mandate, key=settings.mandate_key, now=now)
    if not mandate_ok.ok:
        raise deny(403, "mandate_invalid", mandate_ok.detail, args={})

    parsed, unexpected, problem = parse_args(spec, req.args)
    if unexpected:
        # e.g. an agent passing {"trust": "trusted"}: never honoured, always logged
        with db.transaction(conn):
            events.emit(conn, "suspicious_input", session.session_id, {"path": f"/tools/{name}", "fields": unexpected[:20]}, ts)
    if parsed is None:
        raise deny(400, "invalid_args", problem, args={k: "…" for k in list(req.args)[:20]})
    args = parsed.model_dump()

    held = evaluate(req.token.caveats, EvalContext(agent=req.agent_id, tool=name, invoice_id=invoice_scope(parsed), now=now))
    if not held.ok:
        raise deny(403, "tool_denied", held.detail, args=args)

    output = spec.handler(fixtures, session.scenario, parsed)
    if output is None:
        raise deny(404, "not_found", f"{name}: no record for {args}", args=args, record_status="error")
    result, fragments = output

    observations = observe(fragments)
    records = [
        ValueRecord(
            value_id=new_id("val"), session_id=session.session_id, raw=o.raw, normalized=o.normalized, field_hint=o.field_hint,
            source_type=o.source_type, source_ref=o.source_ref, trust=o.trust, tool_call_id=tool_call_id,
            agent_id=req.agent_id, ts=ts,
        )
        for o in observations
    ]
    with db.transaction(conn):
        db.insert_tool_call(
            conn, tool_call_id=tool_call_id, session_id=session.session_id, agent_id=req.agent_id, tool=name,
            args=args, result=result, status="ok", error=None, ts=ts,
        )
        db.insert_values(conn, records)
        events.emit(conn, "tool_call", session.session_id, {
            "tool_call_id": tool_call_id, "agent_id": req.agent_id, "tool": name, "args": args,
            "status": "ok", "values_recorded": len(records),
        }, ts)
        shown: set[tuple[str, str]] = set()
        for o, r in zip(observations, records, strict=True):
            if is_critical(o) and (o.normalized, o.source_ref) not in shown:
                shown.add((o.normalized, o.source_ref))
                events.emit(conn, "value_recorded", session.session_id, {
                    "value_id": r.value_id, "raw": r.raw, "field_hint": r.field_hint, "source_ref": r.source_ref,
                    "trust": r.trust, "tool_call_id": tool_call_id,
                }, ts)
    return ToolCallResult(tool_call_id=tool_call_id, session_id=session.session_id, tool=spec.name, result=result, values_recorded=len(records))
