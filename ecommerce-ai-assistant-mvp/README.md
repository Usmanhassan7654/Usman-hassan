# Ecommerce AI Assistant MVP

An AI shopping assistant for grocery stores. Customers chat in plain language and the assistant:

1. **Shops by budget.** "I have $50. Suggest groceries for the week." It builds a balanced cart of weekly basics that never goes over the budget, and follows brand preferences ("I like Green Valley", "no Harvest Farm").
2. **Shops by recipe.** "I want to cook chicken pasta for four people." It finds every ingredient and the app works out the packs from the amounts per serving (4 × 150 g chicken = 600 g = 2 packs of 300 g). Pantry staples like salt, oil and spices aren't added automatically: the assistant asks whether you already have them, with an Add button for each.
3. **Finds products instantly.** "Show me gluten-free snacks under $10." It uses vector search with filters for price, diet and allergens, handles typos, and suggests alternatives when something is out of stock.
4. **Checks out inside the chat.** Cart, quantities and a demo payment, all in the conversation.

All prices and totals are calculated by the app, not by the AI.

## What's inside

- **200 products** in `data/products.json`, each with an id, name, brand, category, description, price, size, stock, rating, dietary tags, allergens, items it goes well with, and a vector (SVG) picture in `data/images/`. Brands are fictional and prices are illustrative. To change them, edit `scripts/make_dataset.py` and run `python scripts/make_dataset.py`.
- **Vector search** (`app/catalog.py`): every product becomes a vector of its words plus a vector of character pieces, so misspellings still match, plus AI embeddings (`fastembed`) for meaning-based matching ("something for breakfast"). The embedding model (about 70 MB) downloads once, on the first start, into `data/models/`. Without internet the search still works with the word and character vectors.
- **The assistant** (`app/agent.py`) runs on Groq's free API. It uses `openai/gpt-oss-120b`, and switches to `openai/gpt-oss-20b` when the big model is busy.

## Run it on your laptop

You need Python 3.10 or newer and a free Groq key from https://console.groq.com/keys.

1. Open a terminal in this folder.
2. Install (once):
   ```
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to a new file named `.env` and put your key after `GROQ_API_KEY=`.
4. Start:
   ```
   python run.py
   ```
   Your browser opens http://localhost:8000. Press Ctrl+C in the terminal to stop.

## Tests

```
pip install pytest
python -m pytest -q tests
```

## Putting it on your website later

`python run.py` serves the chat page and a small API (`/api/chat`, `/api/cart`, `/api/checkout`). To go live, host this folder on a server (any Python host) and either link to the page or embed it in your site with an `<iframe>`. Before using it with real customers, add real products, real payment, and customer accounts. Carts are currently kept in memory and reset when the server restarts.
