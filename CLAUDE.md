# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

MCP server that automates adding grocery items to an Amazon Whole Foods Market cart. Uses Playwright for browser automation and exposes tools via the Model Context Protocol.

## Commands

```bash
uv run python server.py          # Run the MCP server (stdio transport)
uv run mcp dev server.py          # Run with MCP Inspector for debugging
uv run playwright install chromium # Install/update browser
```

## Project Structure

- `server.py` — MCP server with all tools and browser automation logic
- `.browser_state/` — Persisted Playwright session (gitignored, created at runtime)

## Architecture

### Amazon Whole Foods API Flow

1. **Search**: `GET /s?k={query}&i=wholefoods` — returns HTML with product data
2. **Extract payload**: Each result has a `<span data-action="fresh-add-to-cart">` element with a `data-fresh-add-to-cart` JSON attribute (contains ASIN, CSRF token, offer listing ID)
3. **Add to cart**: `POST /alm/addtofreshcart` with the extracted JSON payload
4. **Cart**: `https://www.amazon.com/cart/localmarket?almBrandId=VUZHIFdob2xlIEZvb2Rz`

Brand ID `VUZHIFdob2xlIEZvb2Rz` (base64 "UFG Whole Foods") is used across all endpoints. CSRF tokens are per-page-load and session-bound.

### MCP Tools

| Tool | Purpose |
|---|---|
| `login` | Opens browser to Amazon login page |
| `save_session` | Persists browser session to disk |
| `search_whole_foods` | Search products, returns top 10 with prices, ATC availability, and product URLs |
| `add_to_cart` | Add a specific ASIN to cart (requires query + ASIN from search_whole_foods; handles weight-based via product page fallback) |
| `add_grocery_list` | Batch add multiple items by ASIN (requires query + ASIN per item) |
| `view_cart` | Navigate to cart and return item summary with ASINs |
| `remove_from_cart` | Remove a specific item by ASIN (Playwright native click, verifies removal) |
| `clear_cart` | Clear all items via "Clear cart" button + confirmation dialog |
| `get_product_details` | Fetch full product description, features, size, and details from product page |
| `screenshot_product` | Take a screenshot of a product page (view with Read tool) |
| `screenshot_search` | Take a screenshot of search results (view with Read tool) |
| `open_product_page` | Open a product page for manual viewing/adding |

### Browser Session Management

Playwright runs a headless Chromium instance with a shared context. Session state (cookies, storage) is saved to `.browser_state/state.json` and restored on restart. First use requires `login` → manual Amazon login → `save_session`.

**Page management:**
- `_get_main_page()` — shared page for cart/login navigation tools
- `_new_wf_page()` — fresh page per search/add operation (enables parallel safety, fresh CSRF tokens)

### Whole Foods Home URL

`https://www.amazon.com/?i=wholefoods` — used as the base page for fresh search contexts. Do NOT use `?k=grocery&i=wholefoods` as it triggers a "grocery" search.

## Weight-Based Items

Weight-based items (bananas, fresh chicken, apples, pork chops, sweet potatoes) lack `data-fresh-add-to-cart` in **search results** but DO have it on their **product pages**. The server handles this automatically:

1. All search results are scored by relevance (keyword overlap)
2. If the best match lacks ATC, server fetches the product page HTML (`/dp/{ASIN}?almBrandId=...`)
3. Extracts the `data-fresh-add-to-cart` payload from the product page
4. POSTs to `/alm/addtofreshcart` as normal

This works for both `isItemSoldByCount: true` (per-each like bananas) and `isItemSoldByCount: false` (by-weight like chicken breast).

## Item Selection (Claude-in-the-loop)

The server does NOT auto-select items. The workflow is:

1. **Claude calls `search_whole_foods`** with a simple query → gets results with ASINs
2. **Claude evaluates** the results and picks the right ASIN
3. **Claude calls `add_to_cart`** with the specific query + ASIN

This avoids wrong matches (e.g., "banana" adding frozen banana snacks). The LLM's judgment is far better than keyword scoring for deciding if "Organic Sugarbee Apple" is a reasonable substitute for "Organic Fuji Apple".

