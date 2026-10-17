"""Demo data sources, loaded once and validated: vendor registry and invoice DB (trusted),
inbox emails (untrusted), and scenarios. Tools return these records exactly as stored."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.config import FIXTURES_DIR
from app.models import GateMode, MandateConstraints, Outcome, Paise, ScenarioName


class FixtureError(ValueError):
    pass


class _Fixture(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Bank(_Fixture):
    account_name: str
    account_number: str
    ifsc: str
    bank_name: str


class Vendor(_Fixture):
    vendor_id: str = Field(pattern=r"^[a-z0-9_]{1,32}$")
    name: str
    gstin: str
    contact_email: str
    address: str
    bank: Bank


class Invoice(_Fixture):
    invoice_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,32}$")
    vendor_id: str
    description: str
    amount_due_paise: Paise
    currency: Literal["INR"]
    issued_at: str
    due_at: str
    notes: str = ""


class Email(_Fixture):
    email_id: str = Field(pattern=r"^[0-9]{1,10}$")
    from_: str = Field(alias="from")
    from_name: str
    to: str
    subject: str
    received_at: str
    body: str


class WebPage(_Fixture):
    page_id: str = Field(pattern=r"^[a-z0-9_]{1,64}$")
    url: str = Field(pattern=r"^https?://\S{1,200}$")
    title: str
    body: str


class Scenario(_Fixture):
    scenario_id: ScenarioName
    description: str
    instruction: str
    mandate: MandateConstraints
    inbox: list[str]
    expected: dict[GateMode, Outcome]
    expected_payee: str | None = None
    # What the attacker wants (attack scenarios set one): paid to this payee / this amount / this invoice.
    attacker_payee: str | None = None
    attacker_amount_paise: Paise | None = None
    attacker_invoice: str | None = None
    # Data poisoning for this scenario only.
    invoice_notes: dict[str, str] = Field(default_factory=dict)  # invoice_id → replacement notes text
    web_pages: list[str] = Field(default_factory=list)  # page_ids reachable with fetch_page
    scripted_payee_override: str | None = None  # the simulated agent "makes up" this payee


@dataclass(frozen=True)
class Fixtures:
    vendors: dict[str, dict[str, Any]]
    invoices: dict[str, dict[str, Any]]
    emails: dict[str, dict[str, Any]]
    scenarios: dict[str, Scenario]
    web: dict[str, dict[str, Any]]

    def inbox(self, scenario: str | None) -> list[str]:
        """Email ids in a session's inbox: the scenario's list, or every email."""
        if scenario is None:
            return sorted(self.emails, key=int)
        return list(self.scenarios[scenario].inbox)

    def pages(self, scenario: str | None) -> list[dict[str, Any]]:
        """Web pages reachable in a session: the scenario's list, or every page."""
        ids = self.web if scenario is None else self.scenarios[scenario].web_pages
        return [self.web[i] for i in ids]

    def invoice(self, invoice_id: str, scenario: str | None) -> dict[str, Any] | None:
        """An invoice as the invoice DB returns it in this session (scenario notes override applied)."""
        inv = self.invoices.get(invoice_id)
        if inv is None:
            return None
        inv = dict(inv)
        if scenario is not None and invoice_id in self.scenarios[scenario].invoice_notes:
            inv["notes"] = self.scenarios[scenario].invoice_notes[invoice_id]
        return inv


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise FixtureError(f"{path.name}: {e}") from e


def _check(model: type[BaseModel], data: Any, where: str) -> None:
    try:
        model.model_validate(data)
    except ValidationError as e:
        raise FixtureError(f"{where}: {e.errors()[0]['loc']} {e.errors()[0]['msg']}") from e


def load_fixtures(root: Path = FIXTURES_DIR) -> Fixtures:
    vendors = _read(root / "vendors.json")
    invoices = _read(root / "invoices.json")
    emails = {p.stem: _read(p) for p in sorted((root / "emails").glob("*.json"))}
    web = {p.stem: _read(p) for p in sorted((root / "web").glob("*.json"))}
    scenarios: dict[str, Scenario] = {}
    for key, page in web.items():
        _check(WebPage, page, f"web/{key}.json")
        if page["page_id"] != key:
            raise FixtureError(f"web/{key}.json: page_id {page['page_id']} != filename")

    for key, v in vendors.items():
        _check(Vendor, v, f"vendors.json[{key}]")
        if v["vendor_id"] != key:
            raise FixtureError(f"vendors.json: key {key} != vendor_id {v['vendor_id']}")
    for key, inv in invoices.items():
        _check(Invoice, inv, f"invoices.json[{key}]")
        if inv["invoice_id"] != key or inv["vendor_id"] not in vendors:
            raise FixtureError(f"invoices.json[{key}]: id mismatch or unknown vendor")
    for key, e in emails.items():
        _check(Email, e, f"emails/{key}.json")
        if e["email_id"] != key:
            raise FixtureError(f"emails/{key}.json: email_id {e['email_id']} != filename")
    for p in sorted((root / "scenarios").glob("*.json")):
        data = _read(p)
        _check(Scenario, data, f"scenarios/{p.name}")
        s = Scenario.model_validate(data)
        if s.scenario_id != p.stem:
            raise FixtureError(f"scenarios/{p.name}: scenario_id {s.scenario_id} != filename")
        if unknown := [i for i in s.inbox if i not in emails]:
            raise FixtureError(f"scenarios/{p.name}: unknown emails {unknown}")
        if s.mandate.invoice_id not in invoices or s.mandate.vendor_id not in vendors:
            raise FixtureError(f"scenarios/{p.name}: unknown invoice or vendor")
        if unknown := [i for i in s.web_pages if i not in web]:
            raise FixtureError(f"scenarios/{p.name}: unknown web pages {unknown}")
        if unknown := [i for i in s.invoice_notes if i not in invoices]:
            raise FixtureError(f"scenarios/{p.name}: invoice_notes for unknown invoices {unknown}")
        scenarios[s.scenario_id] = s
    return Fixtures(vendors=vendors, invoices=invoices, emails=emails, scenarios=scenarios, web=web)
