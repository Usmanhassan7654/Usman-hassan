"""Groq / Gemini adapter (OpenAI-compatible) and provider fallback, with a fake HTTP session."""

import json

import pytest

from sauda import llm
from sauda.agent import Agent
from sauda.tools import TOOLS


class FakeResponse:
    def __init__(self, status, body, headers=None):
        self.status_code, self._body, self.headers = status, body, headers or {}
        self.text = json.dumps(body)

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, responses):
        self.responses, self.requests = list(responses), []

    def post(self, url, json=None, headers=None, timeout=None):
        self.requests.append({"url": url, "body": json, "headers": headers})
        step = self.responses.pop(0)
        return step if isinstance(step, FakeResponse) else FakeResponse(200, step)


def completion(content=None, tool_calls=None, finish="stop"):
    msg = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = [{"id": f"call_{i}", "type": "function", "function": {"name": n, "arguments": json.dumps(a) if not isinstance(a, str) else a}}
                             for i, (n, a) in enumerate(tool_calls)]
        finish = "tool_calls"
    return {"choices": [{"message": msg, "finish_reason": finish}], "usage": {"prompt_tokens": 100, "completion_tokens": 20}}


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)


def test_request_shape_for_groq_and_gemini():
    for provider, base in (("groq", "https://api.groq.com/openai/v1"), ("gemini", "https://generativelanguage.googleapis.com/v1beta/openai")):
        session = FakeSession([completion("Hi")])
        m = llm.OpenAICompatModel(provider, llm.DEFAULT_MODELS[provider], "secret", session=session)
        reply = m.complete("SYSTEM", [{"role": "user", "content": "doodh"}, {"role": "state", "content": "{\"needs\": []}"}], TOOLS)
        req = session.requests[0]
        assert req["url"] == f"{base}/chat/completions" and req["headers"]["Authorization"] == "Bearer secret"
        msgs = req["body"]["messages"]
        assert msgs[0] == {"role": "system", "content": "SYSTEM"}
        assert len(msgs) == 2 and msgs[1]["content"].startswith("doodh\n\n<store_state>")  # state rides with the message
        names = [t["function"]["name"] for t in req["body"]["tools"]]
        assert names == [t["name"] for t in TOOLS]
        assert reply.text == "Hi" and reply.stop == "end" and reply.usage["input_tokens"] == 100


def test_schemas_keep_only_the_portable_subset():
    params = [llm._clean_schema(t["input_schema"]) for t in TOOLS]
    flat = json.dumps(params)
    assert "additionalProperties" not in flat
    def objects_have_properties(s):
        if isinstance(s, dict):
            if s.get("type") == "object":
                assert "properties" in s
            for v in s.values():
                objects_have_properties(v)
        elif isinstance(s, list):
            for v in s:
                objects_have_properties(v)
    objects_have_properties(params)


def test_tool_calls_round_trip_and_bad_json():
    session = FakeSession([completion(tool_calls=[("find_products", {"need_ids": ["n1"]}), ("show", "{not json")])])
    m = llm.OpenAICompatModel("groq", "x", "k", session=session)
    r = m.complete("S", [{"role": "user", "content": "hi"}], TOOLS)
    assert r.stop == "tool_use" and r.tool_calls[0] == {"id": "call_0", "name": "find_products", "args": {"need_ids": ["n1"]}}
    assert "__invalid_arguments__" in r.tool_calls[1]["args"]
    # history goes back in OpenAI shape
    convo = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "", "tool_calls": r.tool_calls},
             {"role": "tool", "id": "call_0", "name": "find_products", "content": "{}"}]
    out = m._convert("S", convo)
    assert out[2]["content"] is None and out[2]["tool_calls"][0]["function"]["arguments"] == '{"need_ids": ["n1"]}'
    assert out[3] == {"role": "tool", "tool_call_id": "call_0", "content": "{}"}


