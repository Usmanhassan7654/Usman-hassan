from conftest import CSV
from sauda import ingest
from sauda.text import classify, parse_pack, packs_needed


def test_traps_classify_to_distinct_kinds():
    assert classify("Olpers Full Cream Milk 1 Litre", "Dairy > Milk").kind == "dairy.milk"
    assert classify("Nutella Hazelnut Chocolate Spread 350g").kind == "breakfast.spread"
    assert classify("Nestle Milo Nutrition Powder 400g").kind == "bev.nutrition"
    assert classify("Nestle Nido Fortigrow Milk Powder 390g").kind == "dairy.milk_powder"
    assert classify("Olpers Chocolate Flavoured Milk 180ml").kind == "dairy.flavoured_milk"
    assert classify("Potatoes 1 kg", "Fruits & Vegetables").kind == "produce.potato"
    assert classify("Lays Classic Salted Potato Chips 70g").kind == "snacks.chips"
    assert classify("Super Crisp BBQ Potato Sticks 85g").kind == "snacks.chips"
    assert classify("Shan Biryani Masala 50g").kind == "spices.biryani_masala"
    assert classify("Shan Chaat Masala 100g").kind == "spices.chaat_masala"
    assert classify("National Chaat & Fries Masala 100g").kind == "spices.chaat_masala"
    assert classify("Eid Gift Hamper Deluxe").kind == "unknown"


def test_roman_urdu_and_urdu_names():
    assert classify("Doodh 1 litre").kind == "dairy.milk"
    assert classify("Desi Anday 12 pcs").kind == "dairy.eggs"
    assert classify("Chakki Aata 5kg").kind == "staples.flour"
    assert classify("چینی 1 کلو").kind == "staples.sugar"


def test_pack_parsing_and_quantities():
    assert parse_pack("6 x 1.5 L").amount == 9000
    assert parse_pack("1 Dozen").amount == 12
    assert parse_pack("", "Lifebuoy Soap 115g").amount == 115
    assert packs_needed(2.5, "kg", parse_pack("1 kg")) == 3
    assert packs_needed(2, "kg", parse_pack("1 L")) is None  # units don't line up


def test_sync_is_idempotent_and_unpublishes_removed(repo, scope):
    stats = repo.catalog_stats(scope)
    assert stats["published_products"] == 143 and stats["unclassified"] == 1
    assert ingest.sync(repo, scope, CSV)["unchanged"] == 143
    smaller = [r for r in ingest.read_source(CSV) if r["sku"] != "VEG-001"]
    res = ingest.sync(repo, scope, CSV, rows=smaller)
    assert res["unpublished"] == 1
    assert repo.products_by_ids(scope, ["demo-mart:VEG-001"])["demo-mart:VEG-001"]["published"] == 0


def test_invalid_rows_are_counted_not_imported(repo, scope):
    res = ingest.sync(repo, scope, "inline", rows=[{"sku": "X1", "name": "No price"}, {"name": "No sku", "price": 10}])
    assert res["invalid"] == 2 and res["written"] == 0
