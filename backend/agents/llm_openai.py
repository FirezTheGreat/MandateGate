"""OpenAI-compatible provider (LLM_PROVIDER=openai): any server exposing /chat/completions
with function tools (OpenAI, or a local/hosted compatible endpoint via OPENAI_BASE_URL).

Plain HTTP on purpose: the wire format is the stable part every compatible server shares.
"""

import json
import time
from typing import Any

import httpx

from agents.llm import LLMError, Tool, ToolCall, ToolResult, Turn


RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class OpenAICompatConversation:
    def __init__(
        self, *, system: str, user: str, tools: list[Tool], model: str, base_url: str, api_key: str,
        http: httpx.Client | None = None, attempts: int = 3, backoff_s: float = 3.0,
    ) -> None:
        self.model, self.attempts, self.backoff_s = model, attempts, backoff_s
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.http = http if http is not None else httpx.Client(base_url=base_url.rstrip("/"), headers=headers, timeout=120)
        self.tools = [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.schema}} for t in tools]
        self.messages: list[dict[str, Any]] = [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def _post(self) -> httpx.Response:
        """POST with retries: free tiers time out and throttle. Timeouts, connection errors,
        429 and 5xx are retried with backoff; other 4xx are our fault and raised at once."""
        body = {"model": self.model, "messages": self.messages, "tools": self.tools, "tool_choice": "auto"}
        problem = ""
        for attempt in range(1, self.attempts + 1):
            try:
                r = self.http.post("/chat/completions", json=body)
            except (httpx.TimeoutException, httpx.TransportError) as e:
                problem = f"could not reach the OpenAI-compatible endpoint ({type(e).__name__})"
            else:
                if r.status_code < 400:
                    return r
                if r.status_code not in RETRYABLE_STATUS:
                    raise LLMError(f"OpenAI-compatible endpoint returned {r.status_code}: {r.text[:300]}")
                problem = f"OpenAI-compatible endpoint returned {r.status_code}: {r.text[:300]}"
            if attempt < self.attempts:
                time.sleep(self.backoff_s * attempt)
        raise LLMError(f"{problem} (after {self.attempts} attempts)")

    def send(self) -> Turn:
        r = self._post()
        choice = r.json()["choices"][0]
        msg = choice["message"]
        self.messages.append({k: msg[k] for k in ("role", "content", "tool_calls") if k in msg})

        calls: list[ToolCall] = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function", {})
            try:
                args = json.loads(fn.get("arguments") or "{}")
                error = None if isinstance(args, dict) else "arguments must be a JSON object"
            except json.JSONDecodeError:
                args, error = {}, "arguments were not valid JSON"
            calls.append(ToolCall(tc["id"], fn.get("name", ""), args if isinstance(args, dict) else {}, error))

        text = msg.get("content") or ""
        finish = choice.get("finish_reason")
        if finish == "content_filter":
            return Turn("refusal", text, [], note="content_filter")
        if finish == "length":
            return Turn("max_tokens", text, [])
        return Turn("tool_use" if calls else "end", text, calls)

    def add_results(self, results: list[ToolResult]) -> None:
        for r in results:
            self.messages.append({"role": "tool", "tool_call_id": r.call_id, "content": r.content})
