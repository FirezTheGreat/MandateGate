"""Agent internals: the tool loop, both provider adapters (no network), and the zone boundary."""

import ast
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from agents import finance
from agents.llm import (
    FALLBACK_BETA,
    MAX_STEPS,
    AnthropicConversation,
    LLMError,
    Tool,
    ToolCall,
    ToolResult,
    Turn,
    make_conversation,
    run_tool_loop,
)
from agents.llm_openai import OpenAICompatConversation

AGENTS_DIR = Path(__file__).resolve().parent.parent / "agents"
TOOLS = finance.TOOLS


# --------------------------------------------------------------------------- the loop


class Scripted:
    model = "scripted-model"

    def __init__(self, turns: list[Turn]) -> None:
        self.turns, self.results = list(turns), []  # type: ignore[var-annotated]

    def send(self) -> Turn:
        return self.turns.pop(0) if self.turns else Turn("tool_use", "", [ToolCall("again", "list_inbox", {})])

    def add_results(self, results: list[ToolResult]) -> None:
        self.results.append(results)


def ok(name: str, args: dict[str, Any]) -> tuple[str, bool, Any]:
    return json.dumps({"tool": name}), False, {"tool": name, **args}


def test_loop_stops_after_the_first_successful_proposal() -> None:
    convo = Scripted([Turn("tool_use", "", [ToolCall("a", "list_inbox", {})]),
                      Turn("tool_use", "", [ToolCall("b", "propose_payment", {"x": 1}), ToolCall("c", "propose_payment", {"x": 2})])])
    r = run_tool_loop(convo, ok, log=lambda _: None)
    assert (r.stopped, r.steps, r.stop_output) == ("proposed", 2, {"tool": "propose_payment", "x": 1})
    second = convo.results[-1][1]
    assert second.is_error and "already submitted" in second.content  # one payment per run


def test_loop_is_capped_at_max_steps() -> None:
    r = run_tool_loop(Scripted([]), ok, log=lambda _: None)
    assert (r.stopped, r.steps) == ("max_steps", MAX_STEPS)


@pytest.mark.parametrize(("stop", "expected"), [("refusal", "refusal"), ("max_tokens", "max_tokens"), ("end", "finished")])
def test_loop_ends_on_non_tool_turns(stop: str, expected: str) -> None:
    r = run_tool_loop(Scripted([Turn(stop, "text", [])]), ok, log=lambda _: None)  # type: ignore[arg-type]
    assert r.stopped == expected


def test_unparseable_arguments_become_an_error_result() -> None:
    convo = Scripted([Turn("tool_use", "", [ToolCall("a", "read_email", {}, error="arguments were not valid JSON")]), Turn("end", "", [])])
    calls: list[str] = []
    run_tool_loop(convo, lambda n, a: (calls.append(n), ok(n, a))[1], log=lambda _: None)
    assert calls == [] and convo.results[0][0].is_error


def test_every_step_is_logged() -> None:
    lines: list[str] = []
    run_tool_loop(Scripted([Turn("tool_use", "Looking.", [ToolCall("a", "list_inbox", {})]), Turn("end", "", [])]), ok, log=lines.append)
    assert any("step 1 says: Looking." in line for line in lines)
    assert any("step 1 -> list_inbox" in line for line in lines) and any("step 1 <- " in line for line in lines)


# --------------------------------------------------------------------------- Anthropic adapter (fake SDK client)


class FakeMessages:
    def __init__(self, responses: list[Any]) -> None:
        self.responses, self.calls = list(responses), []  # type: ignore[var-annotated]

    def create(self, **kw: Any) -> Any:
        self.calls.append(kw)
        return self.responses.pop(0)


def fake_client(responses: list[Any]) -> Any:
    beta, plain = FakeMessages(responses), FakeMessages(responses)
    return SimpleNamespace(beta=SimpleNamespace(messages=beta), messages=plain)


def response(stop_reason: str, *blocks: Any, stop_details: Any = None) -> Any:
    return SimpleNamespace(stop_reason=stop_reason, content=list(blocks), stop_details=stop_details)


TEXT = SimpleNamespace(type="text", text="Checking the inbox.")
THINKING = SimpleNamespace(type="thinking", thinking="", signature="sig")
TOOL_USE = SimpleNamespace(type="tool_use", id="toolu_1", name="read_email", input={"email_id": "1842"})


def test_anthropic_request_shape_on_opus() -> None:
    client = fake_client([response("tool_use", THINKING, TEXT, TOOL_USE)])
    convo = AnthropicConversation(system="sys", user="Pay INV-1048", tools=TOOLS, client=client)
    turn = convo.send()
    kw = client.beta.messages.calls[0]
    assert kw["model"] == "claude-opus-5-5"
    assert kw["fallbacks"] == "default" and kw["betas"] == [FALLBACK_BETA]
    assert kw["output_config"] == {"effort": "medium"}
    assert "thinking" not in kw and "tool_choice" not in kw  # adaptive by default; forced tool use 400s on Opus 5.5
    assert all(t["strict"] is True and t["input_schema"]["additionalProperties"] is False for t in kw["tools"])
    assert turn == Turn("tool_use", "Checking the inbox.", [ToolCall("toolu_1", "read_email", {"email_id": "1842"})])
    # append-only: the full content (incl. thinking) goes back unchanged
    assert convo.messages[-1] == {"role": "assistant", "content": [THINKING, TEXT, TOOL_USE]}


