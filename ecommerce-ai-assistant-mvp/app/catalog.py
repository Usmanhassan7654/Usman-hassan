"""Product catalog and vector search.

Every product is turned into a vector from its name, brand, category,
description, tags and keywords. A search query becomes a vector the same way
and products are ranked by cosine similarity. Two kinds of vectors are
combined: word vectors (meaning of whole words) and character vectors (so
misspellings like "choclate" or "yoghurt" still match).

On top of that, AI embeddings (the `fastembed` package, installed with the
requirements) add meaning-based matching: "something for breakfast" finds
oats, eggs and muffins even without those words. The small model (about
70 MB) downloads once on first start; without internet the search falls back
to word and character vectors.

Filters (price, diet, allergens, category, stock) are applied exactly, after
the vector ranking.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
from scipy.sparse import hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

DATA = Path(__file__).resolve().parents[1] / "data"

SYNONYMS = {
    "veggies": "vegetables", "veggie": "vegetable", "soda": "cola soft drink", "pop": "soda cola", "chips": "chips crisps",
    "mince": "ground beef", "yoghurt": "yogurt", "prawns": "shrimp", "coriander": "cilantro", "aubergine": "eggplant",
    "courgette": "zucchini", "capsicum": "bell pepper", "nappies": "diapers", "biscuits": "cookies crackers",
    "sweets": "candy chocolate", "fizzy": "soda sparkling", "porridge": "oats oatmeal", "noodles": "noodles pasta",
}
ALLERGEN_GROUPS = {"nuts": ["tree-nuts", "peanuts"], "nut": ["tree-nuts", "peanuts"], "dairy": ["milk"], "lactose": ["milk"],
                   "gluten": ["wheat"], "egg": ["eggs"], "seafood": ["fish", "shellfish"]}


class Catalog:
    def __init__(self, path: Path = DATA / "products.json"):
        self.products: list[dict] = json.loads(Path(path).read_text(encoding="utf-8"))
        self.by_id = {p["id"]: p for p in self.products}
        docs = [self._doc(p) for p in self.products]
        self.words = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, stop_words="english")
        self.chars = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)
        self.matrix = normalize(hstack([self.words.fit_transform(docs), 0.7 * self.chars.fit_transform(docs)]).tocsr())
        self.dense, self.embedder = None, None
        if os.environ.get("USE_EMBEDDINGS", "1") != "0":
            self._load_embeddings(docs)

    @staticmethod
    def _doc(p: dict) -> str:
        return " ".join([p["name"], p["name"], p["brand"], p["category"], p["description"], p["keywords"], p["keywords"],
                         " ".join(p["dietary"])])

    def _load_embeddings(self, docs: list[str]) -> None:
        try:
            from fastembed import TextEmbedding  # optional: pip install fastembed
        except ImportError:
            return
        try:
            # Kept in data/models so it downloads only once.
            self.embedder = TextEmbedding("BAAI/bge-small-en-v1.5", cache_dir=str(DATA / "models"))
            self.dense = np.array(list(self.embedder.embed(docs)), dtype=np.float32)
            self.dense /= np.linalg.norm(self.dense, axis=1, keepdims=True)
        except Exception as e:  # no internet on first run, etc.: keep the word/character vectors
            print(f"Embeddings unavailable ({e}); using word and character vectors only.")
            self.dense, self.embedder = None, None

    @property
    def mode(self) -> str:
        return "word + character vectors + AI embeddings" if self.dense is not None else "word + character vectors"

    def similarity(self, query: str) -> np.ndarray:
        q = " ".join(SYNONYMS.get(w, w) for w in query.lower().split())
        qv = normalize(hstack([self.words.transform([q]), 0.7 * self.chars.transform([q])]).tocsr())
        scores = (self.matrix @ qv.T).toarray().ravel()
        if self.dense is not None:
            e = np.array(list(self.embedder.embed([q])), dtype=np.float32)[0]
            meaning = self.dense @ (e / np.linalg.norm(e))
            # Embedding similarities sit around 0.4-0.5 for unrelated text and 0.65+ for related text;
            # rescale so only real matches add to the score.
            scores = 0.6 * scores + 0.4 * np.clip((meaning - 0.5) / 0.4, 0, 1)
        return scores

    def search(self, query: str = "", max_price: float | None = None, dietary: list[str] | None = None,
               exclude_allergens: list[str] | None = None, category: str | None = None, sort: str = "relevance",
               limit: int = 6) -> dict:
        """Ranked matches plus close matches that are out of stock (so substitutes can be offered)."""
        avoid = set()
        for a in exclude_allergens or []:
            avoid.update(ALLERGEN_GROUPS.get(a.lower(), [a.lower()]))
        need_tags = {d.lower() for d in dietary or []}
        scores = self.similarity(query) if query.strip() else np.ones(len(self.products))
        floor = 0.06 if query.strip() else 0
        ranked = sorted(range(len(self.products)), key=lambda i: -scores[i])
        hits, unavailable = [], []
        for i in ranked:
            p = self.products[i]
            if scores[i] < floor:
                break
            if max_price is not None and p["price"] > max_price:
                continue
            if category and category.lower() not in p["category"].lower():
                continue
            if need_tags and not need_tags <= set(p["dietary"]):
                continue
            if avoid & set(p["allergens"]):
                continue
            if p["stock"] <= 0:
                if len(unavailable) < 3:
                    unavailable.append((scores[i], p))
                continue
            hits.append((scores[i], p))
            if len(hits) >= max(limit * 3, 15):
                break
        # Report an out-of-stock product only if it matched about as well as the best available one.
        top = hits[0][0] if hits else 0
        unavailable = [p for s, p in unavailable if s >= 0.8 * top]
        if sort == "price_low":
            hits.sort(key=lambda h: h[1]["price"])
        elif sort == "rating":
            hits.sort(key=lambda h: -h[1]["rating"])
        return {"results": [p for _, p in hits[:limit]], "out_of_stock": unavailable}

    def best(self, query: str, **filters) -> dict | None:
        found = self.search(query, limit=1, **filters)["results"]
        return found[0] if found else None


def card(p: dict, quantity: int | None = None) -> dict:
    """What the chat UI shows for a product."""
    out = {k: p[k] for k in ("id", "name", "brand", "price", "size", "image", "rating", "dietary")}
    out["in_stock"] = p["stock"] > 0
    if quantity:
        out["quantity"] = quantity
        out["line_total"] = round(p["price"] * quantity, 2)
    return out


def brief(p: dict) -> dict:
    """What the model sees about a product: small, so requests stay cheap."""
    return {"id": p["id"], "name": p["name"], "brand": p["brand"], "price": p["price"], "size": p["size"],
            "dietary": p["dietary"], "allergens": p["allergens"], "in_stock": p["stock"] > 0}
