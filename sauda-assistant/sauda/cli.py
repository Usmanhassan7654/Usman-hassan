"""Command line: set up stores, sync catalogs, chat in the terminal.

    python -m sauda.cli add-store --retailer demo-mart --store demo-khi --key demo-store-key
    python -m sauda.cli sync --key demo-store-key --source data/sample_pk_grocery.csv
    python -m sauda.cli stats --key demo-store-key
    python -m sauda.cli chat --key demo-store-key [--llm groq,gemini]
    python -m sauda.cli models groq            # model ids your key can use
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
    c.add_argument("--llm", help="provider chain, e.g. 'groq,gemini' or 'gemini:gemini-flash-latest' (default: SAUDA_LLM or every provider with a key)")
    c.add_argument("--effort", default="medium", help="Claude only")
    m = sub.add_parser("models", help="list the models your Groq or Gemini key can use")
    m.add_argument("provider", choices=["groq", "gemini", "cerebras", "openrouter", "mistral"])
    args = p.parse_args(argv)

    if args.cmd == "models":
        from . import llm

        key = llm._key(args.provider)
        if not key:
            print(f"Set {' or '.join(llm.KEY_VARS[args.provider])} first.", file=sys.stderr)
            return 2
        print("\n".join(llm.OpenAICompatModel(args.provider, "", key).list_models()))
        return 0
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
        from . import llm
        from .agent import Agent

        model = llm.build(args.llm, effort=args.effort)
        agent, session = Agent(repo, model=model), uuid.uuid4().hex
        print(f"{repo.store_name(scope)} via {model.name} — type what you need. Ctrl-C to quit.\n")
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