def test_retries_rate_limits_then_fails_over_to_the_next_provider():
    groq = FakeSession([FakeResponse(429, {"error": {"message": "rate limited"}}, {"retry-after": "1"})] * 3)
    gemini = FakeSession([completion("from gemini")])
    chain = llm.FallbackModel([llm.OpenAICompatModel("groq", "g", "k", session=groq, max_retries=2),
                               llm.OpenAICompatModel("gemini", "m", "k", session=gemini)])
    r = chain.complete("S", [{"role": "user", "content": "hi"}], TOOLS)
    assert len(groq.requests) == 3 and r.text == "from gemini" and r.model == "gemini:m" and chain.failovers == 1


def test_bad_request_moves_on_and_total_failure_is_reported():
    bad = FakeSession([FakeResponse(400, {"error": {"message": "schema rejected"}})])
    down = FakeSession([FakeResponse(503, {"error": "down"})] * 4)
    chain = llm.FallbackModel([llm.OpenAICompatModel("gemini", "m", "k", session=bad), llm.OpenAICompatModel("groq", "g", "k", session=down)])
    with pytest.raises(llm.LLMError) as e:
        chain.complete("S", [{"role": "user", "content": "hi"}], TOOLS)
    assert "schema rejected" in str(e.value) and "HTTP 503" in str(e.value)


def test_build_from_environment(monkeypatch):
    for v in ("GROQ_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "SAUDA_LLM"):
        monkeypatch.delenv(v, raising=False)
    with pytest.raises(ValueError, match="No model provider"):
        llm.build()
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setenv("GEMINI_API_KEY", "m")
    chain = llm.build()
    assert chain.name == "groq:openai/gpt-oss-20b -> gemini:gemini-flash-latest"
    assert llm.build("gemini:gemini-2.5-pro").name == "gemini:gemini-2.5-pro"
    with pytest.raises(ValueError, match="ANTHROPIC|not set|Unknown"):
        llm.build("openai:gpt")


def test_full_shopping_turn_on_the_openai_compatible_adapter(repo, scope):
    session = FakeSession([
        completion(tool_calls=[("update_needs", {"needs": [{"label": "Aloo", "kinds": ["produce.potato"], "quantity": {"amount": 2, "unit": "kg"}}]})]),
        completion(tool_calls=[("find_products", {"need_ids": ["n1"]})]),
        completion(tool_calls=[("choose_products", {"choices": [{"need_id": "n1", "product_id": "demo-mart:VEG-001"}]})]),
        completion("2 kg aloo: Rs 240. Basket mein daal doon?"),
    ])
    agent = Agent(repo, model=llm.OpenAICompatModel("groq", "openai/gpt-oss-120b", "k", session=session))
    r = agent.handle(scope, "s1", "2 kilo aloo")
    plan = next(c for c in r.cards if c["type"] == "plan")
    assert [(l["name"], l["packs"], l["line_total"]) for l in plan["lines"]] == [("Potatoes 1 kg", 2, 240)]
    assert r.grounding == {"issues": []} and r.usage["models"] == ["groq:openai/gpt-oss-120b"]
    # the tool results reached the model in OpenAI format, bound to the right call ids
    last = session.requests[-1]["body"]["messages"]
    tool_msgs = [m for m in last if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_msgs] == ["call_0", "call_0", "call_0"]
    assert "Potatoes 1 kg" in tool_msgs[1]["content"] and "Chips" not in tool_msgs[1]["content"]


def test_grounding_check_also_guards_open_models(repo, scope):
    session = FakeSession([
        completion(tool_calls=[("update_needs", {"needs": [{"label": "Cheeni", "kinds": ["staples.sugar"]}]})]),
        completion(tool_calls=[("find_products", {"need_ids": ["n1"]})]),
        completion("Cheeni Rs 99 ki hai, maine basket mein add kar di hai."),   # wrong price + false basket claim
        completion("Cheeni Rs 155 (1 kg) hai. Basket mein daal doon?"),
    ])
    r = Agent(repo, model=llm.OpenAICompatModel("gemini", "gemini-flash-latest", "k", session=session)).handle(scope, "s1", "cheeni")
    assert r.reply.startswith("Cheeni Rs 155") and len(r.grounding["corrected"]) == 2


def test_gemini_thought_signatures_are_sent_back_or_placeholdered():
    session = FakeSession([{"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
        {"id": "g1", "type": "function", "function": {"name": "find_products", "arguments": "{}"},
         "extra_content": {"google": {"thought_signature": "SIG"}}}]}, "finish_reason": "tool_calls"}]}])
    gem = llm.OpenAICompatModel("gemini", "gemini-flash-latest", "k", session=session)
    r = gem.complete("S", [{"role": "user", "content": "hi"}], TOOLS)
    own = {"role": "assistant", "content": "", "tool_calls": r.tool_calls}
    from_groq = {"role": "assistant", "content": "", "tool_calls": [{"id": "c9", "name": "show", "args": {}}]}
    out = gem._convert("S", [{"role": "user", "content": "hi"}, from_groq, {"role": "tool", "id": "c9", "name": "show", "content": "{}"}, own])
    assert out[2]["tool_calls"][0]["extra_content"] == {"google": {"thought_signature": llm.GEMINI_SKIP_SIGNATURE}}
    assert out[4]["tool_calls"][0]["extra_content"] == {"google": {"thought_signature": "SIG"}}
    # Groq never receives Gemini-only fields
    groq_out = llm.OpenAICompatModel("groq", "g", "k")._convert("S", [{"role": "user", "content": "hi"}, own])
    assert "extra_content" not in groq_out[2]["tool_calls"][0]


