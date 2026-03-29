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

- `server.py` — MCP server with tool definitions and browser management
- `js/` — JavaScript helpers injected into browser pages
  - `search.js` — Product search (returns ASINs, titles, prices)
  - `add_to_cart.js` — Fetches product page ATC payload and POSTs to cart
  - `product_details.js` — Extracts full product info from product page
  - `view_cart.js` — Parses cart page for items and quantities
  - `clear_cart_click.js` — Dismisses modals and clicks "Clear cart"
  - `clear_cart_find_button.js` — Finds the clear cart button
  - `clear_cart_confirm.js` — Confirms the clear cart dialog
- `.browser_state/` — Persisted Playwright session (gitignored, created at runtime)
- `manifest.json` — MCPB bundle manifest for Claude Desktop distribution

## Architecture

### Amazon Whole Foods API Flow

1. **Search**: `GET /s?k={query}&i=wholefoods` → HTML with product data
2. **Product page**: `GET /dp/{ASIN}?almBrandId=VUZHIFdob2xlIEZvb2Rz` → full details + ATC payload
3. **Add to cart**: `POST /alm/addtofreshcart` with the extracted JSON payload
4. **Cart**: `https://www.amazon.com/cart/localmarket?almBrandId=VUZHIFdob2xlIEZvb2Rz`

Brand ID `VUZHIFdob2xlIEZvb2Rz` (base64 "UFG Whole Foods") is used across all endpoints. CSRF tokens are per-page-load and session-bound.

### Tool Responsibilities

Each tool has a clear, single responsibility:

| Tool | Reads | Writes | Purpose |
|------|-------|--------|---------|
| `login` | — | Browser state | Opens visible browser for Amazon sign-in |
| `save_session` | Browser state | `.browser_state/state.json` | Persists cookies, switches to headless |
| `search_whole_foods` | Search results | — | Find products (read-only, no side effects) |
| `get_product_details` | Product page | Screenshot file | Deep dive: text details + product image |
| `add_to_cart` | Product page | Cart | Adds item by ASIN (fetches fresh ATC token) |
| `view_cart` | Cart page | — | Read current cart contents |
| `remove_from_cart` | Cart page | Cart | Remove specific item by ASIN |
| `clear_cart` | Cart page | Cart | Clear entire cart |

**Key design decisions:**

- `search_whole_foods` is purely read-only — it never touches the cart
- `add_to_cart` always fetches the product page directly for a fresh ATC token — it does not depend on search results
- `get_product_details` combines structured data extraction AND a screenshot in one call, so the agent can both read details and see the product image

### Browser Session Management

Playwright runs headless Chromium (or Chrome if installed) with a shared context. Session state (cookies, storage) is saved to `.browser_state/state.json` and restored on restart. First use requires `login` → manual Amazon login → `save_session`.

**Page management:**

- `_get_main_page()` — shared page for cart/login navigation
- `_new_wf_page()` — fresh page per search/add operation (parallel-safe, fresh CSRF tokens)

**Browser selection:**

- Tries Chrome first (`channel="chrome"`) for password manager / extension support
- Falls back to Playwright's bundled Chromium if Chrome isn't installed

### Weight-Based Items

Weight-based items (bananas, chicken, apples) lack `data-fresh-add-to-cart` in search results but DO have it on their product pages. Since `add_to_cart` always fetches the product page directly, this is handled automatically.

### Parallel Strategy

When adding multiple items, Claude can run agents in parallel:

1. **Search in parallel**: Multiple agents each calling `search_whole_foods`
2. **Evaluate results**: Pick the right ASIN for each item
3. **Add in parallel**: Multiple agents each calling `add_to_cart`

Each `add_to_cart` creates its own browser page via `_new_wf_page()`, so there are no CSRF token conflicts. Cap at 6 concurrent agents.

## Search Query Tips

| Item Type | Good Query | Bad Query |
|-----------|-----------|-----------|
| Fresh produce | `banana`, `apple` | `organic fuji apple fresh produce` |
| Fresh meat | `chicken thighs` | `organic boneless skinless chicken thighs fresh` |
| Pre-packaged | `cheerios`, `oatly oat milk` | Works fine with more words |
| Store-brand | `365 orange juice` | `365 whole foods organic no pulp OJ 52 fl oz` |

## MCPB Distribution

The server can be packaged as a `.mcpb` file for one-click installation in Claude Desktop:

```bash
npm install -g @anthropic-ai/mcpb
mcpb pack . whole-foods-mcp.mcpb
```

Users install by double-clicking the `.mcpb` file. `uv` handles Python + dependency installation automatically on first run.

## Reference

- Whole Foods brand ID (base64): `VUZHIFdob2xlIEZvb2Rz`
- Add to cart endpoint: `POST /alm/addtofreshcart`
- Whole Foods home: `https://www.amazon.com/?i=wholefoods`
- Cart URL: `https://www.amazon.com/cart/localmarket?almBrandId=VUZHIFdob2xlIEZvb2Rz`
- Search URL pattern: `https://www.amazon.com/s?k={query}&i=wholefoods`
- Product page with WF context: `https://www.amazon.com/dp/{ASIN}?almBrandId=VUZHIFdob2xlIEZvb2Rz`
