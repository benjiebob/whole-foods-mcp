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


async def _ensure_context(headless: bool = True) -> BrowserContext:
    """Launch browser and restore session if needed. Returns the shared context."""
    global _playwright, _browser, _context

    if _context:
        return _context

    _playwright = await async_playwright().start()

    if STORAGE_FILE.exists():
        _browser = await _playwright.chromium.launch(headless=headless)
        _context = await _browser.new_context(storage_state=str(STORAGE_FILE))
    else:
        STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        _browser = await _playwright.chromium.launch(headless=headless)
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


async def _new_wf_page() -> Page:
    """Create a fresh page on a Whole Foods URL. Caller must close it when done."""
    ctx = await _ensure_context()
    page = await ctx.new_page()
    await page.goto(WF_HOME, wait_until="domcontentloaded")
    await asyncio.sleep(1)
    return page


async def _save_state():
    """Persist browser cookies/storage for future sessions."""
    if _context:
        STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        await _context.storage_state(path=str(STORAGE_FILE))


# ---------------------------------------------------------------------------
# JS helpers injected into the page
# ---------------------------------------------------------------------------

SEARCH_JS = """
async (query) => {
    const resp = await fetch(`/s?k=${encodeURIComponent(query)}&i=wholefoods`, {
        credentials: 'include',
        headers: { 'Accept': 'text/html' }
    });
    const html = await resp.text();
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const results = [];

    for (const el of doc.querySelectorAll('[data-asin]')) {
        const asin = el.dataset.asin;
        if (!asin || asin.length < 5) continue;

        let title = '';
        for (const sel of ['h2 a span', '.a-text-normal']) {
            const t = el.querySelector(sel);
            if (t && t.textContent.trim().length > 5) {
                title = t.textContent.trim();
                break;
            }
        }
        if (!title) {
            const link = el.querySelector('h2 a');
            if (link) title = link.textContent.trim();
        }
        if (!title || title.length < 3) continue;

        const atcEl = el.querySelector('[data-action="fresh-add-to-cart"]');
        let atcData = null;
        if (atcEl) {
            try {
                atcData = JSON.parse(atcEl.getAttribute('data-fresh-add-to-cart'));
            } catch (e) {}
        }

        // Extract price
        let price = '';
        const priceEl = el.querySelector('.a-price .a-offscreen');
        if (priceEl) price = priceEl.textContent.trim();

        // Extract brief description / size info from search result
        let description = '';
        const descEls = el.querySelectorAll('.a-size-base-plus, .a-color-base:not(h2 span)');
        for (const d of descEls) {
            const t = d.textContent.trim();
            if (t.length > 10 && t !== title && !t.startsWith('$')) {
                description = t.substring(0, 150);
                break;
            }
        }

        // Extract size/weight info
        let size = '';
        const sizeEl = el.querySelector('.a-size-base.a-color-secondary, .a-row .a-size-base');
        if (sizeEl) {
            const t = sizeEl.textContent.trim();
            if (t.length < 50 && !t.startsWith('$')) size = t;
        }

        results.push({ asin, title, price, hasATC: !!atcData, atcData, description, size });
    }
    return results;
}
"""

