# Sauda: grounded shopping assistant for retailers

Customers say what they need in English, Roman Urdu, Urdu or a mix ("biryani for 6", "hafte ka sauda 4 logon ke liye, budget 8000", "Olpers nahi, koi aur doodh"). Sauda works out the task, finds suitable products, helps the customer choose, plans within budget and manages the basket. Every claim in its replies is checked against what the store actually reported.

This is a new implementation built from the project brief. It follows the brief's direction: one production agent with well-defined tools, application-enforced contracts, a single authoritative task state, shared suitability validation, tenant-scoped retrieval, grounded responses and journey tests.

## How a message flows

```
customer message
  → store resolved from the X-Store-Key header (never from the model)
  → session ledger + basket loaded (SQLite, scoped to the store)
  → Claude sees: recent conversation (text) + this message + a fresh "authoritative state" system message
  → Claude calls tools; application code does the work:
       update_needs     record / correct needs, household, budget        (validated against the taxonomy)
       find_products    per-need search → status + suitable options      (kind gate + shared suitability check)
       choose_products  propose product + packs; totals & budget computed by code
       show             choose which cards appear (options / plan / comparison / basket)
       update_basket    only when the customer asks; revisioned, idempotent
       browse_catalog   paginated "what do you have"
  → grounding check: every Rs amount and every "added to basket" claim must match tool results;
    otherwise Claude corrects the reply once before the customer sees it
  → cards built from the ledger/basket (never from the reply text), ledger saved with a version check
```

## How the brief's lessons are enforced

| Lesson from the brief | Where it's enforced |
|---|---|
| 1. "budget", "week", "eatable" are task words, not products | Needs must name a taxonomy kind; `update_needs` rejects anything else. Budget, household and purpose are separate fields. |
| 2. Chocolate spread / nutrition powder aren't milk | Every product is classified into a kind at ingest (`text.classify`). A product can only fill a need whose kinds accept it (`suitability.check`), and that rule runs in search, selection, cards and basket. |
| 3. Potato snacks aren't fresh potatoes | Same kind gate: `snacks.chips` ≠ `produce.potato`; "chips/crisps/fries" veto the potato kind at classification. |
| 4. Chaat/fries masala isn't biryani masala | Separate kinds. A related kind can only be offered as an explicit, labelled substitute (`allow_substitutes`). |
| 5. Missing data vs retrieval failure vs rejection | `find_products` returns `not_in_catalog`, `none_eligible` (with counts per reason: out of stock, constraint, brand…) or `only_substitutes`. Tool failures come back as errors. |
| 6. Correcting one need preserves the others | Needs have stable ids; corrections update one need and re-validate only its candidates and choice. |
| 7. Messages, cards, quantities and totals agree | Totals are computed in code; cards are built from the ledger; the grounding check rejects amounts no tool reported. |
| 8. Finding ≠ completing the task | The ledger tracks each need: open → options → chosen / missing / deferred. |
| 9. A plan isn't a basket change | `choose_products` only proposes. The basket changes through `update_basket` (on request) or card buttons; "added" claims without a basket change are caught. |
| 10. Narrow tests aren't readiness | `evals/journeys.py` runs multi-turn conversations against the real model and checks what the customer sees, with `--repeat` for run-to-run variance. |

The basket mismatch after reload is fixed by design. The server holds the basket, every change carries the last-seen revision and an idempotency key, a stale write returns 409 with the current basket, and the page always re-renders from the server's answer.

## Run it

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...            # or: ant auth login
SAUDA_DEMO=1 uvicorn sauda.server:app   # seeds "Demo Mart" from data/sample_pk_grocery.csv
# open http://localhost:8000
```

Your own store:

```bash
python -m sauda.cli add-store --retailer acme --store acme-khi --store-name "Karachi" --key <publishable-key>
python -m sauda.cli sync --key <publishable-key> --source catalog.csv     # or JSON, or a Shopify / WooCommerce URL
python -m sauda.cli stats --key <publishable-key>                         # includes how many products couldn't be classified
python -m sauda.cli chat --key <publishable-key>                          # terminal chat
```

The chat page takes `?store=<publishable-key>`. Admin sync over HTTP (`POST /api/admin/sync`) needs `SAUDA_ADMIN_KEY`.

Settings: `SAUDA_DB` (default `sauda.db`), `SAUDA_MODEL` (default `claude-opus-5-5`), `SAUDA_EFFORT` (default `medium`).

## Endpoints

| | |
|---|---|
| `POST /api/chat`, `POST /api/chat/stream` | Chat. The stream sends `status` events ("Looking for milk, eggs…") then one `result`, which goes out only after the grounding check. |
| `GET/POST /api/basket/{session}` | Basket view and changes (`expected_revision`, `idempotency_key`). |
| `GET /api/session/{session}` | Recent conversation, so a reload continues where the customer left off. |
| `GET /api/store` | Store name and catalog stats. |
| `GET /health`, `GET /ready`, `GET /metrics` | Liveness; readiness (database, model credentials, a store with a catalog); turn counts, latency, tokens, grounding corrections. |

Limits: 1,000 characters per message, 20 messages per minute per session, one turn at a time per session, 12 model calls and 120 seconds per turn.

## Catalog and sync

- **Sources:** CSV, JSON or JSONL feeds (files or URLs), Shopify `/products.json`, WooCommerce Store API. Column names are matched flexibly (`title`, `variant price`, `inventory`…). Other systems need a connector.
- **Sync jobs:** a sync is a full snapshot written in checkpointed batches. Products missing from the snapshot are unpublished, and the search index is rebuilt in one final transaction, so customers never see half an import. Failed jobs can be resumed with `--resume-job`.
- **Classification:** products are classified into ~90 kinds by deterministic rules with English, Roman Urdu and Urdu keywords and veto words (`sauda/taxonomy.py`). Anything ambiguous becomes `unknown`, which is never offered for a need and is counted in `stats` for review.
- **Sample catalog:** `data/sample_pk_grocery.csv` has 143 illustrative products (real brand names, made-up prices). It deliberately includes the traps from the brief.

## Tests

```bash
python -m pytest -q                                 # 30 tests, no network, ~7 s
ANTHROPIC_API_KEY=... python evals/journeys.py      # live journeys against the real model (spends usage)
```

The offline tests use the real database, catalog, suitability rules, basket and API. Claude is replaced by a scripted stand-in, so they prove the application's contracts: suitability traps, corrections, budgets, totals, basket revisions, tenant isolation, sync, grounding corrections and the HTTP API. They don't prove how well the model interprets customers. That's what the live journeys are for.

## Status and known gaps

- **The live journeys haven't been run yet.** They need an API key. Run them before trusting the interpretation quality, ideally with `--repeat 3`.
- **No vector search.** Retrieval is a deterministic kind gate plus BM25 ranking and a value preference. Claude does the multilingual interpretation (Roman Urdu or Urdu to kinds and English terms), so search doesn't depend on embedding quality. A vector ranker could be added later to rank inside the kind gate.
- **Unknown products aren't auto-classified.** Products the rules can't place stay `unknown` and are excluded. The next step is a model-assisted classifier that writes back to the products table, with review.
- **Quantities are estimates.** Household quantities use rough weekly per-person amounts per kind, and the assistant calls them estimates.
- **No Imtiaz connector.** The Imtiaz site couldn't be reached from the build environment. A connector for it needs its product API or a feed.
- **Customer identity is not built yet.** A session id identifies the customer's basket. Production needs real customer authentication tied to sessions.
- **Checkout and payments are disabled.**
