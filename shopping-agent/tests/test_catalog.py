import json

from shopping_agent.catalog import Product, load_csv_text, load_json_data
from shopping_agent.scraper import extract_jsonld_products


def test_sample_catalog_loads(catalog):
    assert len(catalog) > 90
    assert "Dairy & Eggs" in catalog.categories()


def test_search_finds_by_name_and_plural(catalog):
    names = [p.name for p in catalog.search("eggs")]
    assert names[0] == "Free-Range Eggs"
    assert catalog.search("banana")[0].name == "Bananas"


def test_search_synonyms(catalog):
    assert any("Mince" in p.name for p in catalog.search("ground beef"))
    assert any("Washing Up" in p.name for p in catalog.search("dish soap"))
    assert any("Crisps" in p.name for p in catalog.search("chips"))


def test_search_filters(catalog):
    vegan_milk = catalog.search("milk", tags=["vegan"])
    assert "Oat Milk" in [p.name for p in vegan_milk]
    assert all("vegan" in p.tags for p in vegan_milk)
    cheap = catalog.search("pasta", max_price=1.5)
    assert cheap and all(p.price <= 1.5 for p in cheap)
    by_price = catalog.search("milk", sort="price_asc")
    assert [p.price for p in by_price] == sorted(p.price for p in by_price)


def test_out_of_stock_hidden_by_default(catalog):
    assert not catalog.search("popcorn")
    assert catalog.search("popcorn", in_stock_only=False)


def test_csv_with_aliases_and_semicolons():
    text = "Title;Variant Price;Product Type;Inventory\nRed Apple;$1,50;Fruit;3\nNo price;;Fruit;1\n"
    cat = load_csv_text(text)
    assert len(cat) == 1
    p = next(iter(cat.products.values()))
    assert (p.name, p.price, p.category, p.stock) == ("Red Apple", 1.5, "Fruit", 3)


def test_shopify_json_variants():
    data = {"products": [{
        "title": "Coffee", "product_type": "Drinks", "vendor": "Acme", "tags": ["organic"],
        "handle": "coffee", "body_html": "<p>Nice <b>beans</b></p>",
        "variants": [
            {"sku": "C-250", "title": "250g", "price": "5.00", "available": True},
            {"sku": "C-1K", "title": "1kg", "price": "15.00", "available": False},
        ],
    }]}
    cat = load_json_data(data)
    assert cat.get("C-250").name == "Coffee - 250g"
    assert cat.get("C-250").description == "Nice beans"
    assert not cat.get("C-1K").in_stock


def test_jsonld_extraction():
    ld = {"@context": "https://schema.org", "@graph": [{
        "@type": "Product", "name": "Olive Oil", "sku": "OO1", "brand": {"name": "Acme"},
        "offers": {"@type": "Offer", "price": "6.50", "priceCurrency": "EUR",
                   "availability": "https://schema.org/InStock"},
    }]}
    html = f'<html><script type="application/ld+json">{json.dumps(ld)}</script></html>'
    records = extract_jsonld_products(html, "https://shop.example/oil")
    p = Product.from_record(records[0])
    assert (p.id, p.name, p.price, p.currency, p.brand) == ("OO1", "Olive Oil", 6.5, "EUR", "Acme")
