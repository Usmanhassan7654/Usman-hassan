"""Model providers behind one interface.

The agent speaks a small provider-neutral message format; each adapter
converts it to its API:

    {"role": "user", "content": str}
    {"role": "state", "content": str}          authoritative store state for this turn
    {"role": "assistant", "content": str, "tool_calls": [{"id", "name", "args"}], "raw": provider blocks}
    {"role": "tool", "id": str, "name": str, "content": str, "is_error": bool}

Providers:
    groq     OpenAI-compatible API at api.groq.com          (GROQ_API_KEY)
    gemini   Gemini's OpenAI-compatible endpoint            (GEMINI_API_KEY or GOOGLE_API_KEY)
    claude   Anthropic Messages API                         (ANTHROPIC_API_KEY)

SAUDA_LLM picks the chain, tried in order when a call fails with a rate limit,
server error or timeout, e.g.  SAUDA_LLM="groq:openai/gpt-oss-20b,gemini:gemini-flash-latest"
"""

from __future__ import annotations

import json
import os
import random
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import requests

DEFAULT_MODELS = {"groq": "openai/gpt-oss-20b", "gemini": "gemini-flash-latest", "claude": "claude-opus-5-5"}
BASE_URLS = {"groq": "https://api.groq.com/openai/v1", "gemini": "https://generativelanguage.googleapis.com/v1beta/openai"}
GEMINI_SKIP_SIGNATURE = "skip_thought_signature_validator"
KEY_VARS = {"groq": ("GROQ_API_KEY",), "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"), "claude": ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}


class LLMError(Exception):
    def __init__(self, message: str, retryable: bool = False, provider: str = ""):
        super().__init__(message)
        self.retryable = retryable
        self.provider = provider


@dataclass
class Reply:
    text: str
    tool_calls: list[dict]
    stop: str                      # tool_use | end | refusal | length | pause
    raw: Any = None
    usage: dict = field(default_factory=dict)
    model: str = ""


class ChatModel:
    name = "model"

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> Reply:  # pragma: no cover
        raise NotImplementedError


# ------------------------------------------------------------- Anthropic

