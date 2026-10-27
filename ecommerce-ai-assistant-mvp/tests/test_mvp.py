import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agent import Assistant  # noqa: E402
from app.catalog import Catalog  # noqa: E402
from app.shop import Shop  # noqa: E402


@pytest.fixture
def shop(tmp_path):
    return Shop(Catalog(), orders_path=tmp_path / "orders.json")


def test_dataset_has_200_products_with_pictures():
    products = json.loads((ROOT / "data" / "products.json").read_text())
    assert len(products) == 200 and len({p["id"] for p in products}) == 200
    import xml.dom.minidom
    for p in products:
        assert p["name"] and p["description"] and p["price"] > 0 and p["size"]
        xml.dom.minidom.parse(str(ROOT / "data" / p["image"].lstrip("/")))  # every picture is a valid SVG


def test_vector_search_handles_meaning_typos_and_filters(shop):
    c = shop.catalog
    names = lambda r: [p["name"] for p in r["results"]]
    assert names(c.search("choclate"))[0].lower().find("chocolate") >= 0
    assert names(c.search("yoghurt"))[0].endswith(("Yogurt Plain", "Yogurt Cups"))
    snacks = c.search("snacks", max_price=10, dietary=["gluten-free"])["results"]
    assert snacks and all(p["price"] <= 10 and "gluten-free" in p["dietary"] for p in snacks)
    nut_free = c.search("snack", exclude_allergens=["nuts"])["results"]
    assert all(not {"tree-nuts", "peanuts"} & set(p["allergens"]) for p in nut_free)
    r = c.search("raspberries")
    assert [p["name"] for p in r["out_of_stock"]] == ["Raspberries"] and "Strawberries" in names(r)


@pytest.mark.parametrize("budget,people", [(50, 1), (100, 4), (30, 2), (15, 1)])
def test_budget_cart_never_goes_over(shop, budget, people):
    plan = shop.plan_budget(budget, people)
    assert plan["items"] and plan["total"] <= budget
    assert plan["total"] == round(sum(i["line_total"] for i in plan["items"]), 2)
    assert plan["remaining"] == round(budget - plan["total"], 2)


def test_budget_cart_respects_diet(shop):
    plan = shop.plan_budget(50, dietary=["vegan"])
    assert all("vegan" in shop.catalog.by_id[i["id"]]["dietary"] for i in plan["items"])


def test_recipe_kit_scales_and_skips_pantry(shop):
    kit = shop.recipe_kit("chicken pasta", 4, [
        {"name": "pasta", "search": "pasta", "packs": 1}, {"name": "chicken breast", "search": "chicken breast", "packs": 2},
        {"name": "heavy cream", "packs": 1}, {"name": "parmesan"}, {"name": "salt"}, {"name": "dragon fruit"}],
        have_at_home=["salt"])
    got = {i["for"]: (i["name"], i["quantity"]) for i in kit["items"]}
    assert got["chicken breast"][1] == 2 and "Cream" in got["heavy cream"][0] and "Parmesan" in got["parmesan"][0]
    assert kit["already_have"] == ["salt"] and kit["total"] == round(sum(i["line_total"] for i in kit["items"]), 2)


def test_cart_stock_and_checkout(shop):
    shop.add("s1", "DAI-001", 2)
    with pytest.raises(ValueError):
        shop.add("s1", "FRU-015")  # raspberries: out of stock
    assert shop.cart("s1")["total"] == 8.0
    with pytest.raises(ValueError):
        shop.checkout("s1", "", "", "card")
    order = shop.checkout("s1", "Sara", "12 Main St", "card")
    assert order["total"] == 8.0 and order["demo"] and shop.cart("s1")["items"] == []


class FakeGroq:
    """Plays the AI model: returns scripted tool calls, records requests."""

    def __init__(self, steps):
        self.steps, self.requests = list(steps), []

    def __call__(self, url, headers=None, json=None, timeout=None):
        self.requests.append(json)
        step = self.steps.pop(0)

        class R:
            status_code, headers, text = 200, {}, ""

            @staticmethod
            def json():
                return {"choices": [{"message": step}]}
        return R()


def call(name, args, i="c1"):
    return {"role": "assistant", "content": None, "tool_calls": [{"id": i, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


def test_assistant_budget_turn_and_follow_up(shop, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test")
    fake = FakeGroq([call("plan_budget_cart", {"budget": 50}), {"role": "assistant", "content": "Here's a week of groceries for $50."},
                     call("search_products", {"query": "snacks", "max_price": 10, "dietary": ["gluten-free"]}),
                     {"role": "assistant", "content": "Here are gluten-free snacks."},
                     call("add_to_cart", {"items": [{"product_id": "SNK-001", "quantity": 2}]}), {"role": "assistant", "content": "Added."}])
    monkeypatch.setattr("app.agent.requests.post", fake)
    a = Assistant(shop.catalog, shop)
    r = a.chat("s1", "I have $50. Suggest groceries for the week.")
    bundle = r["cards"][0]
    assert bundle["type"] == "bundle" and bundle["total"] <= 50 and r["cart"]["items"] == []   # a plan is not the cart
    r = a.chat("s1", "Show me gluten-free snacks under $10.")
    assert r["cards"][0]["type"] == "products" and all(p["price"] <= 10 for p in r["cards"][0]["items"])
    r = a.chat("s1", "add the pretzels, 2 please")
    assert r["cart"]["items"][0]["name"] == "Gluten-Free Pretzels" and r["cart"]["total"] == 8.58
    # earlier products are remembered for follow-ups
    sent = [m.get("content") or "" for m in fake.requests[-1]["messages"]]
    assert any("[Products shown:" in m and "SNK-001" in m for m in sent)


def test_assistant_reports_missing_key(shop, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    with pytest.raises(Exception, match="GROQ_API_KEY"):
        Assistant(shop.catalog, shop).chat("s1", "hi")
