import pytest

from sauda import basket as B
from sauda import ingest
from conftest import CSV


def test_revisions_reject_stale_writes_and_dedupe_keys(repo, scope):
    r1 = B.apply(repo, scope, "s1", [B.Op("add", "demo-mart:MLK-001", 2)], expected_revision=0, idempotency_key="k-0000001")
    assert r1["basket"]["revision"] == 1 and r1["basket"]["total"] == 660
    dup = B.apply(repo, scope, "s1", [B.Op("add", "demo-mart:MLK-001", 2)], expected_revision=0, idempotency_key="k-0000001")
    assert dup["duplicate"] and dup["basket"]["items"][0]["quantity"] == 2
    with pytest.raises(B.StaleRevision) as e:
        B.apply(repo, scope, "s1", [B.Op("remove", "demo-mart:MLK-001")], expected_revision=0, idempotency_key="k-0000002")
    assert e.value.basket["revision"] == 1  # the client gets the truth back


def test_stock_and_availability_are_enforced(repo, scope):
    r = B.apply(repo, scope, "s1", [B.Op("add", "demo-mart:MLK-005", 1), B.Op("set", "demo-mart:MEA-004", 99)], None)
    assert r["changes"] == [] and len(r["errors"]) == 2


def test_basket_view_reprices_and_flags_removed_products(repo, scope):
    B.apply(repo, scope, "s1", [B.Op("add", "demo-mart:VEG-001", 1), B.Op("add", "demo-mart:STP-010", 1)], None)
    rows = [r for r in ingest.read_source(CSV) if r["sku"] != "VEG-001"]
    for r in rows:
        if r["sku"] == "STP-010":
            r["price"] = "165"
    ingest.sync(repo, scope, CSV, rows=rows)
    v = B.view(repo, scope, "s1")
    assert v["total"] == 165 and v["problems"][0]["issue"] == "no longer available"


def test_two_retailers_are_isolated(repo, scope):
    other = repo.add_store("other-mart", "Other Mart", "other-lhr", "Lahore", api_key="other-key")
    ingest.sync(repo, other, "other-feed", rows=[{"sku": "MLK-001", "name": "Other Milk 1 L", "price": 999, "size": "1 L", "category": "Milk"}])
    assert repo.scope_for_key("other-key") == other
    mine = {r["name"] for r in repo.products_by_kinds(scope, ["dairy.milk"])}
    theirs = {r["name"] for r in repo.products_by_kinds(other, ["dairy.milk"])}
    assert "Other Milk 1 L" not in mine and theirs == {"Other Milk 1 L"}
    # a product id from another retailer is unknown here
    r = B.apply(repo, scope, "s1", [B.Op("add", "other-mart:MLK-001", 1)], None)
    assert r["errors"] == ["Unknown product other-mart:MLK-001."]
    # sessions with the same id don't collide across stores
    B.apply(repo, other, "s1", [B.Op("add", "other-mart:MLK-001", 1)], None)
    assert B.view(repo, scope, "s1")["items"] == []