class AnthropicModel(ChatModel):
    def __init__(self, model: str = DEFAULT_MODELS["claude"], effort: str = "medium", client: Any = None):
        if client is None:
            import anthropic

            client = anthropic.Anthropic(max_retries=2, timeout=60)
        self.client, self.model, self.effort = client, model, effort
        self.name = f"claude:{model}"

    def complete(self, system, messages, tools) -> Reply:
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            tools=tools,
            messages=self._convert(messages),
            output_config={"effort": self.effort},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        blocks = response.content
        text = "\n\n".join(b.text for b in blocks if getattr(b, "type", "") == "text" and b.text.strip()).strip()
        calls = [{"id": b.id, "name": b.name, "args": dict(b.input or {})} for b in blocks if getattr(b, "type", "") == "tool_use"]
        stop = {"tool_use": "tool_use", "refusal": "refusal", "max_tokens": "length", "pause_turn": "pause"}.get(response.stop_reason, "end")
        u = getattr(response, "usage", None)
        usage = {"input_tokens": getattr(u, "input_tokens", 0) or 0, "output_tokens": getattr(u, "output_tokens", 0) or 0,
                 "cached_tokens": getattr(u, "cache_read_input_tokens", 0) or 0} if u else {}
        return Reply(text, calls, stop, raw=blocks, usage=usage, model=self.name)

    @staticmethod
    def _convert(messages: list[dict]) -> list[dict]:
        out: list[dict] = []
        for m in messages:
            role = m["role"]
            if role == "user":
                out.append({"role": "user", "content": m["content"]})
            elif role == "state":
                out.append({"role": "system", "content": m["content"]})  # mid-conversation system message
            elif role == "assistant":
                if m.get("raw") is not None:
                    out.append({"role": "assistant", "content": m["raw"]})
                elif m.get("tool_calls"):
                    blocks = ([{"type": "text", "text": m["content"]}] if m.get("content") else [])
                    blocks += [{"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["args"]} for c in m["tool_calls"]]
                    out.append({"role": "assistant", "content": blocks})
                else:
                    out.append({"role": "assistant", "content": m.get("content") or "…"})
            elif role == "tool":
                block = {"type": "tool_result", "tool_use_id": m["id"], "content": m["content"]}
                if m.get("is_error"):
                    block["is_error"] = True
                if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                    out[-1]["content"].append(block)  # all results of one round in one message
                else:
                    out.append({"role": "user", "content": [block]})
        return out


# ------------------------------------------------- OpenAI-compatible APIs

class OpenAICompatModel(ChatModel):
    """Groq and Gemini (and any other OpenAI-compatible chat completions API)."""

    def __init__(self, provider: str, model: str, api_key: str, base_url: str | None = None, timeout: float = 60,
                 max_retries: int = 3, session: requests.Session | None = None):
        self.provider, self.model, self.api_key = provider, model, api_key
        self.base_url = (base_url or BASE_URLS[provider]).rstrip("/")
        self.timeout, self.max_retries = timeout, max_retries
        self.session = session or requests.Session()
        self.name = f"{provider}:{model}"

    def complete(self, system, messages, tools) -> Reply:
        body = {
            "model": self.model,
            "messages": self._convert(system, messages),
            "tools": [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                        "parameters": _clean_schema(t["input_schema"])}} for t in tools],
            "tool_choice": "auto",
            "temperature": 0.2,
            "max_tokens": 2048,  # replies are short; a smaller reservation also counts less against per-minute token limits
        }
        data = self._post(body)
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        calls = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            raw_args = fn.get("arguments") or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
                if not isinstance(args, dict):
                    raise ValueError
            except ValueError:
                args = {"__invalid_arguments__": str(raw_args)[:500]}
            call = {"id": tc.get("id") or f"call_{uuid.uuid4().hex[:12]}", "name": fn.get("name", ""), "args": args}
            if tc.get("extra_content"):  # e.g. Gemini's thought signature, which must be sent back with the call
                call["extra"] = {"provider": self.provider, "content": tc["extra_content"]}
            calls.append(call)
        finish = choice.get("finish_reason") or ""
        stop = "tool_use" if calls else {"length": "length", "content_filter": "refusal"}.get(finish, "end")
        u = data.get("usage") or {}
        usage = {"input_tokens": u.get("prompt_tokens", 0) or 0, "output_tokens": u.get("completion_tokens", 0) or 0,
                 "cached_tokens": (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0}
        return Reply((msg.get("content") or "").strip(), calls, stop, usage=usage, model=self.name)

    def _post(self, body: dict) -> dict:
        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        regenerated = False
        for attempt in range(self.max_retries + 1):
            try:
                r = self.session.post(url, json=body, headers=headers, timeout=self.timeout)
            except requests.RequestException as e:
                if attempt == self.max_retries:
                    raise LLMError(f"{self.name}: connection failed ({type(e).__name__}: {e})", retryable=True, provider=self.provider) from e
                time.sleep(_backoff(attempt))
                continue
            if r.status_code == 200:
                return r.json()
            detail = _error_detail(r)
            # Groq answers 400 (tool_use_failed / "Parsing failed") when the model wrote a malformed tool call; a fresh try usually works.
            bad_generation = r.status_code == 400 and any(t in r.text for t in ("tool_use_failed", "failed_generation", "Parsing failed", "output_parse_failed"))
            # An exhausted daily/plan quota won't recover in seconds: hand over to the next provider at once.
            quota_gone = r.status_code == 429 and any(t in r.text.lower() for t in ("quota", "per day", "(tpd)", "(rpd)", "billing"))
            retryable = r.status_code in (408, 409, 429) or r.status_code >= 500 or bad_generation
            if retryable and attempt < self.max_retries and not (bad_generation and regenerated) and not quota_gone:
                regenerated = regenerated or bad_generation  # a malformed tool call gets one fresh try
                time.sleep(_retry_wait(r, attempt))
                continue
            raise LLMError(f"{self.name}: HTTP {r.status_code} {detail}", retryable=retryable, provider=self.provider)
        raise LLMError(f"{self.name}: no response", retryable=True, provider=self.provider)

    def _convert(self, system: str, messages: list[dict]) -> list[dict]:
        out: list[dict] = [{"role": "system", "content": system}]
        for m in messages:
            role = m["role"]
            if role == "user":
                out.append({"role": "user", "content": m["content"]})
            elif role == "state":
                # One system prompt is the portable shape; the state rides with the customer's message.
                if out[-1]["role"] == "user":
                    out[-1] = {"role": "user", "content": f"{out[-1]['content']}\n\n<store_state>\n{m['content']}\n</store_state>"}
                else:
                    out.append({"role": "user", "content": f"<store_state>\n{m['content']}\n</store_state>"})
            elif role == "assistant":
                entry: dict[str, Any] = {"role": "assistant", "content": m.get("content") or ""}
                if m.get("tool_calls"):
                    entry["tool_calls"] = [self._tool_call(c) for c in m["tool_calls"]]
                    if not entry["content"]:
                        entry["content"] = None
                out.append(entry)
            elif role == "tool":
                out.append({"role": "tool", "tool_call_id": m["id"], "content": m["content"]})
        return out

    def _tool_call(self, c: dict) -> dict:
        tc = {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": json.dumps(c["args"], ensure_ascii=False)}}
        extra = c.get("extra") or {}
        if extra.get("provider") == self.provider:
            tc["extra_content"] = extra["content"]
        elif self.provider == "gemini":
            # Gemini's thinking models expect a thought signature on earlier tool calls. Calls made by another
            # provider have none; this documented placeholder tells Gemini to accept them as plain history.
            tc["extra_content"] = {"google": {"thought_signature": GEMINI_SKIP_SIGNATURE}}
        return tc

    def list_models(self) -> list[str]:
        r = self.session.get(f"{self.base_url}/models", headers={"Authorization": f"Bearer {self.api_key}"}, timeout=self.timeout)
        if r.status_code != 200:
            raise LLMError(f"{self.name}: HTTP {r.status_code} {_error_detail(r)}", provider=self.provider)
        return sorted(m.get("id", "").removeprefix("models/") for m in r.json().get("data", []))


# -------------------------------------------------------------- fallback

class FallbackModel(ChatModel):
    """Try each model in order; move on when one is rate limited, down, times out or rejects the request.

    A provider that just failed is tried last for the next COOLDOWN_S seconds, so the rest of a
    customer's turn doesn't keep waiting on it.
    """

    COOLDOWN_S = 60

    def __init__(self, models: list[ChatModel]):
        if not models:
            raise ValueError("No model configured.")
        self.models = models
        self.name = " -> ".join(m.name for m in models)
        self.last_used = ""
        self.failovers = 0
        self._failed_at: dict[str, float] = {}

    def complete(self, system, messages, tools) -> Reply:
        now = time.monotonic()
        order = sorted(self.models, key=lambda m: now - self._failed_at.get(m.name, -1e9) < self.COOLDOWN_S)
        errors = []
        for model in order:
            try:
                reply = model.complete(system, messages, tools)
                self.last_used = model.name
                return reply
            except Exception as e:  # LLMError, or an SDK error from the Claude adapter
                errors.append(str(e) if isinstance(e, LLMError) else f"{model.name}: {type(e).__name__}: {e}")
                self._failed_at[model.name] = time.monotonic()
                self.failovers += 1
        raise LLMError("All models failed: " + " | ".join(errors), retryable=True)


# ---------------------------------------------------------------- config

def _key(provider: str) -> str | None:
    return next((os.environ[v] for v in KEY_VARS[provider] if os.environ.get(v)), None)


def build(spec: str | None = None, effort: str = "medium") -> ChatModel:
    """Build the model chain from SAUDA_LLM (or `spec`); default: every provider that has a key, Groq first."""
    spec = spec if spec is not None else os.environ.get("SAUDA_LLM", "")
    entries = [s.strip() for s in spec.split(",") if s.strip()] or [p for p in ("groq", "gemini", "claude") if _key(p)]
    models: list[ChatModel] = []
    for entry in entries:
        provider, _, model = entry.partition(":")
        provider = provider.strip().lower()
        if provider not in DEFAULT_MODELS:
            raise ValueError(f"Unknown provider '{provider}'. Use groq, gemini or claude.")
        model = model.strip() or DEFAULT_MODELS[provider]
        if provider == "claude":
            models.append(AnthropicModel(model, effort))
            continue
        key = _key(provider)
        if not key:
            raise ValueError(f"{provider} is configured but {' or '.join(KEY_VARS[provider])} is not set.")
        models.append(OpenAICompatModel(provider, model, key))
    if not models:
        raise ValueError("No model provider configured. Set GROQ_API_KEY, GEMINI_API_KEY or ANTHROPIC_API_KEY (and optionally SAUDA_LLM).")
    return models[0] if len(models) == 1 else FallbackModel(models)


def configured() -> bool:
    return any(_key(p) for p in KEY_VARS)


# ------------------------------------------------------------------ helpers

_SCHEMA_KEYS = {"type", "description", "properties", "required", "items", "enum", "minimum", "maximum", "minItems", "maxItems", "nullable", "format"}


def _clean_schema(schema: Any) -> Any:
    """Keep the JSON Schema subset every provider accepts (Gemini's is the narrowest)."""
    if isinstance(schema, dict):
        out = {}
        for k, v in schema.items():
            if k == "properties" and isinstance(v, dict):
                out[k] = {name: _clean_schema(sub) for name, sub in v.items()}
            elif k in _SCHEMA_KEYS:
                out[k] = _clean_schema(v)
        if out.get("type") == "object" and "properties" not in out:
            out["properties"] = {}
        return out
    if isinstance(schema, list):
        return [_clean_schema(s) for s in schema]
    return schema


def _retry_wait(r: requests.Response, attempt: int) -> float:
    """Honour the provider's retry-after (rate limits often ask for 5-30 s), within reason."""
    for header in ("retry-after", "x-ratelimit-reset-tokens", "x-ratelimit-reset-requests"):
        value = r.headers.get(header, "")
        m = re.match(r"^\s*(?:(\d+)m)?\s*([\d.]+)\s*(ms|s)?\s*$", value)
        if m and value:
            seconds = float(m.group(2)) / (1000 if m.group(3) == "ms" else 1) + 60 * int(m.group(1) or 0)
            return min(max(seconds, 0.5), 30.0)
    return _backoff(attempt) * (3 if r.status_code == 429 else 1)


def _backoff(attempt: int) -> float:
    return min(8.0, 1.5 * 2 ** attempt) + random.uniform(0, 0.5)


def _error_detail(r: requests.Response) -> str:
    """The provider's error message. Groq sends {"error": {...}}; Gemini sends [{"error": {...}}]."""
    try:
        body = r.json()
    except ValueError:
        return r.text[:300]
    if isinstance(body, list) and body:
        body = body[0]
    err = body.get("error") if isinstance(body, dict) else body
    if isinstance(err, dict):
        return str(err.get("message") or err.get("status") or err)[:300]
    return str(err or r.text)[:300]
