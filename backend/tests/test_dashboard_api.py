"""Backend support for the dashboard: run-scenario, session/mandate lookups, live-graph event data."""

import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app as gate_app
from app.runner import Runner, RunnerError
from tests.gatekit import GateKit

# --------------------------------------------------------------------------- the runner (real subprocess, no gate needed)


def fake_command(script: str):  # type: ignore[no-untyped-def]
    return lambda scenario, mode, agent: [sys.executable, "-c", script]


def test_runner_returns_the_session_as_soon_as_the_run_creates_it(tmp_path: Path) -> None:
    script = "import time; print('[human] approved', flush=True); print('[session] ses_test123', flush=True); print('later', flush=True); time.sleep(1.5)"
    runner = Runner(command=fake_command(script), log_dir=tmp_path)
    t0 = time.monotonic()
    assert runner.start("hero_attack", "gated", "scripted") == "ses_test123"
    assert time.monotonic() - t0 < 1.5  # did not wait for the run to finish
    assert runner.busy()
    with pytest.raises(RunnerError) as e:
        runner.start("happy", "gated", "scripted")
    assert e.value.error == "run_in_progress"
    runner.process.wait(timeout=10)  # type: ignore[union-attr]
    assert not runner.busy()
    time.sleep(0.2)  # let the pump flush the run's log
    assert (tmp_path / "ses_test123.log").read_text(encoding="utf-8").strip() == "later"


def test_runner_reports_a_run_that_dies_before_starting(tmp_path: Path) -> None:
    runner = Runner(command=fake_command("print('error: gate unreachable'); raise SystemExit(1)"), log_dir=tmp_path)
    with pytest.raises(RunnerError) as e:
        runner.start("hero_attack", "gated", "scripted")
    assert e.value.error == "run_failed" and "gate unreachable" in e.value.detail


def _finished(script: str, tmp_path: Path) -> list[tuple[str, int, str | None]]:
    reports: list[tuple[str, int, str | None]] = []
    runner = Runner(command=fake_command(script), log_dir=tmp_path, on_finish=lambda *a: reports.append(a))
    runner.start("happy", "gated", "llm")
    runner.process.wait(timeout=10)  # type: ignore[union-attr]
    for _ in range(50):  # the pump reports after the process exits
        if reports:
            break
        time.sleep(0.05)
    return reports


def test_runner_reports_how_a_run_ended(tmp_path: Path) -> None:
    """Without this the dashboard spins forever when the AI cannot run (no key, API down): Phase 7 fresh-clone finding."""
    script = "print('[session] ses_x', flush=True); print('paid       nothing'); print('error      agent could not run: no credentials'); raise SystemExit(1)"
    assert _finished(script, tmp_path) == [("ses_x", 1, "agent could not run: no credentials")]
    assert _finished("print('[session] ses_y', flush=True); print('expected   ALLOW: yes')", tmp_path) == [("ses_y", 0, None)]


def test_run_finished_reaches_the_event_feed(gate: TestClient) -> None:
    from app.runner import report_to

    kit = GateKit(gate)
    m, _ = kit.mandate()
    sid = kit.session(m["mandate_id"], "happy")
    report_to(gate_app.state.settings.gate_db_path)(sid, 1, "agent could not run: no credentials")
    finished = [e for e in kit.events(sid) if e["type"] == "run_finished"]
    assert [e["data"] for e in finished] == [{"exit_code": 1, "ok": False, "detail": "agent could not run: no credentials"}]


def test_runner_times_out_when_no_session_appears(tmp_path: Path) -> None:
    runner = Runner(command=fake_command("import time; time.sleep(5)"), start_timeout_s=0.5, log_dir=tmp_path)
    with pytest.raises(RunnerError) as e:
        runner.start("hero_attack", "gated", "scripted")
    assert e.value.error == "run_failed"


# --------------------------------------------------------------------------- POST /admin/run-scenario


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def start(self, scenario: str, mode: str, agent: str) -> str:
        self.calls.append((scenario, mode, agent))
        return "ses_fake"


def test_run_scenario_starts_a_run_in_the_current_mode(gate: TestClient) -> None:
    fake = FakeRunner()
    gate_app.state.runner = fake
    gate.post("/admin/mode", json={"mode": "baseline"})
    r = gate.post("/admin/run-scenario", json={"scenario": "hero_attack", "agent": "scripted"})
    assert r.status_code == 200
    assert r.json() == {"session_id": "ses_fake", "scenario": "hero_attack", "mode": "baseline", "agent": "scripted",
                        "agent_label": "Simulated fooled agent (scripted)"}
    assert fake.calls == [("hero_attack", "baseline", "scripted")]


def test_run_scenario_labels_the_ai_agent_with_its_model(gate: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_MODEL", "gemini-3.8-flash")
    gate_app.state.runner = FakeRunner()
    r = gate.post("/admin/run-scenario", json={"scenario": "happy", "agent": "llm"})
    assert r.json()["agent_label"] == "AI agent (gemini-3.8-flash)"


def test_run_scenario_rejects_unknown_scenarios(gate: TestClient) -> None:
    gate_app.state.runner = FakeRunner()
    assert gate.post("/admin/run-scenario", json={"scenario": "nope"}).status_code == 404


def test_run_scenario_reports_a_busy_runner(gate: TestClient) -> None:
    class Busy:
        def start(self, *_: str) -> str:
            raise RunnerError(409, "run_in_progress", "a scenario is already running")

    gate_app.state.runner = Busy()
    r = gate.post("/admin/run-scenario", json={"scenario": "happy"})
    assert (r.status_code, r.json()["error"]) == (409, "run_in_progress")


# --------------------------------------------------------------------------- lookups & event data


def test_session_and_mandate_lookups(gate: TestClient) -> None:
    kit = GateKit(gate)
    m, _ = kit.mandate()
    sid = kit.session(m["mandate_id"], "hero_attack")
    s = gate.get(f"/sessions/{sid}").json()
    assert (s["mandate_id"], s["scenario"]) == (m["mandate_id"], "hero_attack")
    assert gate.get(f"/mandates/{m['mandate_id']}").json() == m
    assert gate.get("/sessions/ses_nope").status_code == 404
    assert gate.get("/mandates/mdt_nope").status_code == 404


def test_value_events_name_the_tool_call_that_produced_them(gate: TestClient) -> None:
    kit = GateKit(gate)
    sid, tok = kit.start()
    call_id = kit.tool(sid, tok, "read_email", email_id="1842").json()["tool_call_id"]
    recorded = [e["data"] for e in kit.events(sid) if e["type"] == "value_recorded"]
    assert recorded and all(d["tool_call_id"] == call_id for d in recorded)