def test_rate_limit_waits_follow_the_provider(monkeypatch):
    waits = []
    monkeypatch.setattr(llm.time, "sleep", waits.append)
    session = FakeSession([FakeResponse(429, {"error": {"message": "tpm"}}, {"retry-after": "12"}),
                           FakeResponse(429, {"error": {"message": "tpm"}}, {"x-ratelimit-reset-tokens": "1m5.5s"}),
                           FakeResponse(400, {"error": {"message": "x", "code": "tool_use_failed"}}),
                           completion("ok")])
    r = llm.OpenAICompatModel("groq", "g", "k", session=session).complete("S", [{"role": "user", "content": "hi"}], TOOLS)
    assert r.text == "ok" and waits[0] == 12 and waits[1] == 30  # capped


def test_failed_provider_is_tried_last_for_a_while():
    groq = FakeSession([FakeResponse(401, {"error": {"message": "invalid api key"}})] + [completion("groq back")])
    gemini = FakeSession([completion("one"), completion("two")])
    chain = llm.FallbackModel([llm.OpenAICompatModel("groq", "g", "k", session=groq), llm.OpenAICompatModel("gemini", "m", "k", session=gemini)])
    assert chain.complete("S", [{"role": "user", "content": "a"}], TOOLS).text == "one"
    assert chain.complete("S", [{"role": "user", "content": "b"}], TOOLS).text == "two"   # groq skipped during cooldown
    assert len(groq.requests) == 1


def test_provider_errors_are_reported_not_hidden(repo, scope):
    down = FakeSession([FakeResponse(401, {"error": {"message": "Invalid API Key"}})])
    r = Agent(repo, model=llm.OpenAICompatModel("groq", "g", "bad", session=down)).handle(scope, "s1", "doodh")
    assert r.reply.startswith("Sorry, I'm having trouble") and "Invalid API Key" in r.usage["errors"][0]


def test_gemini_list_shaped_errors_are_read():
    session = FakeSession([FakeResponse(400, [{"error": {"code": 400, "message": "Please pass a valid API key", "status": "INVALID_ARGUMENT"}}])])
    with pytest.raises(llm.LLMError, match="Please pass a valid API key"):
        llm.OpenAICompatModel("gemini", "gemini-flash-latest", "bad", session=session).complete("S", [{"role": "user", "content": "hi"}], TOOLS)