## Cart Management

### Removing items
`remove_from_cart` reloads the cart page each time and uses Playwright's native `.click()` (not JS `.click()`) to reliably trigger Amazon's delete handlers. Verifies the item is gone before returning success.

### Clearing the cart
`clear_cart` uses JS `.click()` to click the "Clear cart" link, waits for the confirmation dialog, then clicks "Clear" to confirm. JS clicks are used here to avoid Playwright's pointer-event interception issues with modal overlays.

## Parallel Strategy

When adding multiple items, the workflow is:

1. **Search in parallel**: Launch parallel agents each calling `search_whole_foods` with simple queries
2. **Evaluate results**: Review all search results and pick the correct ASIN for each item
3. **Add in parallel**: Launch parallel agents each calling `add_to_cart(query, asin, qty)`

```
User: "Add these 12 items"
  Step 1 — Search (6 agents in parallel):
    Agent 1: search_whole_foods("banana")
    Agent 2: search_whole_foods("apple")
    Agent 3: search_whole_foods("cheerios")
    ...
  Step 2 — Evaluate results, pick ASINs
  Step 3 — Add (6 agents in parallel):
    Agent 1: add_to_cart("banana", "B07FYYKKQK", qty=5)
    Agent 2: add_to_cart("apple", "B07NQDTD7D", qty=5)
    ...
```

Each `add_to_cart` creates its own browser page via `_new_wf_page()`, so there are no CSRF token conflicts. Cap at 6 concurrent agents to avoid Amazon rate limiting.

Use `add_grocery_list` for batch adding when you already have all ASINs.

### Parallel Searching

The same pattern works for searches. When comparing options across categories (e.g., "show me NA beers, olive oils, and cereals"), launch parallel agents each calling `search_whole_foods`. For deeper product info, agents can call `get_product_details` with specific ASINs to get full descriptions, feature bullets, and size details from the product page.

### Visual Product Inspection

Use `screenshot_product` or `screenshot_search` to take screenshots, then view them with the Read tool. Screenshots are saved to temp files and can be viewed since Claude is multimodal. **Only use screenshots when needed to resolve ambiguity** — not for routine searches.

## Search Query Tips

**Use simple, short queries (1-2 words) for best results, especially produce:**

| Item Type | Good Query | Bad Query |
|---|---|---|
| Fresh produce | `banana`, `apple`, `nectarine` | `organic fuji apple fresh produce` |
| Fresh meat | `pork loin chop` | `organic boneless skinless pork loin chop fresh` |
| Pre-packaged | `cheerios`, `oatly oat milk` | Works fine with more words |
| Store-brand | `365 orange juice` | `365 whole foods organic no pulp OJ 52 fl oz` |

**Key tips:**
- Multi-word queries dilute produce results badly — keep it simple
- When an item isn't found, try related items as separate searches (peach → nectarine, plum)
- Weight-based items show `can_add_to_cart=false` in search but CAN be added via product page fallback
- HTTP 400 from `add_to_cart` means genuinely unavailable at the store
- Product page URLs require `fpw=alm&s=wholefoods` params for valid ATC data

## Limitations

- CSRF tokens expire with session — search results must be fresh
- Results are store-specific (depends on user's selected WF location)
- No price verification — adds best matching result by relevance score
- Some product page ATC payloads return 400 (rare)

## Reference

- Whole Foods brand ID (base64): `VUZHIFdob2xlIEZvb2Rz`
- Add to cart endpoint: `POST /alm/addtofreshcart`
- Whole Foods home: `https://www.amazon.com/?i=wholefoods`
- Cart URL: `https://www.amazon.com/cart/localmarket?almBrandId=VUZHIFdob2xlIEZvb2Rz`
- Search URL pattern: `https://www.amazon.com/s?k={query}&i=wholefoods`
- Product page with WF context: `https://www.amazon.com/dp/{ASIN}?almBrandId=VUZHIFdob2xlIEZvb2Rz`
