"""Provider-pluggable tool-calling loop for the UNTRUSTED agents (CLAUDE.md §9).

    LLM_PROVIDER=anthropic (default)  Anthropic SDK, model LLM_MODEL (default claude-opus-5-5)
    LLM_PROVIDER=openai               any OpenAI-compatible /chat/completions endpoint (llm_openai.py)
    LLM_EFFORT=medium                 Anthropic effort level ("" to omit for models without effort)

`run_tool_loop` drives one conversation: at most MAX_STEPS model calls, every step logged,
tool errors handed back to the model (never raised), and the run ends as soon as a stop tool
(propose_payment) succeeds. The model never sees the delegation token or the payment pass:
the executor adds them outside the conversation.
"""

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

MAX_STEPS = 12
DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "medium"  # Claude Opus 5.5's default; set explicitly so it is visible
# Models that accept the server-side refusal fallback (`fallbacks: "default"`).
FALLBACK_MODELS = frozenset({"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"})
FALLBACK_BETA = "server-side-fallback-2026-07-01"
NO_CREDENTIALS_HINT = (
    "no Anthropic credentials: set ANTHROPIC_API_KEY in .env (or run with AGENT=scripted, which needs no LLM)"
)


class LLMError(RuntimeError):
    """The model could not be called (credentials, network, rate limit, bad request)."""


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    schema: dict[str, Any]  # JSON Schema with additionalProperties: false and every property required


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]
    error: str | None = None  # set when the provider returned unparseable arguments


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    content: str
    is_error: bool


Stop = Literal["tool_use", "end", "max_tokens", "refusal"]


@dataclass(frozen=True)
class Turn:
    stop: Stop
    text: str
    calls: list[ToolCall]
    note: str = ""


class Conversation(Protocol):
    model: str

    def send(self) -> Turn: ...

    def add_results(self, results: list[ToolResult]) -> None: ...


# --------------------------------------------------------------------------- Anthropic


class AnthropicConversation:
    """Claude via the Anthropic SDK. History is append-only: every response's full content
    (thinking, fallback and tool_use blocks) is sent back unchanged."""

    def __init__(
        self, *, system: str, user: str, tools: list[Tool], model: str = DEFAULT_MODEL,
        effort: str = DEFAULT_EFFORT, client: Any = None, max_tokens: int = 16000,
    ) -> None:
        import anthropic  # here, not at module top: the SDK takes seconds to import on Windows, and the
        # scripted and OpenAI-compatible runs never need it (it delayed every dashboard Run click)

        self.model, self.effort, self.system, self.max_tokens = model, effort, system, max_tokens
        self.client = client if client is not None else anthropic.Anthropic()
        # strict: tool inputs are guaranteed to match the schema (no forced tool_choice on Opus 5.5).
        self.tools = [{"name": t.name, "description": t.description, "input_schema": t.schema, "strict": True} for t in tools]
        self.messages: list[dict[str, Any]] = [{"role": "user", "content": user}]

    def _create(self) -> Any:
        params: dict[str, Any] = {
            "model": self.model, "max_tokens": self.max_tokens, "system": self.system,
            "tools": self.tools, "messages": self.messages,
        }
        if self.effort:
            params["output_config"] = {"effort": self.effort}
        if self.model in FALLBACK_MODELS:
            # A safety-classifier decline is re-run server-side on Anthropic's recommended model.
            return self.client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **params)
        return self.client.messages.create(**params)

    def send(self) -> Turn:
        import anthropic

        try:
            resp = self._create()
        except anthropic.AuthenticationError as e:
            raise LLMError(f"Anthropic rejected the credentials ({e.message}); check ANTHROPIC_API_KEY") from e
        except anthropic.RateLimitError as e:
            raise LLMError("Anthropic rate limit hit; wait a minute and retry") from e
        except anthropic.BadRequestError as e:
            raise LLMError(f"Anthropic rejected the request: {e.message}") from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"Anthropic API error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise LLMError("could not reach the Anthropic API (network)") from e
        except TypeError as e:  # the SDK raises TypeError when it finds no credentials at all
            if "authentication" in str(e).lower():
                raise LLMError(NO_CREDENTIALS_HINT) from e
            raise

        self.messages.append({"role": "assistant", "content": resp.content})
        text = "".join(b.text for b in resp.content if b.type == "text")
        if resp.stop_reason == "refusal":
            details = getattr(resp, "stop_details", None)
            return Turn("refusal", text, [], note=f"category={getattr(details, 'category', None)}")
        if resp.stop_reason == "max_tokens":  # never run tools from a truncated turn
            return Turn("max_tokens", text, [])
        calls = [ToolCall(b.id, b.name, dict(b.input)) for b in resp.content if b.type == "tool_use"]
        return Turn("tool_use" if calls else "end", text, calls)

    def add_results(self, results: list[ToolResult]) -> None:
        # All results of one turn go back in a single user message.
        self.messages.append({
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": r.call_id, "content": r.content, "is_error": r.is_error} for r in results],
        })


