"""
MCP Server for Amazon Whole Foods grocery ordering.

Uses Playwright to maintain an authenticated browser session and exposes
tools for searching products, adding items to cart, and managing the cart.
"""

import asyncio
import json
import tempfile
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

STORAGE_DIR = Path(__file__).parent / ".browser_state"
STORAGE_FILE = STORAGE_DIR / "state.json"
WF_BRAND_ID = "VUZHIFdob2xlIEZvb2Rz"
WF_CART_URL = f"https://www.amazon.com/cart/localmarket?almBrandId={WF_BRAND_ID}"
WF_HOME = "https://www.amazon.com/?i=wholefoods"

# ---------------------------------------------------------------------------
# Browser management
# ---------------------------------------------------------------------------

_playwright = None
_browser: Browser | None = None
_context: BrowserContext | None = None
_main_page: Page | None = None


async def _launch_browser(headless: bool = True) -> Browser:
    """Launch Chrome if available, otherwise fall back to Playwright's Chromium."""
    try:
        return await _playwright.chromium.launch(headless=headless, channel="chrome")
    except Exception:
        return await _playwright.chromium.launch(headless=headless)


async def _ensure_context(headless: bool = True) -> BrowserContext:
    """Launch browser and restore session if needed. Returns the shared context."""
    global _playwright, _browser, _context

    if _context:
        return _context

    _playwright = await async_playwright().start()

    if STORAGE_FILE.exists():
        _browser = await _launch_browser(headless=headless)
        _context = await _browser.new_context(storage_state=str(STORAGE_FILE))
    else:
        STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        _browser = await _launch_browser(headless=headless)
        _context = await _browser.new_context()

    return _context


async def _get_main_page() -> Page:
    """Get or create the main page for navigation-based tools (login, cart)."""
    global _main_page
    ctx = await _ensure_context()
    if _main_page and not _main_page.is_closed():
        return _main_page
    _main_page = await ctx.new_page()
    return _main_page


async def _is_logged_in(page: Page) -> bool:
    """Return True if the current page shows an authenticated Amazon session."""
    try:
        text = await page.evaluate(
            "() => { const el = document.querySelector('#nav-link-accountList-nav-line-1'); "
            "return el ? el.textContent.trim().toLowerCase() : null; }"
        )
        if text is None:
            return True  # element not found — can't determine, assume ok
        return "sign in" not in text
    except Exception:
        return True  # can't determine, assume ok


async def _new_wf_page() -> Page:
    """Create a fresh page on a Whole Foods URL. Caller must close it when done."""
    ctx = await _ensure_context()
    page = await ctx.new_page()
    await page.goto(WF_HOME, wait_until="domcontentloaded")
    await asyncio.sleep(1)
    if not await _is_logged_in(page):
        await page.close()
        raise RuntimeError(
            "Session expired or not logged in. Call login() then save_session() before retrying."
        )
    return page


async def _save_state():
    """Persist browser cookies/storage for future sessions."""
    if _context:
        STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        await _context.storage_state(path=str(STORAGE_FILE))


# ---------------------------------------------------------------------------
# JS helpers — loaded from js/ directory
# ---------------------------------------------------------------------------

JS_DIR = Path(__file__).parent / "js"


def _load_js(filename: str) -> str:
    return (JS_DIR / filename).read_text()


SEARCH_JS = _load_js("search.js")
PRODUCT_DETAILS_JS = _load_js("product_details.js")
ADD_TO_CART_JS = _load_js("add_to_cart.js")

# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

mcp = FastMCP("whole-foods")


@mcp.tool()
async def login() -> str:
    """Open a visible browser window for the user to log into Amazon.

    Call this first if the session has expired or on first use.
    The user will need to manually log in and select their Whole Foods store.
    Once done, call save_session to persist the login and switch back to headless.
    """
    global _browser, _context, _main_page

    # Tear down any existing headless browser
    if _context:
        await _save_state()
        await _browser.close()
        _context = None
        _browser = None
        _main_page = None

    # Launch visible browser for login
    await _ensure_context(headless=False)
    page = await _get_main_page()
    await page.goto("https://www.amazon.com/ap/signin?openid.pape.max_auth_age=0&openid.return_to=https%3A%2F%2Fwww.amazon.com%2F&openid.identity=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select&openid.assoc_handle=usflex&openid.mode=checkid_setup&openid.claimed_id=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select&openid.ns=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0", wait_until="domcontentloaded")
    return "Browser opened to Amazon login page. Please log in manually, select your Whole Foods store, then call save_session."