PRODUCT_DETAILS_JS = """
async (asin) => {
    const resp = await fetch(`/dp/${asin}?almBrandId=VUZHIFdob2xlIEZvb2Rz&fpw=alm&s=wholefoods`, {
        credentials: 'include',
        headers: { 'Accept': 'text/html' }
    });
    const html = await resp.text();
    const doc = new DOMParser().parseFromString(html, 'text/html');

    // Title
    const titleEl = doc.querySelector('#productTitle');
    const title = titleEl ? titleEl.textContent.trim() : '';

    // Price
    let price = '';
    const priceEl = doc.querySelector('.a-price .a-offscreen, #price_inside_buybox, #priceblock_ourprice');
    if (priceEl) price = priceEl.textContent.trim();

    // Feature bullets
    const bullets = [];
    for (const li of doc.querySelectorAll('#feature-bullets ul li span, #feature-bullets li span')) {
        const t = li.textContent.trim();
        if (t && t.length > 3 && !t.includes('report')) bullets.push(t);
    }

    // Product description
    let description = '';
    const descEl = doc.querySelector('#productDescription p, #productDescription');
    if (descEl) description = descEl.textContent.trim().substring(0, 500);

    // Important info table (ingredients, allergens, etc.)
    const details = {};
    for (const tr of doc.querySelectorAll('#productDetails_techSpec_section_1 tr, #detailBullets_feature_div li')) {
        const label = tr.querySelector('th, .a-text-bold');
        const value = tr.querySelector('td, span:not(.a-text-bold)');
        if (label && value) {
            const k = label.textContent.trim().replace(/[:\\s]+$/, '');
            const v = value.textContent.trim();
            if (k && v && k.length < 50) details[k] = v.substring(0, 200);
        }
    }

    // Size / weight
    let size = '';
    const sizeEl = doc.querySelector('#variation_size_name .selection, .a-size-base:has(+ #priceblock_ourprice)');
    if (sizeEl) size = sizeEl.textContent.trim();

    // ATC availability
    const atcEl = doc.querySelector('[data-action="fresh-add-to-cart"]');
    let hasATC = false;
    if (atcEl) hasATC = true;

    return { asin, title, price, description, features: bullets.slice(0, 8), details, size, hasATC };
}
"""


# JS to add a specific ASIN to cart.
# First tries to find ATC data in search results. If not found (weight-based items),
# falls back to fetching the product page for the ATC payload.
ADD_BY_SEARCH_JS = """
async ({query, asin, quantity}) => {
    // Helper to POST to fresh cart
    async function addToFreshCart(payload) {
        return await fetch('/alm/addtofreshcart', {
            method: 'POST', credentials: 'include',
            headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
            body: JSON.stringify(payload)
        });
    }

    // Try search results first
    const resp = await fetch(`/s?k=${encodeURIComponent(query)}&i=wholefoods`, {
        credentials: 'include',
        headers: { 'Accept': 'text/html' }
    });
    const html = await resp.text();
    const doc = new DOMParser().parseFromString(html, 'text/html');

    let atcData = null;
    let title = '';
    let price = '';
    for (const el of doc.querySelectorAll('[data-asin]')) {
        if (el.dataset.asin !== asin) continue;
        const atcEl = el.querySelector('[data-action="fresh-add-to-cart"]');
        if (atcEl) {
            try { atcData = JSON.parse(atcEl.getAttribute('data-fresh-add-to-cart')); } catch(e) {}
        }
        const titleEl = el.querySelector('h2 a span, .a-text-normal');
        if (titleEl) title = titleEl.textContent.trim();
        const priceEl = el.querySelector('.a-price .a-offscreen');
        if (priceEl) price = priceEl.textContent.trim();
        break;
    }

    // If no ATC in search results, try the product page
    if (!atcData) {
        const ppResp = await fetch(`/dp/${asin}?almBrandId=VUZHIFdob2xlIEZvb2Rz&fpw=alm&s=wholefoods`, {
            credentials: 'include', headers: { 'Accept': 'text/html' }
        });
        const ppHtml = await ppResp.text();
        const ppDoc = new DOMParser().parseFromString(ppHtml, 'text/html');

        const ppTitle = ppDoc.querySelector('#productTitle');
        if (ppTitle) title = ppTitle.textContent.trim();
        const ppPrice = ppDoc.querySelector('.a-price .a-offscreen');
        if (ppPrice) price = ppPrice.textContent.trim();

        const ppAtc = ppDoc.querySelector('[data-action="fresh-add-to-cart"]');
        if (!ppAtc) {
            return { success: false, reason: 'Item unavailable at this store (no ATC on product page)' };
        }
        try { atcData = JSON.parse(ppAtc.getAttribute('data-fresh-add-to-cart')); }
        catch(e) { return { success: false, reason: 'Failed to parse product page ATC data' }; }
    }

    // Add to cart — try with quantity first, fall back to one-at-a-time
    const payload = { ...atcData };
    if (quantity > 1) payload.quantity = quantity;
    const addResp = await addToFreshCart(payload);

    if (addResp.ok) {
        return { success: true, title, asin, price, quantity };
    }

    // Bulk failed — try one at a time with fresh tokens
    if (quantity > 1) {
        let added = 0;
        for (let i = 0; i < quantity; i++) {
            // Re-fetch product page for fresh CSRF token each time
            const rr = await fetch(`/dp/${asin}?almBrandId=VUZHIFdob2xlIEZvb2Rz&fpw=alm&s=wholefoods`, {
                credentials: 'include', headers: { 'Accept': 'text/html' }
            });
            const rrHtml = await rr.text();
            const rrDoc = new DOMParser().parseFromString(rrHtml, 'text/html');
            const rrAtc = rrDoc.querySelector('[data-action="fresh-add-to-cart"]');
            if (rrAtc) {
                try {
                    const freshData = JSON.parse(rrAtc.getAttribute('data-fresh-add-to-cart'));
                    const r3 = await addToFreshCart(freshData);
                    if (r3.ok) added++;
                } catch(e) {}
            }
            await new Promise(r => setTimeout(r, 400));
        }
        if (added > 0) return { success: true, title, asin, price, quantity: added };
    }

    return { success: false, reason: 'Item unavailable at this store (HTTP ' + addResp.status + ')' };
}
"""

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
            "can_add_to_cart": r["hasATC"],
            "url": f"https://www.amazon.com/dp/{asin}?almBrandId={WF_BRAND_ID}&fpw=alm&s=wholefoods",
        }
        summary.append(entry)

    return json.dumps(summary, indent=2)


