# Whole Foods MCP Server

An [MCP](https://modelcontextprotocol.io) server that automates grocery ordering from Amazon Whole Foods Market. Uses [Playwright](https://playwright.dev/python/) for browser automation and exposes tools for searching products, managing your cart, and batch-adding items.

Built to work with [Claude Code](https://claude.ai/code) — say "add bananas, oat milk, and chicken breast to my cart" and it handles the rest.

## Prerequisites

- **Python 3.11+**
- **[uv](https://docs.astral.sh/uv/)** — Python package manager. Install with `curl -LsSf https://astral.sh/uv/install.sh | sh`
- **An Amazon account** with Whole Foods delivery set up for your address

## Getting Started

### 1. Clone and install

```bash
git clone https://github.com/benjiebob/whole-foods-mcp.git
cd whole-foods-mcp
uv sync
uv run playwright install chromium
```

### 2. Connect to Claude Code

Start Claude Code from the project directory:

```bash
cd whole-foods-mcp
claude
```

The included `.mcp.json` configures the MCP server automatically — no extra setup needed.

### 3. Log in to Amazon

On first use, you need to authenticate your Amazon session:

1. In Claude Code, say: **"log in to Amazon"**
2. A browser window will open to the Amazon sign-in page
3. Log in with your credentials and complete any 2FA prompts
4. Make sure your Whole Foods delivery address is selected (check the top-left of amazon.com)
5. Say: **"save session"** — this persists your login so you don't have to repeat it

Your session is saved locally in `.browser_state/` (gitignored). You'll only need to re-login if your session expires.

### 4. Start shopping

Now you can use natural language:

- *"Search for organic oat milk"*
- *"Add 5 bananas and a dozen eggs to my cart"*
- *"What's in my cart?"*
- *"Remove the cheerios from my cart"*

## Demo

Here's an example session — ordering ingredients for a chicken curry:

```
> please add the items I need to make a chicken curry

I'll add the ingredients for a chicken curry to your Whole Foods cart. Let me search
and add each item.

Adding 6 items in parallel...

✓ Added: Mary's Chicken Breast Boneless Skinless (~1lb) — $9.99/lb
✓ Added: 365 Organic Coconut Milk 13.5oz — $2.49
✓ Added: Yellow Onion — $2.99/lb
✓ Added: 365 Minced Garlic 4.5oz — $2.99
✓ Added: Fresh Ginger Root — $6.99/lb
✓ Added: 365 Organic Curry Powder 1.8oz — $3.49

All 6 items added to your cart. Want me to add rice or naan bread to go with it?

> yeah add some jasmine rice and naan

Adding 2 items...

✓ Added: Lundberg Organic California White Jasmine Rice 2lb — $6.99
✓ Added: Stonefire Original Naan Bread 2ct — $4.49

Done! Your cart now has 8 items for the chicken curry.

> what's in my cart?

Your Whole Foods cart (8 items, subtotal $40.42):

1. Mary's Chicken Breast Boneless Skinless — $9.99
2. 365 Organic Coconut Milk — $2.49
3. Yellow Onion — $2.99
4. 365 Minced Garlic — $2.99
5. Fresh Ginger Root — $6.99
6. 365 Organic Curry Powder — $3.49
7. Lundberg Jasmine Rice 2lb — $6.99
8. Stonefire Original Naan Bread — $4.49
```

> **Note:** On first run, Claude will prompt you to log in to Amazon before adding items. See [step 3](#3-log-in-to-amazon) above.

## Tools

| Tool | Description |
|---|---|
| `login` | Open browser for Amazon login |
| `save_session` | Persist session cookies to disk |
| `search_whole_foods` | Search products with prices and availability |
| `add_to_cart` | Search and add an item (handles weight-based products automatically) |
| `add_grocery_list` | Batch add multiple items in one call |
| `view_cart` | View current cart contents |
| `remove_from_cart` | Remove an item by ASIN |
| `clear_cart` | Clear all cart items |
| `get_product_details` | Get full product page details (description, size, features) |
| `screenshot_product` | Screenshot a product page for visual inspection |
| `screenshot_search` | Screenshot search results for visual inspection |
| `open_product_page` | Open a product page for manual interaction |

## How It Works

1. Maintains an authenticated Amazon session via Playwright (headless Chromium)
2. Searches Whole Foods using Amazon's search API
3. Extracts add-to-cart payloads from search results (or product pages for weight-based items)
4. POSTs to Amazon's fresh cart API to add items
5. Uses relevance scoring to avoid wrong matches

Weight-based items (produce, fresh meat) are handled automatically — the server falls back to the product page to find the add-to-cart payload when it's missing from search results.