@mcp.tool()
async def save_session() -> str:
    """Save the current browser session and switch back to headless mode.

    Call this after logging in. Persists cookies/storage to disk, then
    restarts the browser in headless mode for all subsequent operations.
    """
    global _browser, _context, _main_page

    await _save_state()

    # Tear down visible browser and relaunch headless
    if _browser:
        await _browser.close()
        _context = None
        _browser = None
        _main_page = None

    # Relaunch headless with saved session
    await _ensure_context(headless=True)

    return f"Session saved to {STORAGE_FILE}. Browser switched to headless mode."


@mcp.tool()
async def search_whole_foods(query: str) -> str:
    """Search for a product on Whole Foods.

    IMPORTANT SEARCH TIPS:
    - Use simple, short queries (1-2 words) for best results, especially for produce.
      Good: "banana", "nectarine", "apple"
      Bad: "organic fuji apple fresh produce", "fresh peach nectarine plum stone fruit"
    - Multi-word queries dilute results and often return irrelevant items.
    - When an item isn't found, try related items as SEPARATE searches
      (e.g. peach not available → try "nectarine", then "plum" separately).
    - can_add_to_cart=false does NOT mean unavailable. Weight-based items (produce,
      meat, deli) show false in search but CAN be added via the product page fallback
      in add_to_cart. Only HTTP 400 from add_to_cart means truly unavailable.
    - Bags vs individual: pay attention to whether results are bags (e.g. "48 Ounce Bag")
      or individual items. Match to what the user actually wants.

    Args:
        query: Search terms — keep short and simple for best results

    Returns:
        JSON array of results with asin, title, price, and whether
        the item can be directly added to cart.
    """
    page = await _new_wf_page()
    try:
        results = await page.evaluate(SEARCH_JS, query)
    finally:
        await page.close()

    # Return a clean summary with product links
    summary = []
    for i, r in enumerate(results[:10]):
        asin = r["asin"]
        entry = {
            "index": i,
            "asin": asin,
            "title": r["title"],
            "price": r.get("price", ""),
            "description": r.get("description", ""),
            "size": r.get("size", ""),
            "can_add_to_cart": r["canAddToCart"],
            "url": f"https://www.amazon.com/dp/{asin}?almBrandId={WF_BRAND_ID}&fpw=alm&s=wholefoods",
        }
        summary.append(entry)

    return json.dumps(summary, indent=2)


@mcp.tool()
async def add_to_cart(asin: str, quantity: int = 1) -> str:
    """Add a specific product to cart by its ASIN.

    Use search_whole_foods first to find the right product and get its ASIN,
    then call this tool with the ASIN to add it.

    This tool fetches the product page directly to get fresh add-to-cart data,
    so it works for all item types including weight-based produce and meat.

    IMPORTANT NOTES:
    - HTTP 400 means the item is genuinely unavailable at the selected store.
      When this happens, search for alternatives with simple queries.
    - For quantities > 1, the tool re-fetches the product page for each unit
      to get fresh CSRF tokens.

    Args:
        asin: The Amazon ASIN of the product to add (from search_whole_foods results)
        quantity: How many to add (default 1)

    Returns:
        Confirmation of what was added, or an error message.
    """
    page = await _new_wf_page()
    try:
        result = await page.evaluate(
            ADD_TO_CART_JS, {"asin": asin, "quantity": quantity}
        )
    except Exception:
        await page.close()
        raise

    await page.close()

    if result.get("success"):
        await _save_state()
        return json.dumps({
            "added": result.get("title", asin),
            "asin": result["asin"],
            "price": result.get("price", ""),
            "quantity": result.get("quantity", quantity),
        })
    else:
        return json.dumps({
            "error": "could_not_add",
            "asin": asin,
            "reason": result.get("reason", "Unknown error"),
        })



@mcp.tool()
async def view_cart() -> str:
    """Navigate to the Whole Foods cart and return a summary of items."""
    page = await _get_main_page()
    await page.goto(WF_CART_URL, wait_until="domcontentloaded")
    await asyncio.sleep(2)
    if not await _is_logged_in(page):
        raise RuntimeError(
            "Session expired or not logged in. Call login() then save_session() before retrying."
        )

    cart_info = await page.evaluate(_load_js("view_cart.js"))

    return json.dumps(cart_info, indent=2)


