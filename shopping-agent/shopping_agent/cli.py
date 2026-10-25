"""Terminal chat with the shopping agent.

    python -m shopping_agent.cli --source data/sample_grocery.csv
    python -m shopping_agent.cli --source https://some-shopify-store.com
"""

from __future__ import annotations

import argparse
import sys

from .agent import MODEL, ShoppingAgent
from .cart import OrderStore
from .catalog import load_source


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI shopping assistant")
    parser.add_argument("--source", default="data/sample_grocery.csv",
                        help="CSV/JSON file or e-commerce website URL with the products")
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--effort", default="medium", choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--orders", default="orders.jsonl", help="Where placed orders are written")
    parser.add_argument("--verbose", action="store_true", help="Show the agent's tool calls")
    args = parser.parse_args(argv)

    print(f"Loading products from {args.source} ...")
    catalog = load_source(args.source)
    print(catalog.summary(), "\n")

    agent = ShoppingAgent(catalog, model=args.model, effort=args.effort, orders=OrderStore(args.orders))

    def on_event(kind: str, data: dict) -> None:
        if not args.verbose:
            if kind == "tool_call":
                print(f"  ... {data['name'].replace('_', ' ')}", file=sys.stderr)
            return
        print(f"  [{kind}] {data}", file=sys.stderr)

    print("Tell me what you need (e.g. 'groceries for a pasta night for 4 under $30'). Ctrl-C to quit.\n")
    while True:
        try:
            user = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not user:
            continue
        reply = agent.chat(user, on_event=on_event)
        print(f"\nassistant> {reply}\n")
        if agent.session.last_order:
            order = agent.session.last_order
            print(f"[Order {order['order_id']} saved to {args.orders}]\n")
            agent.session.last_order = None


if __name__ == "__main__":
    raise SystemExit(main())