def test_anthropic_tool_results_go_back_in_one_user_message() -> None:
    convo = AnthropicConversation(system="s", user="u", tools=TOOLS, client=fake_client([]))
    convo.add_results([ToolResult("t1", "a", False), ToolResult("t2", "b", True)])
    assert convo.messages[-1] == {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": "a", "is_error": False},
        {"type": "tool_result", "tool_use_id": "t2", "content": "b", "is_error": True},
    ]}


def test_anthropic_models_without_fallback_use_the_plain_endpoint() -> None:
    client = fake_client([response("end_turn", TEXT)])
    AnthropicConversation(system="s", user="u", tools=TOOLS, client=client, model="claude-haiku-5-5", effort="").send()
    kw = client.messages.calls[0]
    assert "fallbacks" not in kw and "output_config" not in kw and client.beta.messages.calls == []


def test_anthropic_refusal_and_max_tokens_are_mapped() -> None:
    refusal = response("refusal", stop_details=SimpleNamespace(category="cyber"))
    convo = AnthropicConversation(system="s", user="u", tools=TOOLS, client=fake_client([refusal, response("max_tokens", TOOL_USE)]))
    assert convo.send() == Turn("refusal", "", [], note="category=cyber")
    assert convo.send().stop == "max_tokens"  # a truncated turn never runs tools


def test_missing_credentials_become_a_clear_error() -> None:
    class NoCreds:
        def create(self, **_: Any) -> Any:
            raise TypeError('"Could not resolve authentication method. Expected one of api_key, ..."')

    client = SimpleNamespace(beta=SimpleNamespace(messages=NoCreds()), messages=NoCreds())
    with pytest.raises(LLMError, match="ANTHROPIC_API_KEY"):
        AnthropicConversation(system="s", user="u", tools=TOOLS, client=client).send()


# --------------------------------------------------------------------------- OpenAI-compatible adapter (mock transport)


def test_openai_compatible_round_trip() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        if len(seen) == 1:
            return httpx.Response(200, json={"choices": [{"finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": None, "tool_calls": [
                    {"id": "c1", "type": "function", "function": {"name": "read_email", "arguments": '{"email_id": "1842"}'}},
                    {"id": "c2", "type": "function", "function": {"name": "get_vendor", "arguments": "{oops"}},
                ]}}]})
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "Done."}}]})

    http = httpx.Client(base_url="http://llm.test/v1", transport=httpx.MockTransport(handler))
    convo = OpenAICompatConversation(system="sys", user="u", tools=TOOLS, model="m", base_url="", api_key="", http=http)
    turn = convo.send()
    assert [c.name for c in turn.calls] == ["read_email", "get_vendor"]
    assert turn.calls[0].input == {"email_id": "1842"} and turn.calls[1].error == "arguments were not valid JSON"
    convo.add_results([ToolResult("c1", "x", False), ToolResult("c2", "Error", True)])
    assert convo.send() == Turn("end", "Done.", [])
    assert seen[0]["tools"][0]["type"] == "function" and seen[0]["messages"][0] == {"role": "system", "content": "sys"}
    assert [m["role"] for m in seen[1]["messages"]] == ["system", "user", "assistant", "tool", "tool"]


def test_provider_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    with pytest.raises(LLMError, match="LLM_MODEL"):
        make_conversation(system="s", user="u", tools=TOOLS)
    monkeypatch.setenv("LLM_PROVIDER", "nope")
    with pytest.raises(LLMError, match="unknown LLM_PROVIDER"):
        make_conversation(system="s", user="u", tools=TOOLS)


# --------------------------------------------------------------------------- tool schemas & zone boundary


def test_tool_schemas_are_strict_compatible() -> None:
    for t in TOOLS:
        assert isinstance(t, Tool)
        assert t.schema["additionalProperties"] is False and set(t.schema["required"]) == set(t.schema["properties"])
    assert {t.name for t in TOOLS} == {"list_inbox", "read_email", "get_invoice", "get_vendor", "propose_payment"}


def test_finance_prompt_is_ordinary() -> None:
    """Realism (CLAUDE.md §9): no security coaching, no instructions to distrust email."""
    prompt = finance.SYSTEM_PROMPT.lower()
    assert "propose_payment" in prompt
    assert not any(w in prompt for w in ("phishing", "scam", "fraud", "suspicious", "injection", "mandategate"))


@pytest.mark.parametrize("path", sorted(AGENTS_DIR.glob("*.py")), ids=lambda p: p.name)
def test_agents_never_import_the_gate(path: Path) -> None:
    """The untrusted zone talks to the gate over HTTP only (CLAUDE.md §9)."""
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
        assert not any(n == "app" or n.startswith(("app.", "payment_service")) for n in names), (path.name, names)
