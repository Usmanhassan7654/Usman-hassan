"""SQLite storage. Every read and write takes a Scope, so one retailer's
products, sessions and baskets can never leak into another's.

The scope comes from trusted configuration (the store's API key), never from
the model or the customer's message.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS retailers (
  id TEXT PRIMARY KEY, name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stores (
  id TEXT PRIMARY KEY, retailer_id TEXT NOT NULL REFERENCES retailers(id),
  name TEXT NOT NULL, currency TEXT NOT NULL DEFAULT 'PKR', api_key_sha256 TEXT UNIQUE
);
CREATE TABLE IF NOT EXISTS products (
  retailer_id TEXT NOT NULL, product_id TEXT NOT NULL,
  source TEXT NOT NULL, source_id TEXT NOT NULL,
  name TEXT NOT NULL, brand TEXT, category TEXT, size_text TEXT,
  pack_amount REAL, pack_unit TEXT, image TEXT, url TEXT,
  kind TEXT NOT NULL, kind_confidence REAL, kind_method TEXT, kind_reason TEXT,
  content_hash TEXT, published INTEGER NOT NULL DEFAULT 1, updated_at REAL,
  PRIMARY KEY (retailer_id, product_id)
);
CREATE INDEX IF NOT EXISTS products_kind ON products(retailer_id, kind, published);
CREATE TABLE IF NOT EXISTS offers (
  retailer_id TEXT NOT NULL, store_id TEXT NOT NULL, product_id TEXT NOT NULL,
  price REAL NOT NULL, stock INTEGER, updated_at REAL,
  PRIMARY KEY (store_id, product_id)
);
CREATE VIRTUAL TABLE IF NOT EXISTS products_fts USING fts5(
  retailer_id UNINDEXED, product_id UNINDEXED, body, tokenize = 'unicode61 remove_diacritics 2'
);
CREATE TABLE IF NOT EXISTS sessions (
  store_id TEXT NOT NULL, session_id TEXT NOT NULL,
  ledger TEXT NOT NULL, history TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 0, updated_at REAL,
  PRIMARY KEY (store_id, session_id)
);
CREATE TABLE IF NOT EXISTS baskets (
  store_id TEXT NOT NULL, session_id TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 0, lines TEXT NOT NULL DEFAULT '[]', updated_at REAL,
  PRIMARY KEY (store_id, session_id)
);
CREATE TABLE IF NOT EXISTS basket_ops (
  store_id TEXT NOT NULL, session_id TEXT NOT NULL, idempotency_key TEXT NOT NULL,
  result TEXT NOT NULL, created_at REAL,
  PRIMARY KEY (store_id, session_id, idempotency_key)
);
CREATE TABLE IF NOT EXISTS sync_jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, retailer_id TEXT NOT NULL, store_id TEXT NOT NULL,
  source TEXT NOT NULL, status TEXT NOT NULL, checkpoint INTEGER NOT NULL DEFAULT 0,
  stats TEXT, error TEXT, started_at REAL, finished_at REAL
);
"""


@dataclass(frozen=True)
class Scope:
    retailer_id: str
    store_id: str
    currency: str = "PKR"