@mcp.tool()
async def add_to_cart(query: str, asin: str, quantity: int = 1) -> str:
    """Add a specific product to cart by its ASIN.

    Use search_whole_foods first to find the right product and get its ASIN,
    then call this tool with the ASIN to add it. Only items with
    can_add_to_cart=true in search results can be added.

    IMPORTANT NOTES:
    - Items with can_add_to_cart=false CAN still be added — this tool automatically
      falls back to the product page to get add-to-cart data for weight-based items.
    - HTTP 400 means the item is genuinely unavailable at the selected store.
      When this happens, search for alternatives with simple queries.
    - For quantities > 1 of weight-based items, the tool re-fetches the product page
      for each unit to get fresh CSRF tokens.

    Args:
        query: The original search query (needed to find the ASIN's ATC data in search results)
        asin: The Amazon ASIN of the product to add (from search_whole_foods results)
        quantity: How many to add (default 1)

    Returns:
        Confirmation of what was added, or an error message.
    """
    page = await _new_wf_page()
    try:
        result = await page.evaluate(
            ADD_BY_SEARCH_JS, {"query": query, "asin": asin, "quantity": quantity}
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
async def add_grocery_list(items: list[dict]) -> str:
    """Add multiple grocery items to the Whole Foods cart.

    Each item requires an ASIN (from search_whole_foods results).
    Use search_whole_foods first to find the right products.

    Args:
        items: List of objects with keys:
            - query (str): Search query (needed to find ATC data)
            - asin (str): The ASIN to add
            - quantity (int, optional): Number to add (default 1)
            - name (str, optional): Display name for logging

    Returns:
        JSON summary of successes and failures.
    """
    page = await _new_wf_page()

    successes = []
    failures = []

    for item in items:
        query = item["query"]
        asin = item["asin"]
        quantity = item.get("quantity", 1)
        name = item.get("name", query)

        try:
            result = await page.evaluate(
                ADD_BY_SEARCH_JS, {"query": query, "asin": asin, "quantity": quantity}
            )

            if result.get("success"):
                successes.append({
                    "name": name,
                    "matched": result.get("title", asin)[:60],
                    "price": result.get("price", ""),
                    "quantity": result.get("quantity", quantity),
                })
            else:
                failures.append({
                    "name": name,
                    "asin": asin,
                    "reason": result.get("reason", "Failed to add"),
                })
        except Exception as e:
            failures.append({"name": name, "asin": asin, "reason": str(e)})

        await asyncio.sleep(0.4)

    await page.close()
    await _save_state()

    return json.dumps({
        "added": len(successes),
        "failed": len(failures),
        "successes": successes,
        "failures": failures,
    }, indent=2)


@mcp.tool()
async def view_cart() -> str:
    """Navigate to the Whole Foods cart and return a summary of items."""
    page = await _get_main_page()
    await page.goto(WF_CART_URL, wait_until="domcontentloaded")
    await asyncio.sleep(2)

    cart_info = await page.evaluate("""
    () => {
        const items = [];
        for (const el of document.querySelectorAll('[data-asin]')) {
            const asin = el.dataset.asin;
            if (!asin || asin.length < 5) continue;

            let title = '';
            const titleEl = el.querySelector('.sc-product-title, .a-truncate-cut, a[href*="/dp/"]');
            if (titleEl) title = titleEl.textContent.trim();
            if (!title) continue;

            // Extract quantity: try multiple approaches
            let qty = '1';

            // 1. Look for the quantity number in the stepper/dropdown widget
            const qtyNum = el.querySelector('span[id^="qs-widget-quantity"]');
            if (qtyNum) {
                // Get only direct text, not child element text
                const num = qtyNum.textContent.trim().replace(/[^0-9]/g, '');
                if (num) qty = num;
            }

            // 2. Fallback: dropdown prompt
            if (qty === '1') {
                const dd = el.querySelector('.a-dropdown-prompt');
                if (dd) {
                    const num = dd.textContent.trim().replace(/[^0-9]/g, '');
                    if (num) qty = num;
                }
            }

            // 3. Fallback: input field
            if (qty === '1') {
                const inp = el.querySelector('input[name="quantity"]');
                if (inp && inp.value) qty = inp.value;
            }

            // 4. Fallback: data attribute
            if (qty === '1') {
                const dq = el.getAttribute('data-quantity');
                if (dq && dq !== '0') qty = dq;
            }

            // 5. Fallback: look for stepper value display (common in WF cart)
            if (qty === '1') {
                const stepper = el.querySelector('.qs-widget-stepper-value, .sc-quantity-stepper-value');
                if (stepper) {
                    const num = stepper.textContent.trim().replace(/[^0-9]/g, '');
                    if (num) qty = num;
                }
            }

            // 6. Fallback: find any bold number near a minus/plus button
            if (qty === '1') {
                for (const span of el.querySelectorAll('span.a-size-base.a-text-bold')) {
                    const num = span.textContent.trim();
                    if (/^\d+$/.test(num) && parseInt(num) > 0) {
                        qty = num;
                        break;
                    }
                }
            }

            let price = '';
            const priceEl = el.querySelector('.a-price .a-offscreen, .sc-product-price');
            if (priceEl) price = priceEl.textContent.trim();

            items.push({ asin, title: title.substring(0, 80), quantity: qty, price });
        }

        let subtotal = '';
        const subtotalEl = document.querySelector('#sc-subtotal-amount-activecart .a-price .a-offscreen, .sc-subtotal');
        if (subtotalEl) subtotal = subtotalEl.textContent.trim();

        return { items, subtotal };
    }
    """)

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

    # Check if cart has items
    item_count = await page.evaluate("""
    () => document.querySelectorAll('[data-asin]').length
    """)
    if item_count == 0:
        return json.dumps({"cleared": True, "message": "Cart is already empty"})

    # Step 1: Click "Clear entire cart" via JS to avoid pointer interception
    await page.evaluate("""
    () => {
        // Dismiss any existing modal first
        const overlay = document.querySelector('.a-modal-scroller');
        if (overlay) {
            const closeBtn = overlay.querySelector('.a-button-close, [data-action="a-popover-close"]');
            if (closeBtn) closeBtn.click();
        }
    }
    """)
    await asyncio.sleep(1)

    click_result = await page.evaluate("""
    () => {
        const allEls = document.querySelectorAll('a, span, input, button');
        for (const el of allEls) {
            const text = (el.textContent || '').trim().toLowerCase();
            if (text === 'clear cart' || text.includes('clear entire cart') || text.includes('clear all items')) {
                el.click();
                return { clicked: true };
            }
        }
        const href = document.querySelector('a[href*="clearCart"], a[href*="clear-cart"]');
        if (href) { href.click(); return { clicked: true }; }
        return { clicked: false };
    }
    """)

    if not click_result.get("clicked"):
        return json.dumps({"success": False, "reason": "Could not find clear cart button"})

    # Step 2: Wait for confirmation dialog and click "Clear"
    await asyncio.sleep(2)

    confirm_result = await page.evaluate("""
    async () => {
        // Look for a visible modal/popover/dialog
        const containers = document.querySelectorAll(
            '.a-popover:not([style*="display: none"]), .a-modal, [role="dialog"], .a-modal-scroller'
        );
        for (const container of containers) {
            // Find buttons/links/inputs inside that say "Clear" (but not "Clear cart" which is the trigger)
            for (const el of container.querySelectorAll('a, button, input, span')) {
                const text = (el.textContent || '').trim();
                const val = el.getAttribute('value') || '';
                if (text === 'Clear' || val === 'Clear' ||
                    text === 'Yes' || val === 'Yes' ||
                    text === 'Confirm' || val === 'Confirm') {
                    el.click();
                    await new Promise(r => setTimeout(r, 3000));
                    return { confirmed: true, buttonText: text || val };
                }
            }
        }

        // Fallback: search the entire page for a modal-style confirm button
        for (const el of document.querySelectorAll('input[type="submit"], button, a.a-button-text, span.a-button-text')) {
            const text = (el.textContent || '').trim();
            const val = el.getAttribute('value') || '';
            if (text === 'Clear' || val === 'Clear') {
                el.click();
                await new Promise(r => setTimeout(r, 3000));
                return { confirmed: true, buttonText: text || val, fallback: true };
            }
        }

        return { confirmed: false };
    }
    """)

    await asyncio.sleep(2)
    await _save_state()

    if confirm_result.get("confirmed"):
        return json.dumps({"cleared": True, "message": f"Cleared cart (had {item_count} items)"})
    else:
        return json.dumps({"cleared": False, "message": "Clicked 'Clear cart' but could not confirm dialog"})


@mcp.tool()
async def get_product_details(asin: str) -> str:
    """Fetch detailed product information from a Whole Foods product page.

    Returns title, description, feature bullets, size, price, and other details.
    Useful for understanding exactly what a product is before adding to cart.

    Args:
        asin: The Amazon ASIN of the product.
    """
    page = await _new_wf_page()
    try:
        details = await page.evaluate(PRODUCT_DETAILS_JS, asin)
    finally:
        await page.close()

    details["url"] = f"https://www.amazon.com/dp/{asin}?almBrandId={WF_BRAND_ID}&fpw=alm&s=wholefoods"
    return json.dumps(details, indent=2)


@mcp.tool()
async def screenshot_product(asin: str) -> str:
    """Take a screenshot of a Whole Foods product page.

    Returns the file path to the screenshot image. Use the Read tool to view it.

    Args:
        asin: The Amazon ASIN of the product.
    """
    page = await _new_wf_page()
    try:
        url = f"https://www.amazon.com/dp/{asin}?almBrandId={WF_BRAND_ID}&fpw=alm&s=wholefoods"
        await page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(2)

        path = Path(tempfile.mktemp(suffix=".png", prefix=f"wf_product_{asin}_"))
        await page.screenshot(path=str(path), full_page=False)
    finally:
        await page.close()

    return json.dumps({"screenshot": str(path), "asin": asin, "url": url})


@mcp.tool()
async def screenshot_search(query: str) -> str:
    """Take a screenshot of Whole Foods search results.

    Returns the file path to the screenshot image. Use the Read tool to view it.

    Args:
        query: Search terms (e.g. "non alcoholic beer")
    """
    page = await _new_wf_page()
    try:
        search_url = f"https://www.amazon.com/s?k={query}&i=wholefoods"
        await page.goto(search_url, wait_until="domcontentloaded")
        await asyncio.sleep(2)

        path = Path(tempfile.mktemp(suffix=".png", prefix="wf_search_"))
        await page.screenshot(path=str(path), full_page=False)
    finally:
        await page.close()

    return json.dumps({"screenshot": str(path), "query": query})


@mcp.tool()
async def open_product_page(asin: str) -> str:
    """Open a product page in the Whole Foods context.

    Useful for weight-based items that can't be added via API.

    Args:
        asin: The Amazon ASIN of the product.
    """
    page = await _get_main_page()
    url = f"https://www.amazon.com/dp/{asin}?almBrandId={WF_BRAND_ID}&fpw=alm&s=wholefoods"
    await page.goto(url, wait_until="domcontentloaded")
    return f"Opened product page: {url} — the user can now manually add this item."


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")
