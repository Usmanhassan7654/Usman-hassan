# Usman Hasan — Agent Systems Lab

A deployable portfolio containing seven working agent prototypes:

- 3 sales agents: Haramain Gifts, HB Innovations, and Al Midrar Institute
- 1 call-handling agent: fictional insurance incident desk
- 3 lead-generation agents: AI services, commercial solar, and dairy B2B

## Why the demos do not hallucinate

The public prototype uses deterministic JavaScript handlers rather than unconstrained generation. Every answer is restricted to a versioned knowledge record, exposes the exact evidence used, and refuses unsupported prices, status claims, delivery commitments, or catalogue items. Lead examples are labelled synthetic and outbound messages require human verification.

## Run locally

```bash
python -m http.server 8000 --directory dist
```

Open `http://localhost:8000`.

## Structure

- `dist/index.html` — semantic interface
- `dist/styles.css` — responsive visual system
- `dist/app.js` — knowledge bases, agent policies, scoring, and UI behavior
- `.openai/hosting.json` — Sites deployment configuration

## Production upgrade path

Replace the in-browser knowledge records with authenticated backend tools, a vector store for approved documents, observability, user authentication, and human approval gates. An LLM may be added for language understanding, but prices, lead scores, fulfilment, claims, and commitments should remain tool-controlled.
