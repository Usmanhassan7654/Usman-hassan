"""The product list: stored in data/products.csv, edited from the manager dashboard.

The CSV can also be opened and edited in Excel or Google Sheets. List fields
(dietary, allergens, pairs_with) are written in one cell separated by
semicolons, e.g. "vegan; gluten-free".

Every change is validated, written to the CSV safely (to a temporary file
first, then swapped in), and the chat's search index is rebuilt so the change
is live immediately.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import threading
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"
CSV_PATH = DATA / "products.csv"
IMAGES = DATA / "images"

COLUMNS = ["id", "name", "brand", "category", "price", "size", "stock", "rating", "description",
           "dietary", "allergens", "keywords", "pairs_with", "image"]
LIST_FIELDS = ("dietary", "allergens", "pairs_with")
DIETARY = ["vegan", "vegetarian", "gluten-free", "dairy-free", "organic", "keto", "nut-free", "low-sugar", "high-protein"]
ALLERGENS = ["milk", "eggs", "wheat", "tree-nuts", "peanuts", "soy", "fish", "shellfish", "sesame"]
IMAGE_TYPES = {".jpg": b"\xff\xd8\xff", ".jpeg": b"\xff\xd8\xff", ".png": b"\x89PNG", ".webp": b"RIFF", ".svg": b"<"}
MAX_IMAGE_BYTES = 3 * 1024 * 1024


class ProductError(ValueError):
    """A product that can't be saved, with a message the manager can act on."""


# ------------------------------------------------------------------ reading/writing

def read_csv(path: Path = CSV_PATH) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [from_row(r) for r in csv.DictReader(f)]


def from_row(r: dict) -> dict:
    """A CSV row (all text) -> a product with numbers and lists."""
    p = {k: (r.get(k) or "").strip() for k in COLUMNS}
    p["price"] = float(p["price"] or 0)
    p["stock"] = int(float(p["stock"] or 0))
    p["rating"] = float(p["rating"] or 0)
    for k in LIST_FIELDS:
        p[k] = [x.strip().lower() if k != "pairs_with" else x.strip() for x in re.split(r"[;,|]", p[k]) if x.strip()]
    return p


def to_row(p: dict) -> dict:
    row = {k: p.get(k, "") for k in COLUMNS}
    for k in LIST_FIELDS:
        row[k] = "; ".join(p.get(k) or [])
    row["price"] = f"{float(p['price']):.2f}"
    return row


def write_csv(products: list[dict], path: Path = CSV_PATH) -> None:
    tmp = path.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for p in products:
            w.writerow(to_row(p))
    os.replace(tmp, path)  # never leaves a half-written catalog


def to_csv_text(products: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS)
    w.writeheader()
    for p in products:
        w.writerow(to_row(p))
    return buf.getvalue()


def image_url(p: dict) -> str:
    img = p.get("image") or ""
    if img.startswith(("http://", "https://")):
        return img
    return f"/images/{img}" if img else "/images/placeholder.svg"


# ------------------------------------------------------------------ validation

def clean(data: dict, existing: list[dict], editing_id: str | None = None) -> tuple[dict, list[str]]:
    """Validate and normalise a product from the form or a CSV row. Returns (product, warnings)."""
    def text(k, limit=200):
        return str(data.get(k) or "").strip()[:limit]

    p = {"id": text("id", 40) or editing_id or "", "name": text("name", 120), "brand": text("brand", 60),
         "category": text("category", 60), "size": text("size", 40), "description": text("description", 600),
         "keywords": text("keywords", 200), "image": text("image", 500)}
    errors = []
    if not p["name"]:
        errors.append("Name is required.")
    if not p["category"]:
        errors.append("Category is required.")
    if not p["size"]:
        errors.append("Size is required (e.g. 1 L, 500 g, 12 ct).")
    try:
        p["price"] = round(float(str(data.get("price", "")).replace("$", "").strip()), 2)
        if p["price"] <= 0:
            errors.append("Price must be more than 0.")
    except ValueError:
        errors.append("Price must be a number, e.g. 3.99.")
        p["price"] = 0
    try:
        p["stock"] = int(float(str(data.get("stock", "0")).strip() or 0))
        if p["stock"] < 0:
            errors.append("Stock can't be negative.")
    except ValueError:
        errors.append("Stock must be a whole number.")
        p["stock"] = 0
    try:
        p["rating"] = min(5.0, max(0.0, float(data.get("rating") or 4.5)))
    except ValueError:
        p["rating"] = 4.5
    for k, allowed in (("dietary", DIETARY), ("allergens", ALLERGENS)):
        raw = data.get(k) or []
        values = [v.strip().lower() for v in (re.split(r"[;,|]", raw) if isinstance(raw, str) else raw) if str(v).strip()]
        unknown = [v for v in values if v not in allowed]
        if unknown:
            errors.append(f"Unknown {k}: {', '.join(unknown)}. Allowed: {', '.join(allowed)}.")
        p[k] = [v for v in values if v in allowed]
    raw = data.get("pairs_with") or []
    p["pairs_with"] = [v.strip() for v in (re.split(r"[;,|]", raw) if isinstance(raw, str) else raw) if str(v).strip()]
    if p["image"] and not p["image"].startswith(("http://", "https://")) and not (IMAGES / p["image"]).exists():
        errors.append(f"Picture '{p['image']}' isn't in data/images. Upload it or use a web link.")
    if errors:
        raise ProductError(" ".join(errors))
    if not p["description"]:
        p["description"] = f"{p['name']} from {p['brand'] or 'our store'} ({p['size']})."
    warnings = []
    if any(e["name"].lower() == p["name"].lower() and e["id"] != (editing_id or p["id"]) for e in existing):
        warnings.append(f"Another product is already called '{p['name']}'.")
    return p, warnings


