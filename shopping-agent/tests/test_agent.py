"""Agent loop tests with a scripted fake Claude client (no network)."""

import json
from types import SimpleNamespace as NS

import pytest

from shopping_agent.agent import ShoppingAgent, ShoppingSession, ToolError
from shopping_agent.cart import OrderStore


def text(t):
    return NS(type="text", text=t)


def tool(name, args, id_):
    return NS(type="tool_use", name=name, input=args, id=id_)


def resp(*blocks, stop="end_turn"):
    return NS(content=list(blocks), stop_reason=stop)


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.responses.pop(0)


def test_full_shopping_flow(catalog, tmp_path):
    orders = OrderStore(tmp_path / "orders.jsonl")
    client = FakeClient([
        # Turn 1: understand intent, search, fill cart.
        resp(tool("save_preferences", {"budget": 20, "household_size": 2}, "t1"),
             tool("search_products", {"query": "eggs"}, "t2"),
             tool("search_products", {"query": "bread"}, "t3"), stop="tool_use"),
        resp(tool("add_to_cart", {"items": [{"product_id": "DAI-004", "quantity": 1},
                                            {"product_id": "BAK-001", "quantity": 2}]}, "t4"), stop="tool_use"),
        resp(text("Added eggs and 2 loaves. Total 6.67.")),
        # Turn 2: checkout details -> summary.
        resp(tool("prepare_checkout", {"customer_name": "Sam", "delivery_address": "1 High St",
                                       "payment_method": "cash_on_delivery"}, "t5"), stop="tool_use"),
        # Model tries to place the order in the same turn: must be blocked.
        resp(tool("place_order", {}, "t6"), stop="tool_use"),
        resp(text("Here is your summary. Shall I place the order?")),
        # Turn 3: user confirms.
        resp(tool("place_order", {}, "t7"), stop="tool_use"),
        resp(text("Order placed!")),
    ])
    agent = ShoppingAgent(catalog, client=client, orders=orders)
    events = []
    on_event = lambda kind, data: events.append((kind, data))

    assert "Added eggs" in agent.chat("breakfast basics for 2, budget $20", on_event)
    view = agent.session.cart_view()
    assert view["total"] == pytest.approx(3.49 + 2 * 1.59)
    assert view["remaining_budget"] == pytest.approx(20 - view["total"])

    agent.chat("Sam, 1 High St, cash please", on_event)
    assert ("tool_error", {"name": "place_order",
            "error": "The customer has not confirmed the summary yet. Show it and wait for their reply."}) in events
    assert not (tmp_path / "orders.jsonl").exists()

    assert agent.chat("yes, place it", on_event) == "Order placed!"
    order = json.loads((tmp_path / "orders.jsonl").read_text().splitlines()[0])
    assert order["customer"]["customer_name"] == "Sam"
    assert order["item_count"] == 3
    assert agent.session.cart.item_count == 0
    assert catalog.get("DAI-004").stock == 89

    # Tool results for parallel calls go back in one user message, matched by id.
    second_call_msgs = client.calls[1]["messages"]
    results = second_call_msgs[-1]["content"]
    assert [r["tool_use_id"] for r in results] == ["t1", "t2", "t3"]
    assert client.calls[0]["model"] == "claude-opus-5-5"


def test_cart_change_invalidates_checkout(catalog, tmp_path):
    s = ShoppingSession(catalog=catalog, orders=OrderStore(tmp_path / "o.jsonl"))
    s.turn = 1
    s.tool_add_to_cart([{"product_id": "FRU-001", "quantity": 2}])
    s.tool_prepare_checkout("A", "B", "card_on_delivery")
    s.tool_add_to_cart([{"product_id": "FRU-002", "quantity": 1}])
    s.turn = 2
    with pytest.raises(ToolError, match="No checkout prepared"):
        s.tool_place_order()


def test_add_to_cart_reports_bad_items(catalog, tmp_path):
    s = ShoppingSession(catalog=catalog, orders=OrderStore(tmp_path / "o.jsonl"))
    out = s.tool_add_to_cart([{"product_id": "NOPE", "quantity": 1},
                              {"product_id": "SNK-007", "quantity": 1},
                              {"product_id": "MEA-004", "quantity": 99}])
    assert out["added"] == []
    assert len(out["errors"]) == 3


def test_search_falls_back_without_filters(catalog, tmp_path):
    s = ShoppingSession(catalog=catalog, orders=OrderStore(tmp_path / "o.jsonl"))
    out = s.tool_search_products("salmon", tags=["vegan"])
    assert out["results"] == []
    assert out["unfiltered_results"][0]["name"] == "Salmon Fillets"


def test_refusal_returns_message(catalog, tmp_path):
    client = FakeClient([resp(stop="refusal")])
    agent = ShoppingAgent(catalog, client=client, orders=OrderStore(tmp_path / "o.jsonl"))
    assert "can't help" in agent.chat("something bad")
