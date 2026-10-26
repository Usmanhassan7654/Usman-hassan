"""The ten lessons from the brief, checked against the real catalog and code."""

from sauda import retrieval as R
from sauda.ledger import Constraints, Ledger, Need
from sauda.tools import Turn, choose_products, find_products, update_needs


def names(outcome):
    return [c.name for c in outcome.candidates]


def test_milk_never_matches_spread_powder_or_flavoured(repo, scope):
    out = R.search(repo, scope, Need("n1", "Milk", ["dairy.milk"], ["milk"]))
    assert out.status == R.FOUND
    assert names(out) and all("Milk" in n and "Spread" not in n and "Powder" not in n and "Flavoured" not in n for n in names(out))


def test_potato_never_matches_chips(repo, scope):
    out = R.search(repo, scope, Need("n1", "Aloo", ["produce.potato"], ["potato"]))
    assert names(out) == ["Potatoes 1 kg"]


def test_biryani_masala_never_silently_becomes_chaat_masala(repo, scope):
    out = R.search(repo, scope, Need("n1", "Biryani masala", ["spices.biryani_masala"], ["biryani"]))
    assert names(out) and all("Biryani" in n for n in names(out))
    assert "Shan Sindhi Biryani Masala 60g" not in names(out)  # out of stock
    assert out.rejected.get("out_of_stock") == 1


def test_missing_vs_out_of_stock_vs_constraints_are_distinct(repo, scope):
    assert R.search(repo, scope, Need("n1", "Diapers size 5", ["baby.diapers"], constraints=Constraints(must_terms=["size 5"]))).status == R.NONE_ELIGIBLE
    assert R.search(repo, scope, Need("n2", "Olive oil spray", ["oils.olive_oil"], constraints=Constraints(max_unit_price=100))).rejected == {"over_max_price": 1}
    # Peas exist but are out of stock -> none_eligible with an out_of_stock reason
    peas = R.search(repo, scope, Need("n3", "Peas", ["produce.vegetables"], constraints=Constraints(must_terms=["peas"])))
    assert peas.status == R.NONE_ELIGIBLE and peas.rejected.get("out_of_stock") == 1


def test_not_in_catalog(repo, scope):
    from sauda import ingest
    small = repo.add_store("tiny-mart", "Tiny Mart", "tiny-1", "Hyderabad", api_key="tiny-key")
    ingest.sync(repo, small, "tiny-feed", rows=[{"sku": "S1", "name": "White Sugar 1 kg", "price": 150, "size": "1 kg"}])
    assert R.search(repo, small, Need("n1", "Milk", ["dairy.milk"])).status == R.NOT_IN_CATALOG
    assert R.search(repo, small, Need("n2", "Cheeni", ["staples.sugar"])).status == R.FOUND


def test_substitutes_only_when_allowed_and_flagged(repo, scope, tmp_path):
    need = Need("n1", "Cooking oil under 600", ["oils.cooking_oil"], constraints=Constraints(max_unit_price=580))
    assert R.search(repo, scope, need).status == R.NONE_ELIGIBLE
    need.allow_substitutes = True
    out = R.search(repo, scope, need)
    assert out.status == R.ONLY_SUBSTITUTES and out.candidates[0].name == "Dalda Banaspati Ghee 1 kg" and out.candidates[0].substitute


def test_correcting_one_need_preserves_the_others(repo, scope):
    turn = Turn(repo, scope, "s1", Ledger())
    update_needs(turn, {"needs": [{"label": "Milk", "kinds": ["dairy.milk"]}, {"label": "Rice", "kinds": ["staples.rice"]}]})
    find_products(turn, {"need_ids": ["n1", "n2"]})
    choose_products(turn, {"choices": [{"need_id": "n1", "product_id": "demo-mart:MLK-001"}, {"need_id": "n2", "product_id": "demo-mart:STP-008"}]})
    # "not Olpers" -> only the milk choice is dropped
    update_needs(turn, {"needs": [{"id": "n1", "constraints": {"exclude_brands": ["Olpers"]}}]})
    milk, rice = turn.ledger.get("n1"), turn.ledger.get("n2")
    assert milk.selection is None and "dropped choice" in milk.history[-1]
    assert all("MLK-001" not in c for c in milk.candidates)
    assert rice.selection["product_id"] == "demo-mart:STP-008"


def test_choose_rejects_unsuitable_product(repo, scope):
    turn = Turn(repo, scope, "s1", Ledger())
    update_needs(turn, {"needs": [{"label": "Milk", "kinds": ["dairy.milk"]}]})
    out = choose_products(turn, {"choices": [{"need_id": "n1", "product_id": "demo-mart:MLK-009"}]})  # Nutella
    assert out["errors"] and "wrong_kind" in out["errors"][0] and out["plan"] == []


def test_budget_words_are_not_needs_and_totals_are_computed(repo, scope):
    turn = Turn(repo, scope, "s1", Ledger())
    out = update_needs(turn, {"needs": [{"label": "Budget", "kinds": ["budget"]}], "budget": {"amount": 2000}, "household": {"people": 4, "days": 7}})
    assert out["errors"] and turn.ledger.active_needs() == []  # "budget" is not a product kind
    update_needs(turn, {"needs": [{"label": "Milk", "kinds": ["dairy.milk"]}, {"label": "Eggs", "kinds": ["dairy.eggs"]}]})
    found = find_products(turn, {"need_ids": ["n1", "n2"]})
    milk = found["results"][0]["options"][0]
    assert milk["suggested_packs"] == 7  # 1.75 L x 4 people / 1 L packs
    plan = choose_products(turn, {"choices": [{"need_id": "n1", "product_id": milk["product_id"]}, {"need_id": "n2", "product_id": "demo-mart:EGG-001"}]})
    expected = milk["price"] * 7 + 390 * 2  # 16 eggs -> 2 dozen
    assert plan["plan_total"] == expected
    assert plan["budgets"][0]["remaining"] == 2000 - expected and plan["budgets"][0]["over"] is (expected > 2000)
