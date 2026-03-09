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
| `add_to_cart` | Search + add a single item (handles weight-based via product page fallback) |
| `add_grocery_list` | Batch add multiple items (handles quantities, weight-based, and delays) |
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

## Relevance Scoring

To avoid wrong matches (e.g., "banana" matching frozen banana snacks), the server uses keyword overlap scoring:

1. All search results are scored by how many query words appear in the title
2. Results sorted by score descending
3. If the best match has ATC, use it directly
4. If a lower-ranked ATC result scores >= 0.75, use that instead
5. Otherwise, fall back to product page for the best match's ASIN

## Cart Management

### Removing items
`remove_from_cart` reloads the cart page each time and uses Playwright's native `.click()` (not JS `.click()`) to reliably trigger Amazon's delete handlers. Verifies the item is gone before returning success.

### Clearing the cart
`clear_cart` uses JS `.click()` to click the "Clear cart" link, waits for the confirmation dialog, then clicks "Clear" to confirm. JS clicks are used here to avoid Playwright's pointer-event interception issues with modal overlays.

## Parallel Adding Strategy

When adding multiple items, launch parallel agents (up to 6 at a time) each calling `add_to_cart` for a single item. This is much faster than `add_grocery_list` which processes sequentially.

```
User: "Add these 12 items"
  Batch 1 (6 agents in parallel):
    Agent 1: add_to_cart("banana fresh conventional", qty=5)
    Agent 2: add_to_cart("organic fuji apple", qty=5)
    Agent 3: add_to_cart("Honey Nut Cheerios family size")
    Agent 4: add_to_cart("Oatly oat milk 64 oz")
    Agent 5: add_to_cart("Guinness non alcoholic stout 4 pack")
    Agent 6: add_to_cart("Tony's Chocolonely milk chocolate 32%")
  Batch 2 (remaining 6 agents in parallel):
    Agent 7-12: ...
```

Each `add_to_cart` creates its own browser page via `_new_wf_page()`, so there are no CSRF token conflicts. Cap at 6 concurrent agents to avoid Amazon rate limiting.

Use `add_grocery_list` as a fallback if agents aren't available or for small lists (3 items or fewer).

### Parallel Searching

The same pattern works for searches. When comparing options across categories (e.g., "show me NA beers, olive oils, and cereals"), launch parallel agents each calling `search_whole_foods`. For deeper product info, agents can call `get_product_details` with specific ASINs to get full descriptions, feature bullets, and size details from the product page.

### Visual Product Inspection

Use `screenshot_product` or `screenshot_search` to take screenshots, then view them with the Read tool. Screenshots are saved to temp files and can be viewed since Claude is multimodal. **Only use screenshots when needed to resolve ambiguity** — not for routine searches.

## Search Query Tips

| Item Type | Recommended Query Pattern | Notes |
|---|---|---|
| Fresh produce (weight-based) | `banana fresh conventional` | Added via product page |
| Fresh meat (weight-based) | `organic boneless skinless chicken breast fresh Mary's` | Added via product page |
| Pre-packaged items | `Tillamook extra sharp white cheddar cheese block 8 oz` | Has ATC in search |
| Store-brand items | `365 whole foods minced garlic 4.5 oz` | Search with "365" prefix |
| Instacart store-brands | Search for the generic product type | Will get WF/365 brand |

**Key tips:**
- Be specific: include brand, size, and "fresh"/"organic" when relevant
- Weight-based items are handled automatically — no need for workarounds
- For quantities > 1, the API accepts a `quantity` field; falls back to re-searching for fresh CSRF tokens per add if that fails
- 400ms delay between items to avoid rate limiting

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
