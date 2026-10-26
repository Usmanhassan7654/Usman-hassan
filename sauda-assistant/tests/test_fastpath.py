"""Clear product lists and 'yes, add them' are handled without any model call."""

import pytest

from sauda import retrieval as R
from sauda.agent import Agent
from sauda.fastpath import parse_list
from sauda.ledger import Ledger, Need
from sauda.tools import Turn
from conftest import FakeClient


@pytest.fixture
def turn(repo, scope):
    return Turn(repo, scope, "s1", Ledger())


def kinds(items):
    return [(i.kind, i.quantity, i.brands) for i in items]


def test_plain_lists_are_understood(turn):
    assert kinds(parse_list(turn, "doodh aur double roti")) == [("dairy.milk", None, []), ("bakery.bread", None, [])]
    assert kinds(parse_list(turn, "2 kg aloo, 1 kg pyaz")) == [("produce.potato", {"amount": 2.0, "unit": "kg"}, []),
                                                              ("produce.onion", {"amount": 1.0, "unit": "kg"}, [])]
    assert kinds(parse_list(turn, "eggs, bread and milk")) == [("dairy.eggs", None, []), ("bakery.bread", None, []), ("dairy.milk", None, [])]
    assert kinds(parse_list(turn, "چینی اور چائے")) == [("staples.sugar", None, []), ("bev.tea", None, [])]
    assert kinds(parse_list(turn, "mujhe olpers doodh chahiye")) == [("dairy.milk", None, ["Olpers"])]
    assert kinds(parse_list(turn, "1 darjan anday")) == [("dairy.eggs", {"amount": 1.0, "unit": "dozen"}, [])]


@pytest.mark.parametrize("message", [
    "chicken biryani ka saman", "budget 5000 mein doodh", "doodh kitne ka hai?", "Olpers nahi", "aadha kilo aloo",
    "doodh aur kuch meetha", "hafte ka sauda", "matar", "haan", "basket mein daal do", "salam", "chai ke liye doodh",
])
def test_anything_more_goes_to_the_model(turn, message):
    assert parse_list(turn, message) is None


def test_broad_kinds_require_the_named_product(repo, scope):
    peas = R.search(repo, scope, Need("n1", "Peas", ["produce.vegetables"], ["peas"]))
    assert peas.status == R.NONE_ELIGIBLE and peas.rejected["out_of_stock"] == 1   # never cauliflower instead
    assert [c.name for c in R.search(repo, scope, Need("n2", "Okra", ["produce.vegetables"], ["okra"])).candidates] == ["Okra Bhindi 500g"]


def test_list_then_yes_needs_no_model_at_all(repo, scope):
    agent = Agent(repo, client=FakeClient([]), fast_path=True)   # any model call would fail the test
    r = agent.handle(scope, "s1", "cheeni aur 2 kg aloo")
    assert r.usage["model_calls"] == 0 and r.usage["fast_path"]
    plan = next(c for c in r.cards if c["type"] == "plan")
    assert [(l["name"], l["packs"]) for l in plan["lines"]] == [("White Sugar 1 kg", 1), ("Potatoes 1 kg", 2)]   # 1 kg, not the 5 kg bag
    assert r.reply.startswith("Ye mil gaya:") and "Rs 395" in r.reply and r.reply.endswith("Basket mein daal doon?")
    assert r.grounding == {"issues": []} and r.basket["items"] == []

    r2 = agent.handle(scope, "s1", "haan daal do")
    assert r2.usage["model_calls"] == 0 and r2.basket["total"] == 395 and len(r2.basket["items"]) == 2
    assert "Rs 395" in r2.reply and r2.grounding == {"issues": []}


def test_urdu_and_english_replies(repo, scope):
    agent = Agent(repo, client=FakeClient([]), fast_path=True)
    assert agent.handle(scope, "u1", "چینی اور چائے").reply.startswith("یہ مل گیا")
    assert agent.handle(scope, "e1", "milk and eggs").reply.endswith("Shall I add these to your basket?")


def test_yes_without_a_pending_question_goes_to_the_model(repo, scope):
    client = FakeClient([__import__("conftest").resp(__import__("conftest").text("What would you like to add?"))])
    r = Agent(repo, client=client, fast_path=True).handle(scope, "s1", "haan")
    assert r.usage["model_calls"] == 1