def new_id(category: str, existing: list[dict]) -> str:
    prefix = re.sub(r"[^A-Z]", "", category.upper())[:3].ljust(3, "X")
    taken = {e["id"] for e in existing}
    n = 1 + sum(1 for e in existing if e["id"].startswith(prefix + "-"))
    while f"{prefix}-{n:03d}" in taken:
        n += 1
    return f"{prefix}-{n:03d}"


def check_image(filename: str, data: bytes) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in IMAGE_TYPES:
        raise ProductError("Picture must be JPG, PNG, WEBP or SVG.")
    if len(data) > MAX_IMAGE_BYTES:
        raise ProductError("Picture is too big (max 3 MB).")
    head = data[:16].lstrip() if ext == ".svg" else data[:16]
    if not head.startswith(IMAGE_TYPES[ext]):
        raise ProductError("That file doesn't look like a real picture.")
    if ext == ".svg" and re.search(rb"<script|on\w+\s*=", data, re.I):
        raise ProductError("SVG pictures with scripts aren't allowed.")
    return ext


# ------------------------------------------------------------------ the store

class ProductStore:
    def __init__(self, catalog, path: Path = CSV_PATH):
        self.catalog, self.path = catalog, path
        self.lock = threading.Lock()

    def all(self) -> list[dict]:
        return self.catalog.products

    def _save(self, products: list[dict]) -> None:
        write_csv(products, self.path)
        self.catalog.reload(products)   # the chat sees the change right away

    def add(self, data: dict) -> tuple[dict, list[str]]:
        with self.lock:
            products = [dict(p) for p in self.all()]
            p, warnings = clean(data, products)
            if p["id"] and any(e["id"] == p["id"] for e in products):
                raise ProductError(f"ID {p['id']} is already used.")
            p["id"] = p["id"] or new_id(p["category"], products)
            self._save(products + [p])
            return p, warnings

    def update(self, pid: str, data: dict) -> tuple[dict, list[str]]:
        with self.lock:
            products = [dict(p) for p in self.all()]
            idx = next((i for i, e in enumerate(products) if e["id"] == pid), None)
            if idx is None:
                raise ProductError(f"No product {pid}.")
            merged = {**products[idx], **{k: v for k, v in data.items() if v is not None}, "id": pid}
            p, warnings = clean(merged, products, editing_id=pid)
            products[idx] = p
            self._save(products)
            return p, warnings

    def delete(self, pid: str) -> None:
        with self.lock:
            products = [p for p in self.all() if p["id"] != pid]
            if len(products) == len(self.all()):
                raise ProductError(f"No product {pid}.")
            self._save(products)

    def save_image(self, pid: str, filename: str, data: bytes) -> str:
        ext = check_image(filename, data)
        name = re.sub(r"[^A-Za-z0-9_-]", "", pid) + ext
        for old in IMAGES.glob(re.sub(r"[^A-Za-z0-9_-]", "", pid) + ".*"):  # replace an earlier picture of this product
            if old.name != name:
                old.unlink()
        (IMAGES / name).write_bytes(data)
        return name

    # -------------------------------------------------------------- CSV import

    def import_preview(self, text: str) -> dict:
        """Check an uploaded CSV without saving: what would be added, updated, or rejected."""
        try:
            rows = list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))
        except csv.Error as e:
            raise ProductError(f"That file isn't a readable CSV: {e}") from e
        if not rows:
            raise ProductError("The CSV has no product rows.")
        missing = [c for c in ("name", "category", "price", "size") if c not in rows[0]]
        if missing:
            raise ProductError(f"The CSV needs these columns: {', '.join(missing)}. Download the current catalog to see the format.")
        current = {p["id"]: p for p in self.all()}
        staged, added, updated, errors, warnings = [], 0, 0, [], []
        working = [dict(p) for p in self.all()]
        for n, row in enumerate(rows, start=2):  # row 1 is the header
            rid = (row.get("id") or "").strip()
            try:
                base = {**current[rid], **{k: v for k, v in row.items() if v not in (None, "")}} if rid in current else row
                p, warn = clean(base, working, editing_id=rid or None)
            except ProductError as e:
                errors.append({"row": n, "name": (row.get("name") or "").strip(), "error": str(e)})
                continue
            if rid in current:
                updated += 1
            else:
                p["id"] = rid or new_id(p["category"], working)
                added += 1
                working.append(p)
            staged.append(p)
            warnings += [f"Row {n}: {w}" for w in warn]
        return {"added": added, "updated": updated, "errors": errors, "warnings": warnings[:20], "staged": staged}

    def import_commit(self, text: str) -> dict:
        with self.lock:
            preview = self.import_preview(text)
            if preview["errors"]:
                raise ProductError(f"Fix the {len(preview['errors'])} rows with errors first.")
            products = {p["id"]: dict(p) for p in self.all()}
            for p in preview["staged"]:
                products[p["id"]] = p
            self._save(list(products.values()))
            return {k: preview[k] for k in ("added", "updated", "warnings")}

    # -------------------------------------------------------------- overview

    def overview(self, orders_path: Path) -> dict:
        ps = self.all()
        orders = json.loads(orders_path.read_text()) if orders_path.exists() else []
        return {"products": len(ps), "in_stock": sum(p["stock"] > 5 for p in ps), "low_stock": sum(0 < p["stock"] <= 5 for p in ps),
                "out_of_stock": sum(p["stock"] <= 0 for p in ps), "categories": len({p["category"] for p in ps}),
                "orders": len(orders), "revenue": round(sum(o["total"] for o in orders), 2),
                "needs_attention": [{"id": p["id"], "name": p["name"], "stock": p["stock"]} for p in sorted(ps, key=lambda p: p["stock"]) if p["stock"] <= 5][:8]}