def make_conversation(*, system: str, user: str, tools: list[Tool]) -> Conversation:
    provider = os.environ.get("LLM_PROVIDER", "anthropic").strip().lower() or "anthropic"
    model = os.environ.get("LLM_MODEL", "").strip()
    if provider == "anthropic":
        effort = os.environ.get("LLM_EFFORT", DEFAULT_EFFORT).strip()
        return AnthropicConversation(system=system, user=user, tools=tools, model=model or DEFAULT_MODEL, effort=effort)
    if provider == "openai":
        from agents.llm_openai import OpenAICompatConversation

        if not model:
            raise LLMError("LLM_PROVIDER=openai needs LLM_MODEL (e.g. a model name your endpoint serves)")
        return OpenAICompatConversation(
            system=system, user=user, tools=tools, model=model,
            base_url=os.environ.get("OPENAI_BASE_URL", "").strip() or "https://api.openai.com/v1",
            api_key=os.environ.get("OPENAI_API_KEY", "").strip(),
        )
    raise LLMError(f"unknown LLM_PROVIDER {provider!r} (use anthropic or openai)")


# --------------------------------------------------------------------------- the loop

# (content for the model, is_error, raw value for the caller)
Executor = Callable[[str, dict[str, Any]], tuple[str, bool, Any]]


@dataclass(frozen=True)
class LoopResult:
    stopped: Literal["proposed", "finished", "max_steps", "refusal", "max_tokens"]
    steps: int
    final_text: str
    stop_output: Any = None  # raw result of the stop tool (the Decision)


def _clip(s: str, n: int = 160) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 3] + "..."


def run_tool_loop(
    convo: Conversation, execute: Executor, *, agent: str = "finance", max_steps: int = MAX_STEPS,
    stop_tools: frozenset[str] = frozenset({"propose_payment"}), log: Callable[[str], None] = print,
) -> LoopResult:
    text = ""
    for step in range(1, max_steps + 1):
        turn = convo.send()
        text = turn.text or text
        if turn.text:
            log(f"[{agent}] step {step} says: {_clip(turn.text)}")
        if turn.stop == "refusal":
            log(f"[{agent}] step {step}: model declined ({turn.note})")
            return LoopResult("refusal", step, text)
        if turn.stop == "max_tokens":
            log(f"[{agent}] step {step}: output hit max_tokens")
            return LoopResult("max_tokens", step, text)
        if not turn.calls:
            log(f"[{agent}] step {step}: finished without proposing a payment")
            return LoopResult("finished", step, text)

        results: list[ToolResult] = []
        stop_output: Any = None
        stopped = False
        for call in turn.calls:
            log(f"[{agent}] step {step} -> {call.name} {json.dumps(call.input, ensure_ascii=False)}")
            if call.error:
                content, is_error, raw = f"Error: {call.error}", True, None
            elif stopped and call.name in stop_tools:
                content, is_error, raw = "Error: a payment was already submitted in this run.", True, None
            else:
                content, is_error, raw = execute(call.name, call.input)
            log(f"[{agent}] step {step} <- {'ERROR ' if is_error else ''}{_clip(content)}")
            results.append(ToolResult(call.id, content, is_error))
            if call.name in stop_tools and not is_error and not stopped:
                stopped, stop_output = True, raw
        convo.add_results(results)
        if stopped:
            return LoopResult("proposed", step, text, stop_output)

    log(f"[{agent}] stopped after {max_steps} steps without a proposal")
    return LoopResult("max_steps", max_steps, text)