@mcp.tool()
async def remove_from_cart(asin: str) -> str:
    """Remove an item from the Whole Foods cart by its ASIN.

    Args:
        asin: The Amazon ASIN of the product to remove. Use view_cart to find ASINs.
    """
    page = await _get_main_page()

    # Always reload the cart page to get fresh DOM
    await page.goto(WF_CART_URL, wait_until="domcontentloaded")
    await asyncio.sleep(2)
    if not await _is_logged_in(page):
        raise RuntimeError(
            "Session expired or not logged in. Call login() then save_session() before retrying."
        )

    # Use Playwright's native click (not JS .click()) to trigger Amazon's event handlers
    # Find the delete button inside the item's container
    delete_selector = f'[data-asin="{asin}"] input[value="Delete"]'
    delete_btn = await page.query_selector(delete_selector)

    if not delete_btn:
        # Try alternative selectors
        delete_selector = f'[data-asin="{asin}"] .sc-action-delete input'
        delete_btn = await page.query_selector(delete_selector)

    if not delete_btn:
        return json.dumps({"error": "Item not found in cart or no delete button", "asin": asin})

    # Use Playwright's click which generates real mouse events
    await delete_btn.click()

    # Wait for the page to process the deletion
    await asyncio.sleep(2)
    await page.wait_for_load_state("domcontentloaded")
    await asyncio.sleep(1)

    # Verify the item is actually gone
    still_there = await page.query_selector(f'[data-asin="{asin}"]')
    if still_there:
        return json.dumps({"error": "Delete clicked but item still in cart", "asin": asin})

    await _save_state()
    return json.dumps({"removed": True, "asin": asin})


@mcp.tool()
async def clear_cart() -> str:
    """Remove all items from the Whole Foods cart using the bulk 'Clear entire cart' button."""
    page = await _get_main_page()
    await page.goto(WF_CART_URL, wait_until="domcontentloaded")
    await asyncio.sleep(2)
    if not await _is_logged_in(page):
        raise RuntimeError(
            "Session expired or not logged in. Call login() then save_session() before retrying."
        )

    # Check if cart has items
    item_count = await page.evaluate("() => document.querySelectorAll('[data-asin]').length")
    if item_count == 0:
        return json.dumps({"cleared": True, "message": "Cart is already empty"})

    # Step 1: Click "Clear entire cart" via JS to avoid pointer interception
    await page.evaluate(_load_js("clear_cart_click.js"))
    await asyncio.sleep(1)

    click_result = await page.evaluate(_load_js("clear_cart_find_button.js"))

    if not click_result.get("clicked"):
        return json.dumps({"success": False, "reason": "Could not find clear cart button"})

    # Step 2: Wait for confirmation dialog and click "Clear"
    await asyncio.sleep(2)

    confirm_result = await page.evaluate(_load_js("clear_cart_confirm.js"))

    await asyncio.sleep(2)
    await _save_state()

    if confirm_result.get("confirmed"):
        return json.dumps({"cleared": True, "message": f"Cleared cart (had {item_count} items)"})
    else:
        return json.dumps({"cleared": False, "message": "Clicked 'Clear cart' but could not confirm dialog"})


@mcp.tool()
async def get_product_details(asin: str) -> str:
    """Fetch detailed product information from a Whole Foods product page.

    Returns title, description, feature bullets, size, price, image URL,
    and a screenshot of the product page. Use this to get more info about
    a product found via search_whole_foods — for example to check
    ingredients, allergens, exact size/weight, or to see what the product
    looks like.

    Args:
        asin: The Amazon ASIN of the product (from search_whole_foods results).
    """
    page = await _new_wf_page()
    try:
        url = f"https://www.amazon.com/dp/{asin}?almBrandId={WF_BRAND_ID}&fpw=alm&s=wholefoods"
        await page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(2)

        details = await page.evaluate(PRODUCT_DETAILS_JS, asin)

        # Screenshot the product page so Claude can see the product image
        path = Path(tempfile.mktemp(suffix=".png", prefix=f"wf_product_{asin}_"))
        await page.screenshot(path=str(path), full_page=False)
        details["screenshot"] = str(path)
    finally:
        await page.close()

    details["url"] = url
    return json.dumps(details, indent=2)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")
