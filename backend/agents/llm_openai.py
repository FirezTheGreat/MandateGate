"""OpenAI-compatible provider (LLM_PROVIDER=openai): any server exposing /chat/completions
with function tools (OpenAI, or a local/hosted compatible endpoint via OPENAI_BASE_URL).

Plain HTTP on purpose: the wire format is the stable part every compatible server shares.
"""

import json
from typing import Any

import httpx

from agents.llm import LLMError, Tool, ToolCall, ToolResult, Turn


class OpenAICompatConversation:
    def __init__(
        self, *, system: str, user: str, tools: list[Tool], model: str, base_url: str, api_key: str,
        http: httpx.Client | None = None,
    ) -> None:
        self.model = model
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.http = http if http is not None else httpx.Client(base_url=base_url.rstrip("/"), headers=headers, timeout=120)
        self.tools = [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.schema}} for t in tools]
        self.messages: list[dict[str, Any]] = [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def send(self) -> Turn:
        try:
            r = self.http.post("/chat/completions", json={"model": self.model, "messages": self.messages, "tools": self.tools, "tool_choice": "auto"})
        except httpx.HTTPError as e:
            raise LLMError(f"could not reach the OpenAI-compatible endpoint ({type(e).__name__})") from e
        if r.status_code >= 400:
            raise LLMError(f"OpenAI-compatible endpoint returned {r.status_code}: {r.text[:300]}")
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
