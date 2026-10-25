"""Product catalog: a normalized product model, loaders and search.

Products can come from a CSV file, a JSON file, or an e-commerce website URL.
Every source is normalized into the same `Product` shape so the agent never
has to care where the data came from.
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

# Column / key aliases seen in real-world exports (Shopify, WooCommerce,
# Google Merchant feeds, hand-made spreadsheets).
FIELD_ALIASES = {
    "id": ["id", "sku", "product_id", "item_id", "handle", "variant_sku", "code"],
    "name": ["name", "title", "product_name", "product", "item", "item_name"],
    "price": ["price", "sale_price", "unit_price", "variant_price", "cost", "amount"],
    "category": ["category", "categories", "product_type", "type", "department", "aisle"],
    "brand": ["brand", "vendor", "manufacturer"],
    "description": ["description", "body", "body_html", "details", "summary", "short_description"],
    "unit": ["unit", "size", "weight", "pack_size", "quantity_unit"],
    "stock": ["stock", "inventory", "qty", "quantity", "inventory_quantity", "stock_quantity"],
    "tags": ["tags", "labels", "keywords", "dietary"],
    "url": ["url", "link", "product_url"],
    "image": ["image", "image_url", "image_link", "image_src"],
    "currency": ["currency", "price_currency"],
}

SYNONYMS = {
    "soda": ["cola", "soft drink", "fizzy"],
    "pop": ["soda", "cola"],
    "veggie": ["vegetable"],
    "veggies": ["vegetable"],
    "fruit": ["fruits"],
    "pasta": ["spaghetti", "penne", "macaroni"],
    "noodle": ["pasta"],
    "chips": ["crisps"],
    "crisps": ["chips"],
    "mince": ["ground"],
    "ground": ["mince"],
    "yoghurt": ["yogurt"],
    "yogurt": ["yoghurt"],
    "loo": ["toilet"],
    "nappy": ["diaper"],
    "diaper": ["nappy"],
    "detergent": ["laundry", "washing"],
    "aubergine": ["eggplant"],
    "eggplant": ["aubergine"],
    "coriander": ["cilantro"],
    "cilantro": ["coriander"],
}

STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "for", "with", "some", "any", "i",
    "need", "want", "buy", "get", "me", "my", "to", "please", "pack", "of",
}


def _tokens(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    out = []
    for w in words:
        if w in STOPWORDS:
            continue
        out.append(_singular(w))
    return out


def _singular(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith(("oes", "ches", "shes", "xes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _parse_price(value) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"\d+(?:[.,]\d{3})*(?:[.,]\d+)?", str(value))
    if not match:
        return None
    number = match.group(0)
    # "1,299.50" -> 1299.50 ; "12,50" -> 12.50
    if "," in number and "." in number:
        number = number.replace(",", "")
    elif "," in number:
        head, _, tail = number.rpartition(",")
        number = f"{head.replace(',', '')}.{tail}" if len(tail) != 3 else number.replace(",", "")
    try:
        return float(number)
    except ValueError:
        return None


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", text).strip()


@dataclass
class Product:
    id: str
    name: str
    price: float
    category: str = ""
    brand: str = ""
    description: str = ""
    unit: str = ""
    stock: int | None = None
    tags: list[str] = field(default_factory=list)
    url: str = ""
    image: str = ""
    currency: str = "USD"

    @property
    def in_stock(self) -> bool:
        return self.stock is None or self.stock > 0

    def to_dict(self, compact: bool = False) -> dict:
        data = asdict(self)
        data["in_stock"] = self.in_stock
        if compact:
            for key in ("description", "image", "url"):
                data.pop(key, None)
            data = {k: v for k, v in data.items() if v not in ("", [], None)}
        return data

    @classmethod
    def from_record(cls, record: dict, index: int = 0) -> "Product | None":
        """Build a product from an arbitrary dict using FIELD_ALIASES."""
        lowered = {re.sub(r"[\s-]+", "_", str(k).strip().lower()): v for k, v in record.items()}

        def pick(key: str):
            for alias in FIELD_ALIASES[key]:
                value = lowered.get(alias)
                if value not in (None, ""):
                    return value
            return None

        name = pick("name")
        price = _parse_price(pick("price"))
        if not name or price is None:
            return None

        tags = pick("tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in re.split(r"[,;|]", tags) if t.strip()]
        category = pick("category") or ""
        if isinstance(category, list):
            category = ", ".join(str(c.get("name", c)) if isinstance(c, dict) else str(c) for c in category)

        stock = pick("stock")
        try:
            stock = int(float(stock)) if stock is not None else None
        except (TypeError, ValueError):
            stock = None if str(stock).lower() not in ("out of stock", "no", "false") else 0

        return cls(
            id=str(pick("id") or f"item-{index}"),
            name=_strip_html(str(name)),
            price=round(price, 2),
            category=str(category),
            brand=str(pick("brand") or ""),
            description=_strip_html(str(pick("description") or ""))[:500],
            unit=str(pick("unit") or ""),
            stock=stock,
            tags=[str(t).lower() for t in tags],
            url=str(pick("url") or ""),
            image=str(pick("image") or ""),
            currency=str(pick("currency") or "USD"),
        )


class Catalog:
    def __init__(self, products: Iterable[Product] = (), source: str = ""):
        self.products: dict[str, Product] = {}
        self.source = source
        for product in products:
            self.add(product)

    def add(self, product: Product) -> None:
        # De-duplicate ids coming from messy sources.
        pid, n = product.id, 2
        while pid in self.products:
            pid = f"{product.id}-{n}"
            n += 1
        product.id = pid
        self.products[pid] = product

    def __len__(self) -> int:
        return len(self.products)

    def get(self, product_id: str) -> Product | None:
        return self.products.get(product_id)

    def categories(self) -> list[str]:
        return sorted({p.category for p in self.products.values() if p.category})

    def summary(self) -> str:
        cats = self.categories()
        prices = [p.price for p in self.products.values()]
        lines = [f"{len(self)} products loaded from {self.source or 'unknown source'}."]
        if prices:
            lines.append(f"Price range: {min(prices):.2f} - {max(prices):.2f}.")
        if cats:
            lines.append("Categories: " + ", ".join(cats[:60]))
        return "\n".join(lines)

    def search(
        self,
        query: str = "",
        category: str | None = None,
        max_price: float | None = None,
        min_price: float | None = None,
        tags: list[str] | None = None,
        in_stock_only: bool = True,
        sort: str = "relevance",
        limit: int = 8,
    ) -> list[Product]:
        q_tokens = _tokens(query)
        expanded = set(q_tokens)
        for t in q_tokens:
            for syn in SYNONYMS.get(t, []):
                expanded.update(_tokens(syn))
        wanted_tags = {t.lower() for t in (tags or [])}

        scored: list[tuple[float, Product]] = []
        for p in self.products.values():
            if in_stock_only and not p.in_stock:
                continue
            if max_price is not None and p.price > max_price:
                continue
            if min_price is not None and p.price < min_price:
                continue
            if category and category.lower() not in p.category.lower():
                continue
            haystack_tags = set(p.tags) | set(_tokens(" ".join(p.tags)))
            if wanted_tags and not wanted_tags <= haystack_tags:
                continue

            score = 0.0
            if q_tokens:
                name_t = set(_tokens(p.name))
                meta_t = set(_tokens(f"{p.category} {p.brand} {' '.join(p.tags)}"))
                desc_t = set(_tokens(p.description))
                for t in expanded:
                    weight = 1.0 if t in q_tokens else 0.6
                    if t in name_t:
                        score += 3 * weight
                    elif any(n.startswith(t) or t.startswith(n) for n in name_t if len(n) > 2 and len(t) > 2):
                        score += 1.5 * weight
                    if t in meta_t:
                        score += 1.5 * weight
                    if t in desc_t:
                        score += 0.5 * weight
                # Bonus when every query word hits the name, e.g. "whole milk".
                if all(t in name_t for t in q_tokens):
                    score += 2
                if score == 0:
                    continue
            scored.append((score, p))

        if sort == "price_asc":
            scored.sort(key=lambda sp: (sp[1].price, -sp[0]))
        elif sort == "price_desc":
            scored.sort(key=lambda sp: (-sp[1].price, -sp[0]))
        else:
            scored.sort(key=lambda sp: (-sp[0], sp[1].price))
        return [p for _, p in scored[:limit]]


# ---------------------------------------------------------------- loaders


def _records_to_catalog(records: Iterable[dict], source: str) -> Catalog:
    catalog = Catalog(source=source)
    for i, rec in enumerate(records):
        product = Product.from_record(rec, i)
        if product:
            catalog.add(product)
    return catalog


def load_csv_text(text: str, source: str = "csv") -> Catalog:
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    return _records_to_catalog(reader, source)


def load_json_data(data, source: str = "json") -> Catalog:
    if isinstance(data, dict):
        # Common wrappers: {"products": [...]}, {"items": [...]}, {"data": [...]}
        for key in ("products", "items", "data", "results"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            data = [data]
    records = []
    for item in data:
        if isinstance(item, dict) and isinstance(item.get("variants"), list) and item["variants"]:
            records.extend(_shopify_records(item))
        elif isinstance(item, dict):
            records.append(item)
    return _records_to_catalog(records, source)


def _shopify_records(item: dict) -> list[dict]:
    """Flatten a Shopify product (products.json) into one record per variant."""
    out = []
    image = (item.get("images") or [{}])[0].get("src", "") if item.get("images") else ""
    for v in item["variants"]:
        variant_title = v.get("title") or ""
        title = item.get("title", "")
        if variant_title and variant_title.lower() != "default title":
            title = f"{title} - {variant_title}"
        out.append({
            "id": v.get("sku") or v.get("id"),
            "title": title,
            "price": v.get("price"),
            "product_type": item.get("product_type"),
            "vendor": item.get("vendor"),
            "body_html": item.get("body_html"),
            "tags": item.get("tags"),
            "stock": 1 if v.get("available", True) else 0,
            "image": image,
            "url": item.get("handle", ""),
        })
    return out


def load_file(path: str | Path) -> Catalog:
    path = Path(path)
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() in (".json", ".jsonl"):
        if path.suffix.lower() == ".jsonl":
            data = [json.loads(line) for line in text.splitlines() if line.strip()]
        else:
            data = json.loads(text)
        return load_json_data(data, source=str(path))
    return load_csv_text(text, source=str(path))


def load_source(source: str, **kwargs) -> Catalog:
    """Load a catalog from a file path or an http(s) URL."""
    if re.match(r"^https?://", source, re.I):
        from .scraper import load_url

        return load_url(source, **kwargs)
    return load_file(source)
