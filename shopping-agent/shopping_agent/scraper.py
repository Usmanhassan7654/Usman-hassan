"""Load a product catalog from an e-commerce website URL.

Strategies are tried from most to least structured:

1. The URL itself is a CSV / JSON feed.
2. Shopify storefront:      <origin>/products.json
3. WooCommerce Store API:   <origin>/wp-json/wc/store/v1/products
4. schema.org Product JSON-LD on the page, then on linked product pages.

Only use this on sites whose terms allow automated access.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .catalog import Catalog, Product, load_csv_text, load_json_data

HEADERS = {"User-Agent": "ShoppingAssistantBot/1.0 (+catalog import)"}
TIMEOUT = 20


def _get(session: requests.Session, url: str) -> requests.Response | None:
    try:
        resp = session.get(url, headers=HEADERS, timeout=TIMEOUT)
    except requests.RequestException:
        return None
    return resp if resp.ok else None


def load_url(url: str, max_pages: int = 5, max_product_pages: int = 40) -> Catalog:
    session = requests.Session()
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"

    resp = _get(session, url)
    ctype = resp.headers.get("content-type", "") if resp is not None else ""

    # 1. Direct feeds.
    if resp is not None and ("csv" in ctype or url.lower().endswith(".csv")):
        return load_csv_text(resp.text, source=url)
    if resp is not None and ("json" in ctype or url.lower().endswith(".json")):
        try:
            catalog = load_json_data(resp.json(), source=url)
            if len(catalog):
                return catalog
        except ValueError:
            pass

    # 2. Shopify.
    catalog = _try_shopify(session, origin, max_pages)
    if len(catalog):
        return catalog

    # 3. WooCommerce.
    catalog = _try_woocommerce(session, origin, max_pages)
    if len(catalog):
        return catalog

    # 4. JSON-LD.
    if resp is not None:
        catalog = _from_jsonld_pages(session, url, resp.text, max_product_pages)
        if len(catalog):
            return catalog

    raise ValueError(
        f"Could not find products at {url}. Try a CSV/JSON export, a Shopify or "
        "WooCommerce store, or a page with schema.org Product markup."
    )


def _try_shopify(session: requests.Session, origin: str, max_pages: int) -> Catalog:
    items: list[dict] = []
    for page in range(1, max_pages + 1):
        resp = _get(session, f"{origin}/products.json?limit=250&page={page}")
        if resp is None:
            break
        try:
            batch = resp.json().get("products", [])
        except ValueError:
            break
        if not batch:
            break
        for item in batch:
            item["handle"] = f"{origin}/products/{item.get('handle', '')}"
        items.extend(batch)
    return load_json_data(items, source=f"{origin} (Shopify)") if items else Catalog()


def _try_woocommerce(session: requests.Session, origin: str, max_pages: int) -> Catalog:
    records: list[dict] = []
    for page in range(1, max_pages + 1):
        resp = _get(session, f"{origin}/wp-json/wc/store/v1/products?per_page=100&page={page}")
        if resp is None:
            break
        try:
            batch = resp.json()
        except ValueError:
            break
        if not isinstance(batch, list) or not batch:
            break
        for item in batch:
            prices = item.get("prices") or {}
            minor = int(prices.get("currency_minor_unit", 2) or 2)
            raw = prices.get("price")
            records.append({
                "id": item.get("sku") or item.get("id"),
                "name": item.get("name"),
                "price": int(raw) / 10**minor if raw not in (None, "") else None,
                "currency": prices.get("currency_code", "USD"),
                "category": ", ".join(c.get("name", "") for c in item.get("categories", [])),
                "description": item.get("short_description") or item.get("description"),
                "stock": 1 if item.get("is_in_stock", True) else 0,
                "tags": [t.get("name", "") for t in item.get("tags", [])],
                "url": item.get("permalink"),
                "image": (item.get("images") or [{}])[0].get("src", "") if item.get("images") else "",
            })
    return load_json_data(records, source=f"{origin} (WooCommerce)") if records else Catalog()


def extract_jsonld_products(html: str, base_url: str = "") -> list[dict]:
    """Return product records found in schema.org JSON-LD blocks."""
    soup = BeautifulSoup(html, "html.parser")
    found: list[dict] = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (ValueError, TypeError):
            continue
        for node in _walk(data):
            types = node.get("@type")
            types = types if isinstance(types, list) else [types]
            if "Product" not in types:
                continue
            offers = node.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            if offers.get("@type") == "AggregateOffer":
                price = offers.get("lowPrice") or offers.get("price")
            else:
                price = offers.get("price")
            availability = str(offers.get("availability", ""))
            brand = node.get("brand")
            if isinstance(brand, dict):
                brand = brand.get("name")
            image = node.get("image")
            if isinstance(image, list):
                image = image[0] if image else ""
            if isinstance(image, dict):
                image = image.get("url", "")
            found.append({
                "id": node.get("sku") or node.get("productID") or node.get("gtin13") or node.get("url"),
                "name": node.get("name"),
                "price": price,
                "currency": offers.get("priceCurrency", "USD"),
                "brand": brand,
                "category": node.get("category"),
                "description": node.get("description"),
                "stock": 0 if "OutOfStock" in availability else None,
                "url": urljoin(base_url, node.get("url") or offers.get("url") or base_url),
                "image": image,
            })
    return found


def _walk(data):
    if isinstance(data, list):
        for item in data:
            yield from _walk(item)
    elif isinstance(data, dict):
        yield data
        for key in ("@graph", "itemListElement", "item", "mainEntity"):
            if key in data:
                yield from _walk(data[key])


def _from_jsonld_pages(session: requests.Session, url: str, html: str, max_product_pages: int) -> Catalog:
    records = extract_jsonld_products(html, url)
    if not records:
        # Listing page without markup: follow links that look like product pages.
        soup = BeautifulSoup(html, "html.parser")
        host = urlparse(url).netloc
        links = []
        for a in soup.find_all("a", href=True):
            href = urljoin(url, a["href"]).split("#")[0]
            if urlparse(href).netloc == host and re.search(r"/(product|products|p|item|dp)/", href):
                if href not in links:
                    links.append(href)
        for link in links[:max_product_pages]:
            page = _get(session, link)
            if page is not None:
                records.extend(extract_jsonld_products(page.text, link))
    catalog = Catalog(source=f"{url} (JSON-LD)")
    for i, rec in enumerate(records):
        product = Product.from_record(rec, i)
        if product:
            catalog.add(product)
    return catalog
