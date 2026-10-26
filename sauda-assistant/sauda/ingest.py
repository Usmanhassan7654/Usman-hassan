"""Catalog connectors and synchronization.

A sync job reads a full snapshot from a source, normalizes and classifies each
product, and writes products and store offers in checkpointed batches. Only
when the whole snapshot has been read does the final transaction unpublish
products that disappeared and rebuild the search index, so customers never
see a half-imported catalog. A failed job can be resumed from its checkpoint.

Supported sources: CSV / JSON / JSONL files or URLs, Shopify storefronts
(/products.json) and WooCommerce stores (Store API). Anything else needs a
connector written for it.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import time
from pathlib import Path
from typing import Iterable, Iterator

from . import text as txt
from .db import Repo, Scope

ALIASES = {
    "source_id": ["sku", "id", "product_id", "item_id", "variant_sku", "code", "handle"],
    "name": ["name", "title", "product_name", "product", "item_name"],
    "price": ["price", "sale_price", "unit_price", "variant_price", "amount"],
    "category": ["category", "categories", "product_type", "type", "department", "aisle"],
    "brand": ["brand", "vendor", "manufacturer"],
    "size": ["size", "unit", "weight", "pack_size", "net_weight", "volume"],
    "stock": ["stock", "inventory", "qty", "quantity", "inventory_quantity", "stock_quantity", "available"],
    "image": ["image_url", "image", "image_link", "image_src", "picture", "thumbnail"],
    "url": ["url", "link", "product_url", "permalink"],
}

BATCH = 200


class SourceError(Exception):
    pass


# ----------------------------------------------------------------- reading

def read_source(source: str) -> Iterator[dict]:
    if re.match(r"^https?://", source, re.I):
        yield from _read_url(source)
        return
    path = Path(source)
    if not path.exists():
        raise SourceError(f"File not found: {source}")
    data = path.read_text(encoding="utf-8-sig")
    yield from _parse(data, path.suffix.lower())


def _parse(data: str, suffix: str) -> Iterator[dict]:
    if suffix == ".jsonl":
        for line in data.splitlines():
            if line.strip():
                yield json.loads(line)
        return
    if suffix == ".json" or data.lstrip()[:1] in "[{":
        obj = json.loads(data)
        if isinstance(obj, dict):
            obj = next((obj[k] for k in ("products", "items", "data", "results") if isinstance(obj.get(k), list)), [obj])
        for item in obj:
            if isinstance(item, dict) and isinstance(item.get("variants"), list) and item["variants"]:
                yield from _shopify_variants(item)
            elif isinstance(item, dict):
                yield item
        return
    try:
        dialect = csv.Sniffer().sniff(data[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    yield from csv.DictReader(io.StringIO(data), dialect=dialect)


def _read_url(url: str) -> Iterator[dict]:
    import requests

    headers = {"User-Agent": "SaudaCatalogSync/1.0"}
    if url.lower().split("?")[0].endswith((".csv", ".json", ".jsonl")):
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        yield from _parse(r.text, Path(url.split("?")[0]).suffix.lower())
        return
    origin = re.match(r"^(https?://[^/]+)", url).group(1)
    found_shopify = False
    for page in range(1, 41):  # Shopify
        r = requests.get(f"{origin}/products.json?limit=250&page={page}", headers=headers, timeout=30)
        if not r.ok or "json" not in r.headers.get("content-type", ""):
            break
        batch = r.json().get("products", [])
        if not batch:
            break
        found_shopify = True
        for item in batch:
            item["handle"] = f"{origin}/products/{item.get('handle', '')}"
            yield from _shopify_variants(item)
    if found_shopify:
        return
    for page in range(1, 41):  # WooCommerce Store API
        r = requests.get(f"{origin}/wp-json/wc/store/v1/products?per_page=100&page={page}", headers=headers, timeout=30)
        if not r.ok:
            if page == 1:
                raise SourceError(f"{origin} is not a Shopify or WooCommerce store and is not a CSV/JSON feed. It needs its own connector.")
            break
        batch = r.json()
        if not batch:
            break
        for item in batch:
            prices = item.get("prices") or {}
            minor = int(prices.get("currency_minor_unit", 2) or 2)
            yield {
                "sku": item.get("sku") or item.get("id"), "name": item.get("name"),
                "price": int(prices["price"]) / 10 ** minor if prices.get("price") else None,
                "category": ", ".join(c.get("name", "") for c in item.get("categories", [])),
                "stock": 1 if item.get("is_in_stock", True) else 0, "url": item.get("permalink"),
                "image": (item.get("images") or [{}])[0].get("src", "") if item.get("images") else "",
            }


def _shopify_variants(item: dict) -> Iterator[dict]:
    image = (item.get("images") or [{}])[0].get("src", "") if item.get("images") else ""
    for v in item["variants"]:
        title = item.get("title", "")
        if v.get("title") and v["title"].lower() != "default title":
            title = f"{title} {v['title']}"
        yield {"sku": v.get("sku") or v.get("id"), "title": title, "price": v.get("price"), "product_type": item.get("product_type"),
               "vendor": item.get("vendor"), "stock": 1 if v.get("available", True) else 0, "image": image, "url": item.get("handle", "")}


# ---------------------------------------------------------------- normalize

def _pick(rec: dict, key: str):
    low = {re.sub(r"[\s-]+", "_", str(k).strip().lower()): v for k, v in rec.items()}
    for alias in ALIASES[key]:
        v = low.get(alias)
        if v not in (None, ""):
            return v
    return None


def _price(v) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"\d[\d,]*(?:\.\d+)?", str(v))
    return float(m.group(0).replace(",", "")) if m else None


def normalize(rec: dict) -> dict | None:
    name, price = _pick(rec, "name"), _price(_pick(rec, "price"))
    source_id = _pick(rec, "source_id")
    if not name or price is None or price <= 0 or source_id in (None, ""):
        return None
    stock = _pick(rec, "stock")
    if isinstance(stock, str) and stock.strip().lower() in ("true", "yes", "in stock"):
        stock = None
    elif isinstance(stock, str) and stock.strip().lower() in ("false", "no", "out of stock"):
        stock = 0
    else:
        try:
            stock = int(float(stock)) if stock is not None else None
        except (TypeError, ValueError):
            stock = None
    out = {
        "source_id": str(source_id).strip(), "name": re.sub(r"\s+", " ", str(name)).strip(), "price": round(price, 2),
        "category": str(_pick(rec, "category") or ""), "brand": str(_pick(rec, "brand") or ""),
        "size": str(_pick(rec, "size") or ""), "stock": stock, "image": str(_pick(rec, "image") or ""), "url": str(_pick(rec, "url") or ""),
    }
    if out["image"] and not re.match(r"^https://", out["image"]):
        out["image"] = ""  # only https images are shown to customers
    return out


# ------------------------------------------------------------------- sync

def sync(repo: Repo, scope: Scope, source: str, rows: Iterable[dict] | None = None, resume_job: int | None = None) -> dict:
    """Run (or resume) a full-snapshot sync of `source` into this store."""
    records = list(rows if rows is not None else read_source(source))
    now = time.time()
    c = repo.conn
    if resume_job:
        job = c.execute("SELECT * FROM sync_jobs WHERE id = ? AND retailer_id = ? AND store_id = ?",
                        (resume_job, scope.retailer_id, scope.store_id)).fetchone()
        if not job or job["status"] == "completed":
            raise SourceError("Nothing to resume.")
        job_id, start = job["id"], job["checkpoint"]
        stats = json.loads(job["stats"] or "{}")
    else:
        with repo.tx() as t:
            job_id = t.execute("INSERT INTO sync_jobs(retailer_id, store_id, source, status, started_at) VALUES (?,?,?,?,?)",
                               (scope.retailer_id, scope.store_id, source, "running", now)).lastrowid
        start, stats = 0, {"read": len(records), "invalid": 0, "written": 0, "unchanged": 0, "unclassified": 0}

    seen_key = f"sync-seen-{job_id}"
    try:
        for offset in range(start, len(records), BATCH):
            with repo.tx() as t:
                for rec in records[offset:offset + BATCH]:
                    item = normalize(rec)
                    if not item:
                        stats["invalid"] += 1
                        continue
                    _upsert(t, scope, source, item, seen_key, stats)
                t.execute("UPDATE sync_jobs SET checkpoint = ?, stats = ? WHERE id = ?",
                          (min(offset + BATCH, len(records)), json.dumps(stats), job_id))
        # Publish: one transaction swaps the snapshot in.
        with repo.tx() as t:
            gone = t.execute("""UPDATE products SET published = 0, updated_at = ?
                                WHERE retailer_id = ? AND source = ? AND published = 1 AND (content_hash IS NULL OR content_hash NOT LIKE ?)""",
                             (now, scope.retailer_id, source, f"%|{seen_key}")).rowcount
            t.execute("UPDATE products SET content_hash = substr(content_hash, 1, instr(content_hash, '|') - 1) "
                      "WHERE retailer_id = ? AND content_hash LIKE ?", (scope.retailer_id, f"%|{seen_key}"))
            t.execute("DELETE FROM products_fts WHERE retailer_id = ?", (scope.retailer_id,))
            for r in t.execute("SELECT product_id, name, brand, category, kind FROM products WHERE retailer_id = ? AND published = 1",
                               (scope.retailer_id,)).fetchall():
                kind_words = r["kind"].replace(".", " ").replace("_", " ") if r["kind"] != "unknown" else ""
                t.execute("INSERT INTO products_fts(retailer_id, product_id, body) VALUES (?,?,?)",
                          (scope.retailer_id, r["product_id"], f"{r['name']} {r['brand']} {r['category']} {kind_words}"))
            stats["unpublished"] = gone
            t.execute("UPDATE sync_jobs SET status = 'completed', stats = ?, finished_at = ? WHERE id = ?",
                      (json.dumps(stats), time.time(), job_id))
    except Exception as e:
        with repo.tx() as t:
            t.execute("UPDATE sync_jobs SET status = 'failed', error = ?, stats = ?, finished_at = ? WHERE id = ?",
                      (str(e)[:500], json.dumps(stats), time.time(), job_id))
        raise
    return {"job_id": job_id, **stats}


def _upsert(t, scope: Scope, source: str, item: dict, seen_key: str, stats: dict) -> None:
    product_id = f"{scope.retailer_id}:{item['source_id']}"
    content = json.dumps({k: item[k] for k in ("name", "brand", "category", "size", "image", "url")}, sort_keys=True)
    digest = hashlib.sha256(content.encode()).hexdigest()[:16]
    row = t.execute("SELECT content_hash FROM products WHERE retailer_id = ? AND product_id = ?", (scope.retailer_id, product_id)).fetchone()
    old = (row["content_hash"] or "").split("|")[0] if row else None
    if row and old == digest:
        t.execute("UPDATE products SET content_hash = ?, published = 1 WHERE retailer_id = ? AND product_id = ?",
                  (f"{digest}|{seen_key}", scope.retailer_id, product_id))
        stats["unchanged"] += 1
    else:
        cls = txt.classify(item["name"], item["category"], item["brand"])
        pack = txt.parse_pack(item["size"], item["name"])
        if cls.kind == "unknown":
            stats["unclassified"] += 1
        t.execute(
            """INSERT OR REPLACE INTO products(retailer_id, product_id, source, source_id, name, brand, category, size_text,
               pack_amount, pack_unit, image, url, kind, kind_confidence, kind_method, kind_reason, content_hash, published, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)""",
            (scope.retailer_id, product_id, source, item["source_id"], item["name"], item["brand"], item["category"],
             item["size"] or (pack.label() if pack else ""), pack.amount if pack else None, pack.unit if pack else None,
             item["image"], item["url"], cls.kind, cls.confidence, cls.method, cls.reason, f"{digest}|{seen_key}", time.time()))
        stats["written"] += 1
    t.execute("INSERT OR REPLACE INTO offers(retailer_id, store_id, product_id, price, stock, updated_at) VALUES (?,?,?,?,?,?)",
              (scope.retailer_id, scope.store_id, product_id, item["price"], item["stock"], time.time()))
