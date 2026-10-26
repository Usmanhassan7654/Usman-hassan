"""Command line: set up stores, sync catalogs, chat in the terminal.

    python -m sauda.cli add-store --retailer demo-mart --store demo-khi --key demo-store-key
    python -m sauda.cli sync --key demo-store-key --source data/sample_pk_grocery.csv
    python -m sauda.cli stats --key demo-store-key
    python -m sauda.cli chat --key demo-store-key
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid

from . import ingest
from .db import Repo


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="sauda")
    p.add_argument("--db", default="sauda.db")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add-store")
    a.add_argument("--retailer", required=True)
    a.add_argument("--retailer-name")
    a.add_argument("--store", required=True)
    a.add_argument("--store-name")
    a.add_argument("--key", required=True, help="publishable store key used by the chat widget")
    a.add_argument("--currency", default="PKR")
    s = sub.add_parser("sync")
    s.add_argument("--key", required=True)
    s.add_argument("--source", required=True, help="CSV/JSON file or URL, or a Shopify/WooCommerce store URL")
    s.add_argument("--resume-job", type=int)
    st = sub.add_parser("stats")
    st.add_argument("--key", required=True)
    c = sub.add_parser("chat")
    c.add_argument("--key", required=True)
    c.add_argument("--model", default="claude-opus-5-5")
    c.add_argument("--effort", default="medium")
    args = p.parse_args(argv)

    repo = Repo(args.db)
    if args.cmd == "add-store":
        scope = repo.add_store(args.retailer, args.retailer_name or args.retailer, args.store, args.store_name or args.store, args.key, args.currency)
        print(f"Store ready: {scope}")
        return 0
    scope = repo.scope_for_key(args.key)
    if not scope:
        print("Unknown store key.", file=sys.stderr)
        return 2
    if args.cmd == "sync":
        print(json.dumps(ingest.sync(repo, scope, args.source, resume_job=args.resume_job), indent=1))
    elif args.cmd == "stats":
        print(json.dumps(repo.catalog_stats(scope), indent=1))
    elif args.cmd == "chat":
        from .agent import Agent

        agent, session = Agent(repo, model=args.model, effort=args.effort), uuid.uuid4().hex
        print(f"{repo.store_name(scope)} — type what you need. Ctrl-C to quit.\n")
        while True:
            try:
                text = input("you> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if not text:
                continue
            r = agent.handle(scope, session, text, emit=lambda e: print(f"  … {e['text']}", file=sys.stderr))
            print(f"\nsauda> {r.reply}\n")
            for card in r.cards:
                if card["type"] == "plan":
                    for l in card["lines"]:
                        print(f"   {l['packs']} x {l['name']}  Rs {l['line_total']:,.0f}")
                    print(f"   Total Rs {card['total']:,.0f}\n")
                elif card["type"] == "options":
                    for g in card["groups"]:
                        print(f"   {g['label']}:")
                        for o in g["options"]:
                            print(f"     {o['ref']}. {o['name']}  Rs {o['price']:,.0f}")
                    print()
            if r.basket["items"]:
                print(f"   Basket: {r.basket['item_count']} items, Rs {r.basket['total']:,.0f}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
