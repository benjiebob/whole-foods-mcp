# Whole Foods MCP Server

An [MCP](https://modelcontextprotocol.io) server that automates grocery ordering from Amazon Whole Foods Market. Uses [Playwright](https://playwright.dev/python/) for browser automation and exposes tools for searching products, managing your cart, and adding items.

Works with [Claude Code](https://claude.ai/code) and [Claude Desktop](https://claude.ai/download) (via MCPB).

## Demo

https://github.com/user-attachments/assets/8ee0c000-6289-4b2f-86e4-2ebbe237561c

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

Your session is saved locally in `.browser_state/` (gitignored). You'll only need to re-login if your session expires (typically every few weeks).

> **Note:** If you have Chrome installed, the login window will use Chrome (so your password manager and extensions are available). Otherwise it falls back to Playwright's bundled Chromium.

### 4. Start shopping

Now you can use natural language:

- *"Search for organic oat milk"*
- *"Add 5 bananas and a dozen eggs to my cart"*
- *"What's in my cart?"*
- *"Remove the cheerios from my cart"*

## Claude Desktop (MCPB)

You can also install this as a one-click extension for Claude Desktop:

```bash
npm install -g @anthropic-ai/mcpb
mcpb pack . whole-foods-mcp.mcpb
```

Then double-click `whole-foods-mcp.mcpb` to install in Claude Desktop.

## Tools

| Tool | Description |
|------|-------------|
| `login` | Open browser for Amazon login |
| `save_session` | Persist session cookies to disk |
| `search_whole_foods` | Search products — returns ASIN, title, price, size |
| `get_product_details` | Deep dive into a product — full description, ingredients, image screenshot |
| `add_to_cart` | Add a product by ASIN (fetches product page for fresh token) |
| `view_cart` | View current cart contents |
| `remove_from_cart` | Remove an item by ASIN |
| `clear_cart` | Clear all cart items |

## How It Works

1. Maintains an authenticated Amazon session via Playwright (headless Chrome/Chromium)
2. **Search** finds products using Amazon's Whole Foods search
3. **Add to cart** fetches the product page directly for a fresh add-to-cart token, then POSTs to Amazon's cart API
4. Weight-based items (produce, fresh meat) are handled automatically — the product page always has the add-to-cart payload

### Tool Design

- **Search is read-only** — `search_whole_foods` never touches the cart
- **Add to cart is independent of search** — `add_to_cart` only needs an ASIN, it fetches its own token from the product page
- **Product details include a screenshot** — `get_product_details` returns structured text AND a screenshot so Claude can see the product image
- **No bulk tools** — Claude handles parallelism natively by calling `add_to_cart` multiple times via agents
