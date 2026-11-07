# R5: Gemini API and ETF prices (2026-11-07)

Research input for PLAN-v2. Checked against the official docs (ai.google.dev now redirects to aistudio.google.com/docs) and live endpoints.

## Gemini API
- **Models:**
  - `gemini-4-argon`: 1M-token context, 65K output. Good for planning and orchestration. Paid tier only; we use the event key.
  - `gemini-3.8-flash`: 1M context, much cheaper. Suits many parallel extraction calls.
  - `gemini-3.5-flash-lite`: cheapest.
  - Gemini 2.5 is deprecated (re-routed from 2026-12-01).
- **SDK:** `google-genai`, imported as `from google import genai`. Pin it to `>=2.31,<3`. Version 3.0.0 shipped 2026-11-06 with breaking changes (default API `v1`, default HTTP library `httpx2`), and its compatibility with the Interactions API is unconfirmed. The alternative is plain REST over our own `core/http`.
- **Key:** the `GEMINI_API_KEY` environment variable (`GOOGLE_API_KEY` wins if both are set). Local only and never committed. For REST, send it in the `x-goog-api-key` header, never in the URL.
- **Interactions API:** generally available since 2026-06 and the recommended interface. Use `client.interactions.create(model, input, system_instruction, generation_config, response_format, tools, store, background)` and read `.output_text`; the async form is `client.aio.interactions`.
- **Caching is implicit only.** There is no explicit caching on Argon or Interactions. The minimum cacheable prefix is 4,096 tokens, so put the large shared document first. Cached tokens are about 95% cheaper (`usage.total_cached_tokens`).
- **Thinking:** set `generation_config={"thinking_level": "low"|"medium"|"high"}`. Thinking tokens count against `max_output_tokens` (use ≥ 32K). Don't send temperature or top_p/top_k to Argon. Allow long client timeouts (15 min or more).
- **Structured output:** `response_format={"type":"text","mime_type":"application/json","schema": Model.model_json_schema()}`, then `Model.model_validate_json(it.output_text)`. **Keep schemas flat:** `anyOf` and `$ref` from nested or Optional Pydantic fields are unconfirmed, and overly complex schemas return 400.
- **Grounding:** Google Search grounding returns citation offsets into the *answer*, not quotes from the source. We don't use it for evidence; we fetch the documents ourselves and verify quotes.
- **Pricing (until 2026-11-30):** Argon $2 per 1M input and $10 per 1M output tokens; 3.8 Flash $0.75 / $3.75. Argon's rate limits are visible only in AI Studio.

## ETF prices (to turn shares into value)
- **Primary: TickerInside.**
  - `GET https://tickerinside.com/api/v1/fund/{ticker}.json` gives `last_close`, `last_close_date` and `currency`. `/api/v1/batch?funds=IVV,QQQ,...` covers up to 10 funds.
  - Use lowercase tickers; uppercase gets a 301.
  - Confirmed for IVV, QQQ, XLK, EEM, VTI, VXUS, SPY and VOO. IVV was 738.68 on 2026-11-06, and Yahoo, Nasdaq and iShares agree.
  - It's the **exchange close, not NAV** (IVV NAV was 738.70); say so in the UI.
  - Updated nightly after the US close. Prices "remain the data of their providers", so attribute them to TickerInside.
- **Stale handling:** warn when `last_close_date` is older than the previous trading day.
- **Rejected:** Yahoo, Nasdaq (unofficial; restrictive terms), Stooq (now behind a JavaScript challenge or key) and Alpha Vantage (needs a key). SEC N-PORT has net assets only, and is quarterly.
- **Display:** "IVV $738.68 × 120 shares = $88,641.60 · close 2026-11-06 · source: TickerInside". The arithmetic is done in Python, never by the model.