def key_hash(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


class Repo:
    def __init__(self, path: str | Path = "sauda.db"):
        self.path = str(path)
        self._local = threading.local()
        self.conn.executescript(SCHEMA)

    @property
    def conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=15, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return conn

    @contextmanager
    def tx(self):
        c = self.conn
        c.execute("BEGIN IMMEDIATE")
        try:
            yield c
            c.execute("COMMIT")
        except BaseException:
            c.execute("ROLLBACK")
            raise

    # -------------------------------------------------------------- tenants

    def add_store(self, retailer_id: str, retailer_name: str, store_id: str, store_name: str,
                  api_key: str, currency: str = "PKR") -> Scope:
        with self.tx() as c:
            c.execute("INSERT OR IGNORE INTO retailers(id, name) VALUES (?, ?)", (retailer_id, retailer_name))
            c.execute("INSERT OR REPLACE INTO stores(id, retailer_id, name, currency, api_key_sha256) VALUES (?,?,?,?,?)",
                      (store_id, retailer_id, store_name, currency, key_hash(api_key)))
        return Scope(retailer_id, store_id, currency)

    def scope_for_key(self, api_key: str) -> Scope | None:
        row = self.conn.execute("SELECT id, retailer_id, currency FROM stores WHERE api_key_sha256 = ?",
                                (key_hash(api_key),)).fetchone()
        return Scope(row["retailer_id"], row["id"], row["currency"]) if row else None

    def store_name(self, scope: Scope) -> str:
        row = self.conn.execute("SELECT s.name AS s, r.name AS r FROM stores s JOIN retailers r ON r.id = s.retailer_id "
                                "WHERE s.id = ? AND s.retailer_id = ?", (scope.store_id, scope.retailer_id)).fetchone()
        return f"{row['r']} ({row['s']})" if row else scope.store_id

    # ------------------------------------------------------------- catalog

    def products_by_kinds(self, scope: Scope, kinds: list[str], include_unpublished: bool = False) -> list[sqlite3.Row]:
        if not kinds:
            return []
        marks = ",".join("?" * len(kinds))
        published = "" if include_unpublished else "AND p.published = 1"
        return self.conn.execute(
            f"""SELECT p.*, o.price, o.stock, (o.product_id IS NOT NULL) AS has_offer
                FROM products p LEFT JOIN offers o
                  ON o.product_id = p.product_id AND o.store_id = ? AND o.retailer_id = p.retailer_id
                WHERE p.retailer_id = ? AND p.kind IN ({marks}) {published}""",
            (scope.store_id, scope.retailer_id, *kinds)).fetchall()

    def products_by_ids(self, scope: Scope, ids: list[str]) -> dict[str, sqlite3.Row]:
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        rows = self.conn.execute(
            f"""SELECT p.*, o.price, o.stock, (o.product_id IS NOT NULL) AS has_offer
                FROM products p LEFT JOIN offers o
                  ON o.product_id = p.product_id AND o.store_id = ? AND o.retailer_id = p.retailer_id
                WHERE p.retailer_id = ? AND p.product_id IN ({marks})""",
            (scope.store_id, scope.retailer_id, *ids)).fetchall()
        return {r["product_id"]: r for r in rows}

    def lexical_scores(self, scope: Scope, terms: list[str], product_ids: list[str]) -> dict[str, float]:
        """BM25 relevance of the given products to the search terms (higher is better)."""
        words = sorted({w for t in terms for w in _fts_words(t)})
        if not words or not product_ids:
            return {}
        query = " OR ".join(f'"{w}"*' for w in words)
        marks = ",".join("?" * len(product_ids))
        rows = self.conn.execute(
            f"""SELECT product_id, bm25(products_fts) AS score FROM products_fts
                WHERE products_fts MATCH ? AND retailer_id = ? AND product_id IN ({marks})""",
            (query, scope.retailer_id, *product_ids)).fetchall()
        return {r["product_id"]: -r["score"] for r in rows}

    def browse(self, scope: Scope, kind: str | None, query: str | None, page: int, page_size: int) -> tuple[list[sqlite3.Row], int]:
        where, args = ["p.retailer_id = ?", "p.published = 1"], [scope.retailer_id]
        if kind:
            where.append("(p.kind = ? OR p.kind LIKE ?)")
            args += [kind, kind + ".%"]
        if query:
            ids = [r["product_id"] for r in self.conn.execute(
                "SELECT product_id FROM products_fts WHERE products_fts MATCH ? AND retailer_id = ?",
                (" OR ".join(f'"{w}"*' for w in _fts_words(query)) or '""', scope.retailer_id)).fetchall()]
            if not ids:
                return [], 0
            where.append(f"p.product_id IN ({','.join('?' * len(ids))})")
            args += ids
        sql = f"""FROM products p JOIN offers o ON o.product_id = p.product_id AND o.store_id = ? AND o.retailer_id = p.retailer_id
                  WHERE {' AND '.join(where)}"""
        total = self.conn.execute(f"SELECT COUNT(*) {sql}", (scope.store_id, *args)).fetchone()[0]
        rows = self.conn.execute(f"SELECT p.*, o.price, o.stock, 1 AS has_offer {sql} ORDER BY p.kind, o.price LIMIT ? OFFSET ?",
                                 (scope.store_id, *args, page_size, (page - 1) * page_size)).fetchall()
        return rows, total

    def catalog_stats(self, scope: Scope) -> dict:
        c = self.conn
        published = c.execute("SELECT COUNT(*) FROM products WHERE retailer_id = ? AND published = 1", (scope.retailer_id,)).fetchone()[0]
        unknown = c.execute("SELECT COUNT(*) FROM products WHERE retailer_id = ? AND published = 1 AND kind = 'unknown'",
                            (scope.retailer_id,)).fetchone()[0]
        offers = c.execute("SELECT COUNT(*) FROM offers WHERE store_id = ? AND retailer_id = ?", (scope.store_id, scope.retailer_id)).fetchone()[0]
        kinds = c.execute("SELECT COUNT(DISTINCT kind) FROM products WHERE retailer_id = ? AND published = 1 AND kind != 'unknown'",
                          (scope.retailer_id,)).fetchone()[0]
        last = c.execute("SELECT status, finished_at, stats FROM sync_jobs WHERE retailer_id = ? AND store_id = ? ORDER BY id DESC LIMIT 1",
                         (scope.retailer_id, scope.store_id)).fetchone()
        return {"published_products": published, "unclassified": unknown, "store_offers": offers, "kinds": kinds,
                "last_sync": dict(last) if last else None}

    # ------------------------------------------------------------- sessions

    def load_session(self, scope: Scope, session_id: str) -> tuple[dict | None, list, int]:
        row = self.conn.execute("SELECT ledger, history, version FROM sessions WHERE store_id = ? AND session_id = ?",
                                (scope.store_id, session_id)).fetchone()
        if not row:
            return None, [], 0
        return json.loads(row["ledger"]), json.loads(row["history"]), row["version"]

    def save_session(self, scope: Scope, session_id: str, ledger: dict, history: list, expected_version: int) -> int:
        """Optimistic write: fails if another request saved this session meanwhile."""
        with self.tx() as c:
            row = c.execute("SELECT version FROM sessions WHERE store_id = ? AND session_id = ?", (scope.store_id, session_id)).fetchone()
            current = row["version"] if row else 0
            if current != expected_version:
                raise ConcurrentUpdate(f"session changed (version {current}, expected {expected_version})")
            c.execute("INSERT OR REPLACE INTO sessions(store_id, session_id, ledger, history, version, updated_at) VALUES (?,?,?,?,?,?)",
                      (scope.store_id, session_id, json.dumps(ledger), json.dumps(history), current + 1, time.time()))
            return current + 1

    # -------------------------------------------------------------- baskets

    def load_basket(self, scope: Scope, session_id: str) -> tuple[list[dict], int]:
        row = self.conn.execute("SELECT lines, revision FROM baskets WHERE store_id = ? AND session_id = ?",
                                (scope.store_id, session_id)).fetchone()
        return (json.loads(row["lines"]), row["revision"]) if row else ([], 0)

    def save_basket(self, c: sqlite3.Connection, scope: Scope, session_id: str, lines: list[dict], revision: int) -> None:
        c.execute("INSERT OR REPLACE INTO baskets(store_id, session_id, revision, lines, updated_at) VALUES (?,?,?,?,?)",
                  (scope.store_id, session_id, revision, json.dumps(lines), time.time()))

    def find_op(self, c: sqlite3.Connection, scope: Scope, session_id: str, key: str) -> dict | None:
        row = c.execute("SELECT result FROM basket_ops WHERE store_id = ? AND session_id = ? AND idempotency_key = ?",
                        (scope.store_id, session_id, key)).fetchone()
        return json.loads(row["result"]) if row else None

    def record_op(self, c: sqlite3.Connection, scope: Scope, session_id: str, key: str, result: dict) -> None:
        c.execute("INSERT INTO basket_ops(store_id, session_id, idempotency_key, result, created_at) VALUES (?,?,?,?,?)",
                  (scope.store_id, session_id, key, json.dumps(result), time.time()))


class ConcurrentUpdate(Exception):
    pass


def _fts_words(text: str) -> list[str]:
    from .text import tokens

    return [w for w in tokens(text) if len(w) > 1]
