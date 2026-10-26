# AI Shopping Assistant

A shopping agent built on Claude. The customer types what they need in plain language, for example:

> "Groceries for a week of breakfasts for two, budget $20"
> "Ingredients for chicken biryani for 6"
> "We're out of cleaning stuff"

From there the agent:

1. **Works out what you mean.** It turns a vague need into a concrete shopping list with sensible quantities (a recipe's ingredients, the usual breakfast items, cleaning basics).
2. **Searches the catalog** once per item, tries other words when a search comes back empty, and respects your budget, dietary needs, brands and household size.
3. **Fills the cart itself** and tells you what it picked and why. It suggests substitutes for anything that's missing or out of stock.
4. **Shows products as cards in the chat**, with the store's picture, price and an Add button that turns into a − / + quantity stepper. Items it adds appear as cards automatically, and when you need to choose (which cooking oil, which brand) it shows the options as cards. Button clicks change the cart instantly without waiting for Claude, and Claude is told about them with your next message. Products without a picture get a tile with their initials.
5. **Takes you through checkout**: name, address, delivery slot and payment method. It shows an order summary and **places the order only after you confirm it in your next message**. The code enforces this rule, so it doesn't rely on the prompt alone.

## Product data sources

| Source | Example |
|---|---|
| CSV file (`,` `;` tab or `|` separated; flexible column names such as `title`, `variant price`, `product_type`, `inventory`) | `data/sample_grocery.csv` |
| JSON / JSONL file (plain list, `{"products": [...]}`, or a Shopify `products.json` export) | `products.json` |
| Shopify store URL (reads `/products.json`) | `https://store.example.com` |
| WooCommerce store URL (reads the Store API) | `https://shop.example.com` |
| Any page with schema.org `Product` JSON-LD (also follows product links from listing pages) | `https://shop.example.com/category/fruit` |
| A direct CSV/JSON feed URL | `https://example.com/feed.csv` |

Only scrape sites whose terms allow automated access.

## Run it

```bash
cd shopping-agent
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...      # or: ant auth login

# Web chat UI with a live cart, file upload and store-URL loader
CATALOG_SOURCE=data/sample_grocery.csv uvicorn shopping_agent.server:app --reload
# open http://localhost:8000

# Or use the terminal
python -m shopping_agent.cli --source data/sample_grocery.csv
python -m shopping_agent.cli --source https://some-shopify-store.com --verbose
```

Environment variables for the server: `CATALOG_SOURCE`, `ORDERS_PATH` (default `orders.jsonl`), `SHOPPING_MODEL` (default `claude-opus-5-5`), `SHOPPING_EFFORT` (default `medium`).

## How it works

```
customer message
      │
      ▼
ShoppingAgent.chat()  ── Claude (tool use loop) ──►  tools
                                                      ├─ search_products / get_product_details / list_categories
                                                      ├─ show_products (cards with pictures and Add buttons)
                                                      ├─ add_to_cart / update_cart_item / remove_from_cart / view_cart
                                                      ├─ save_preferences (budget, dietary, household size)
                                                      ├─ prepare_checkout  → summary, nothing placed yet
                                                      └─ place_order       → only allowed in a later turn
```

| File | Role |
|---|---|
| `shopping_agent/catalog.py` | `Product` model, CSV/JSON loaders, and search (synonyms, plurals, filters, sorting) |
| `shopping_agent/scraper.py` | Website loaders: Shopify, WooCommerce, JSON-LD and direct feeds |
| `shopping_agent/cart.py` | Cart rules (stock limits, quantities, totals) and `OrderStore` |
| `shopping_agent/agent.py` | System prompt, tool definitions, tool implementations and the Claude loop |
| `shopping_agent/server.py`, `static/index.html` | FastAPI web chat with one session per browser tab |
| `shopping_agent/cli.py` | Terminal chat |

Claude API details: the model is `claude-opus-5-5` with effort `medium` and prompt caching. The server-side refusal fallback (`fallbacks: "default"`) is turned on, so a request that the safety filters decline is retried on Anthropic's recommended fallback model instead of failing. If you'd rather not use it, remove the `betas` and `fallbacks` lines in `ShoppingAgent._create`.

## Going live

The default `OrderStore.place()` writes each order to `orders.jsonl`. To take real orders, replace it with a call to your store's checkout or order API, such as the Shopify Admin API, WooCommerce REST or Stripe Checkout. Payment details should stay with your payment provider; the agent never handles them.

## Tests

```bash
python -m pytest -q
```

The tests cover the loaders, search quality, cart rules and the full agent flow, including the rule that blocks placing an order before the customer confirms. They use a scripted fake Claude client, so they run with no network and no API key.
