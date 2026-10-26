"""Whole customer turns through the agent, with a scripted stand-in for Claude.

These check what the customer sees: the reply, the cards, the totals and
the basket, and that they agree with each other.
"""

from sauda import basket as B
from sauda.agent import Agent
from conftest import FakeClient, resp, text, tool

MILK, EGGS, BREAD = "demo-mart:MLK-003", "demo-mart:EGG-001", "demo-mart:BAK-001"   # 295, 390, 190


def breakfast_script(final_reply):
    return [
        resp(tool("update_needs", {"household": {"people": 2, "days": 7}, "needs": [
            {"label": "Milk", "kinds": ["dairy.milk"], "search_terms": ["milk"]},
            {"label": "Eggs", "kinds": ["dairy.eggs"]},
            {"label": "Bread", "kinds": ["bakery.bread"]}]}, "u1"), stop="tool_use"),
        resp(tool("find_products", {"need_ids": ["n1", "n2", "n3"]}, "f1"), stop="tool_use"),
        resp(tool("choose_products", {"choices": [{"need_id": "n1", "product_id": MILK}, {"need_id": "n2", "product_id": EGGS},
                                                  {"need_id": "n3", "product_id": BREAD}]}, "c1"), stop="tool_use"),
        resp(text(final_reply)),
    ]


def test_plan_cards_totals_and_reply_agree(repo, scope):
    # 2 people x 7 days: milk 3.5 L -> 4 x 1 L; eggs 8 -> 1 dozen; bread 600 g -> 1 loaf
    total = 295 * 4 + 390 + 190
    client = FakeClient(breakfast_script(f"Here's a week of breakfast for two. Total Rs {total:,}."))
    agent = Agent(repo, client=client)
    r = agent.handle(scope, "s1", "do logon ke liye hafte ka nashta")
    plan = next(c for c in r.cards if c["type"] == "plan")
    assert [(l["product_id"], l["packs"]) for l in plan["lines"]] == [(MILK, 4), (EGGS, 1), (BREAD, 1)]
    assert plan["total"] == total
    assert r.grounding == {"issues": []}
    assert r.basket["items"] == []          # a plan is not a basket change
    assert r.steps[0] == "updated the shopping list"


def test_wrong_amount_in_reply_is_corrected_before_the_customer_sees_it(repo, scope):
    client = FakeClient(breakfast_script("Total Rs 1,500.") + [resp(text("Total Rs 1,760."))])
    r = Agent(repo, client=client).handle(scope, "s1", "breakfast for 2 for a week")
    assert r.reply == "Total Rs 1,760."
    assert r.grounding["corrected"] and "Rs 1,500" in r.grounding["corrected"][0]
    assert "[Store check" in client.calls[-1]["messages"][-1]["content"]


def test_basket_claim_without_basket_change_is_caught(repo, scope):
    client = FakeClient(breakfast_script("I've added everything to your basket!") + [resp(text("Want me to add these to your basket?"))])
    r = Agent(repo, client=client).handle(scope, "s1", "breakfast for 2 for a week")
    assert r.reply.startswith("Want me to add") and r.grounding["issues"] == []


def test_basket_changes_only_on_request_and_next_turn_sees_state(repo, scope):
    agent = Agent(repo, client=FakeClient(breakfast_script("Total Rs 1,760. Add to basket?")))
    agent.handle(scope, "s1", "breakfast for 2 for a week")

    agent.client = FakeClient([
        resp(tool("update_basket", {"from_plan": True}, "b1"), stop="tool_use"),
        resp(text("Done, I've added all 3 items to your basket. Total Rs 1,760.")),
    ])
    r = agent.handle(scope, "s1", "haan sab daal do")
    assert r.grounding == {"issues": []}
    assert r.basket["revision"] == 1 and r.basket["total"] == 1760
    assert any(c["type"] == "basket" for c in r.cards)
    sent = agent.client.calls[0]["messages"]
    # previous turn is plain text; the new message is followed by the authoritative state
    assert sent[0] == {"role": "user", "content": "breakfast for 2 for a week"}
    assert sent[1]["role"] == "assistant" and isinstance(sent[1]["content"], str)
    assert sent[2] == {"role": "user", "content": "haan sab daal do"}
    assert sent[3]["role"] == "system" and '"plan_total": 1760' in sent[3]["content"]


def test_card_buttons_are_reported_to_the_model(repo, scope):
    agent = Agent(repo, client=FakeClient(breakfast_script("Total Rs 1,760.")))
    agent.handle(scope, "s1", "breakfast for 2 for a week")
    B.apply(repo, scope, "s1", [B.Op("add", EGGS, 1)], expected_revision=0, idempotency_key="click-0001")
    agent.client = FakeClient([resp(text("You have one dozen eggs in your basket."))])
    agent.handle(scope, "s1", "kya hai basket mein?")
    state = agent.client.calls[0]["messages"][-1]["content"]
    assert "card buttons" in state and "Farm Fresh Eggs" in state


def test_options_are_numbered_and_remembered_for_references(repo, scope):
    client = FakeClient([
        resp(tool("update_needs", {"needs": [{"label": "Cooking oil", "kinds": ["oils.cooking_oil"]}]}, "u1"), stop="tool_use"),
        resp(tool("find_products", {"need_ids": ["n1"]}, "f1"), stop="tool_use"),
        resp(tool("show", {"type": "options", "need_ids": ["n1"]}, "s1"), stop="tool_use"),
        resp(text("Here are the oils we have.")),
    ])
    agent = Agent(repo, client=client)
    r = agent.handle(scope, "s1", "oil chahiye")
    opts = r.cards[0]["groups"][0]["options"]
    assert [o["ref"] for o in opts] == list(range(1, len(opts) + 1))
    agent.client = FakeClient([resp(text("Okay."))])
    agent.handle(scope, "s1", "doosra wala")
    assert '"ref": 2' in agent.client.calls[0]["messages"][-1]["content"]


def test_refusal_and_tool_errors_are_handled(repo, scope):
    client = FakeClient([
        resp(tool("update_needs", {"needs": [{"label": "Something", "kinds": ["nonsense.kind"]}]}, "u1"), stop="tool_use"),
        resp(stop="refusal"),
    ])
    r = Agent(repo, client=client).handle(scope, "s1", "...")
    tool_result = client.calls[1]["messages"][-1]["content"][0]
    assert "Unknown kinds" in tool_result["content"] and "closest valid" in tool_result["content"]
    assert r.reply.startswith("Sorry, I can't help")


def test_request_uses_fallbacks_and_cached_system_prompt(repo, scope):
    client = FakeClient([resp(text("Hi! What do you need today?"))])
    Agent(repo, client=client).handle(scope, "s1", "salam")
    call = client.calls[0]
    assert call["model"] == "claude-opus-5-5" and call["fallbacks"] == "default"
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "Demo Mart" in call["system"][0]["text"] and "produce.potato" in call["system"][0]["text"]
