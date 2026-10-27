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


def test_budget_respects_brand_preferences(shop):
    plain = {i["name"] for i in shop.plan_budget(60)["items"]}
    liked = shop.plan_budget(60, prefer_brands=["Harvest Farm"])
    brands = {shop.catalog.by_id[i["id"]]["brand"] for i in liked["items"]}
    assert "Harvest Farm" in brands and liked["total"] <= 60
    avoided = shop.plan_budget(60, avoid_brands=["Green Valley", "Harvest Farm"])
    assert not {"Green Valley", "Harvest Farm"} & {shop.catalog.by_id[i["id"]]["brand"] for i in avoided["items"]}
    assert plain  # the default plan still works


def test_recipe_packs_are_calculated_from_servings(shop):
    from app.shop import packs_for, pack_size
    assert pack_size("4 x 5.3 oz") == (601.02, "g") and pack_size("1 gal") == (3785.0, "ml")
    assert packs_for(600, "g", "300 g") == 2 and packs_for(1, "lb", "500 g") == 1 and packs_for(6, "eggs", "12 ct") == 1
    kit = shop.recipe_kit("chicken pasta", 4, [
        {"name": "chicken breast", "search": "chicken breast fillets", "amount_per_serving": 150, "unit": "g"},
        {"name": "pasta", "search": "artisan pasta", "amount_per_serving": 100, "unit": "g"},
        {"name": "heavy cream", "amount_per_serving": 60, "unit": "ml"}])
    got = {i["for"]: (i["quantity"], i["needed"]) for i in kit["items"]}
    assert got == {"chicken breast": (2, "600 g"), "pasta": (1, "400 g"), "heavy cream": (1, "240 ml")}
    bigger = shop.recipe_kit("chicken pasta", 8, [{"name": "chicken breast", "search": "chicken breast fillets", "amount_per_serving": 150, "unit": "g"}])
    assert bigger["items"][0]["quantity"] == 4   # double the servings, double the packs


def test_pantry_staples_are_asked_about_not_added(shop):
    ings = [{"name": "spaghetti"}, {"name": "salt"}, {"name": "olive oil"}, {"name": "black pepper"}, {"name": "garlic"}]
    kit = shop.recipe_kit("aglio e olio", 2, ings)
    assert [i["for"] for i in kit["items"]] == ["spaghetti", "garlic"]
    assert [i["for"] for i in kit["pantry_check"]] == ["salt", "olive oil", "black pepper"]
    assert kit["total"] == round(sum(i["line_total"] for i in kit["items"]), 2)   # pantry items are not in the total
    assert [i["for"] for i in shop.recipe_kit("aglio e olio", 2, ings, include_pantry=True)["items"]] == ["spaghetti", "salt", "olive oil", "black pepper", "garlic"]
    assert shop.recipe_kit("aglio e olio", 2, ings, have_at_home=["salt", "olive oil"])["already_have"] == ["salt", "olive oil"]


def test_meaning_search_with_embeddings_and_safe_fallback(monkeypatch):
    import numpy as np
    from app import catalog as C

    class FakeEmbedder:  # stands in for the downloaded model: "breakfast" is close to oats, muffins, eggs
        def embed(self, texts):
            for t in texts:
                t = t.lower()
                yield np.array([1.0 if any(w in t for w in ("breakfast", "oat", "muffin", "egg", "cereal")) else 0.0, 1.0], dtype=np.float32)

    c = C.Catalog()
    plain = [p["name"] for p in c.search("morning meal ideas")["results"]]
    c.embedder = FakeEmbedder()
    c.dense = np.array(list(c.embedder.embed([c._doc(p) for p in c.products])), dtype=np.float32)
    c.dense /= np.linalg.norm(c.dense, axis=1, keepdims=True)
    with_meaning = [p["name"] for p in c.search("breakfast")["results"]]
    assert c.mode.endswith("AI embeddings") and any(w in " ".join(with_meaning) for w in ("Oat", "Muffin", "Egg"))
    assert isinstance(plain, list)
    # a model that can't load (no internet on first start) falls back to word + character vectors
    import fastembed

    def no_internet(*a, **k):
        raise ConnectionError("no internet")
    monkeypatch.setattr(fastembed, "TextEmbedding", no_internet)
    monkeypatch.setenv("USE_EMBEDDINGS", "1")
    fallback = C.Catalog()
    assert fallback.mode == "word + character vectors" and fallback.search("milk")["results"]
