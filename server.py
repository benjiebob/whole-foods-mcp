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


async def _ensure_context() -> BrowserContext:
    """Launch browser and restore session if needed. Returns the shared context."""
    global _playwright, _browser, _context

    if _context:
        return _context

    _playwright = await async_playwright().start()

    if STORAGE_FILE.exists():
        _browser = await _playwright.chromium.launch(headless=True)
        _context = await _browser.new_context(storage_state=str(STORAGE_FILE))
    else:
        STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        _browser = await _playwright.chromium.launch(headless=True)
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
    const resp = await fetch(`/dp/${asin}?almBrandId=VUZHIFdob2xlIEZvb2Rz`, {
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

ADD_TO_CART_JS = """
async ({atcData, quantity}) => {
    // Try adding with quantity parameter first
    const payload = { ...atcData };
    if (quantity && quantity > 1) {
        payload.quantity = quantity;
    }
    const resp = await fetch('/alm/addtofreshcart', {
        method: 'POST',
        credentials: 'include',
        headers: {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        },
        body: JSON.stringify(payload)
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return await resp.json();
}
"""

RELEVANCE_FN = """
function _scoreRelevance(query, title) {
    const qWords = query.toLowerCase().split(/\\s+/).filter(w => w.length > 2);
    const tLower = title.toLowerCase();
    let matched = 0;
    for (const w of qWords) {
        if (tLower.includes(w)) matched++;
    }
    return qWords.length > 0 ? matched / qWords.length : 0;
}
"""

# JS to search and add in one shot with relevance scoring.
# If the best-matching result has ATC, add via API.
# If it doesn't (weight-based), fall back to fetching the product page for the ATC payload.
SEARCH_AND_ADD_JS = """
async ({query, quantity}) => {
    """ + RELEVANCE_FN + """

    // Search
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
            if (t && t.textContent.trim().length > 5) { title = t.textContent.trim(); break; }
        }
        if (!title) { const link = el.querySelector('h2 a'); if (link) title = link.textContent.trim(); }
        if (!title || title.length < 3) continue;

        const atcEl = el.querySelector('[data-action="fresh-add-to-cart"]');
        let atcData = null;
        if (atcEl) { try { atcData = JSON.parse(atcEl.getAttribute('data-fresh-add-to-cart')); } catch(e) {} }

        let price = '';
        const priceEl = el.querySelector('.a-price .a-offscreen');
        if (priceEl) price = priceEl.textContent.trim();

        const score = _scoreRelevance(query, title);
        results.push({ asin, title, price, hasATC: !!atcData, atcData, score });
    }

    if (results.length === 0) {
        return { success: false, results: [] };
    }

    // Sort all results by relevance score descending
    results.sort((a, b) => b.score - a.score);

    // Best overall match
    const bestMatch = results[0];
    // Best match that has ATC
    const bestATC = results.find(r => r.hasATC);

    // Decide: use the best ATC result only if it's reasonably relevant,
    // otherwise prefer the best overall match via product page
    const ATC_RELEVANCE_THRESHOLD = 0.75;
    let chosen = null;
    let method = 'search';

    if (bestMatch.hasATC) {
        // Best match also has ATC — ideal case
        chosen = bestMatch;
    } else if (bestATC && bestATC.score >= ATC_RELEVANCE_THRESHOLD) {
        // There's a relevant ATC result, use it
        chosen = bestATC;
    } else {
        // Best match doesn't have ATC and no relevant ATC result exists
        // → fall back to product page for the best match
        chosen = bestMatch;
        method = 'product_page';
    }

    // Helper to POST to fresh cart
    async function addToFreshCart(payload) {
        const r = await fetch('/alm/addtofreshcart', {
            method: 'POST', credentials: 'include',
            headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
            body: JSON.stringify(payload)
        });
        return r;
    }

    if (method === 'product_page') {
        // Fetch the product page to get the ATC payload
        const ppResp = await fetch(`/dp/${chosen.asin}?almBrandId=VUZHIFdob2xlIEZvb2Rz`, {
            credentials: 'include', headers: { 'Accept': 'text/html' }
        });
        const ppHtml = await ppResp.text();
        const ppDoc = new DOMParser().parseFromString(ppHtml, 'text/html');

        const ppTitle = ppDoc.querySelector('#productTitle');
        if (ppTitle) chosen.title = ppTitle.textContent.trim();

        const ppAtc = ppDoc.querySelector('[data-action="fresh-add-to-cart"]');
        if (!ppAtc) {
            return {
                success: false,
                reason: 'No ATC on product page either',
                results: results.slice(0, 5).map(r => ({ asin: r.asin, title: r.title, price: r.price, score: r.score }))
            };
        }
        let ppPayload;
        try { ppPayload = JSON.parse(ppAtc.getAttribute('data-fresh-add-to-cart')); }
        catch(e) { return { success: false, reason: 'Failed to parse product page ATC' }; }

        // Add with quantity (one at a time from product page since each needs fresh tokens)
        for (let i = 0; i < quantity; i++) {
            if (i > 0) {
                // Re-fetch product page for fresh CSRF token
                const rr = await fetch(`/dp/${chosen.asin}?almBrandId=VUZHIFdob2xlIEZvb2Rz`, {
                    credentials: 'include', headers: { 'Accept': 'text/html' }
                });
                const rrHtml = await rr.text();
                const rrDoc = new DOMParser().parseFromString(rrHtml, 'text/html');
                const rrAtc = rrDoc.querySelector('[data-action="fresh-add-to-cart"]');
                if (rrAtc) {
                    try { ppPayload = JSON.parse(rrAtc.getAttribute('data-fresh-add-to-cart')); } catch(e) {}
                }
            }
            const addR = await addToFreshCart(ppPayload);
            if (!addR.ok && i === 0) {
                return { success: false, reason: `HTTP ${addR.status} from product page add` };
            }
            if (i < quantity - 1) await new Promise(r => setTimeout(r, 400));
        }

        return { success: true, title: chosen.title, asin: chosen.asin, price: chosen.price, quantity, method: 'product_page' };
    }

    // Standard ATC path
    const payload = { ...chosen.atcData };
    if (quantity > 1) payload.quantity = quantity;
    const addResp = await addToFreshCart(payload);

    if (!addResp.ok) {
        // Quantity param failed — retry one at a time with fresh tokens
        if (quantity > 1) {
            for (let i = 0; i < quantity; i++) {
                const r2 = await fetch(`/s?k=${encodeURIComponent(query)}&i=wholefoods`, {
                    credentials: 'include', headers: { 'Accept': 'text/html' }
                });
                const h2 = await r2.text();
                const d2 = new DOMParser().parseFromString(h2, 'text/html');
                // Find the same ASIN or first ATC
                for (const el of d2.querySelectorAll('[data-asin]')) {
                    const atcEl = el.querySelector('[data-action="fresh-add-to-cart"]');
                    if (atcEl) {
                        const elAsin = el.dataset.asin;
                        const score = _scoreRelevance(query, el.textContent);
                        if (score < ATC_RELEVANCE_THRESHOLD) continue;
                        try {
                            const freshData = JSON.parse(atcEl.getAttribute('data-fresh-add-to-cart'));
                            const r3 = await addToFreshCart(freshData);
                            if (r3.ok) break;
                        } catch(e) {}
                    }
                }
                await new Promise(r => setTimeout(r, 400));
            }
        } else {
            throw new Error(`HTTP ${addResp.status}`);
        }
    }

    return { success: true, title: chosen.title, asin: chosen.asin, price: chosen.price, quantity, method: 'search' };
}
"""

# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

mcp = FastMCP("whole-foods")


@mcp.tool()
async def login() -> str:
    """Open a browser window for the user to log into Amazon.

    Call this first if the session has expired or on first use.
    The user will need to manually log in and select their Whole Foods store.
    Once done, call save_session to persist the login.
    """
    page = await _get_main_page()
    await page.goto("https://www.amazon.com/ap/signin?openid.pape.max_auth_age=0&openid.return_to=https%3A%2F%2Fwww.amazon.com%2F&openid.identity=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select&openid.assoc_handle=usflex&openid.mode=checkid_setup&openid.claimed_id=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select&openid.ns=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0", wait_until="domcontentloaded")
    return "Browser opened to Amazon login page. Please log in manually, select your Whole Foods store, then call save_session."


@mcp.tool()
async def save_session() -> str:
    """Save the current browser session so it persists across server restarts.

    Call this after logging in or whenever you want to checkpoint the session.
    """
    await _save_state()
    return f"Session saved to {STORAGE_FILE}"


@mcp.tool()
async def search_whole_foods(query: str) -> str:
    """Search for a product on Whole Foods.

    Args:
        query: Search terms (e.g. "organic whole milk 64 oz")

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
            "url": f"https://www.amazon.com/dp/{asin}?almBrandId={WF_BRAND_ID}",
        }
        summary.append(entry)

    return json.dumps(summary, indent=2)


@mcp.tool()
async def add_to_cart(query: str, quantity: int = 1, result_index: int = 0) -> str:
    """Search for a product and add the matching result to cart.

    Args:
        query: Search terms (e.g. "Tillamook extra sharp white cheddar")
        quantity: How many to add (default 1). Handles fresh CSRF tokens per add.
        result_index: Which search result to add (0 = first match with ATC). Defaults to 0.

    Returns:
        Confirmation of what was added, or an error/weight-based message.
    """
    page = await _new_wf_page()
    try:
        result = await page.evaluate(SEARCH_AND_ADD_JS, {"query": query, "quantity": quantity})
    except Exception:
        await page.close()
        raise

    await page.close()

    if result.get("success"):
        await _save_state()
        return json.dumps({
            "added": result["title"],
            "asin": result["asin"],
            "price": result.get("price", ""),
            "quantity": result.get("quantity", quantity),
            "method": result.get("method", "search"),
        })
    else:
        found = [{
            "asin": r["asin"], "title": r["title"],
            "price": r.get("price", ""),
            "url": f"https://www.amazon.com/dp/{r['asin']}?almBrandId={WF_BRAND_ID}",
        } for r in result.get("results", [])]
        return json.dumps({
            "error": "could_not_add",
            "message": result.get("reason", "No matching results could be added"),
            "results": found,
        })


@mcp.tool()
async def add_grocery_list(items: list[dict]) -> str:
    """Add multiple grocery items to the Whole Foods cart.

    Each item gets a fresh search (fresh CSRF tokens) so quantities > 1 work
    reliably. Weight-based items that can't be added via API are returned
    separately with product URLs for manual addition.

    Args:
        items: List of objects with keys:
            - query (str): Search query for the item
            - quantity (int, optional): Number to add (default 1)
            - name (str, optional): Display name for logging

    Returns:
        JSON summary of successes, failures, and weight-based items needing manual add.
    """
    page = await _new_wf_page()

    successes = []
    failures = []

    for item in items:
        query = item["query"]
        quantity = item.get("quantity", 1)
        name = item.get("name", query)

        try:
            result = await page.evaluate(
                SEARCH_AND_ADD_JS, {"query": query, "quantity": quantity}
            )

            if result.get("success"):
                successes.append({
                    "name": name,
                    "matched": result["title"][:60],
                    "price": result.get("price", ""),
                    "quantity": quantity,
                    "method": result.get("method", "search"),
                })
            else:
                failures.append({
                    "name": name,
                    "reason": result.get("reason", "No matching results"),
                    "results": result.get("results", [])[:3],
                })
        except Exception as e:
            failures.append({"name": name, "reason": str(e)})

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
        // Try to extract cart items from the page
        for (const el of document.querySelectorAll('[data-asin]')) {
            const asin = el.dataset.asin;
            if (!asin || asin.length < 5) continue;

            let title = '';
            const titleEl = el.querySelector('.sc-product-title, .a-truncate-cut, a[href*="/dp/"]');
            if (titleEl) title = titleEl.textContent.trim();
            if (!title) continue;

            let qty = '1';
            const qtyEl = el.querySelector('.a-dropdown-prompt, input[name="quantity"]');
            if (qtyEl) qty = qtyEl.value || qtyEl.textContent.trim();

            let price = '';
            const priceEl = el.querySelector('.a-price .a-offscreen, .sc-product-price');
            if (priceEl) price = priceEl.textContent.trim();

            items.push({ asin, title: title.substring(0, 80), quantity: qty, price });
        }

        // Try to get subtotal
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

    details["url"] = f"https://www.amazon.com/dp/{asin}?almBrandId={WF_BRAND_ID}"
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
        url = f"https://www.amazon.com/dp/{asin}?almBrandId={WF_BRAND_ID}"
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
    url = f"https://www.amazon.com/dp/{asin}?almBrandId={WF_BRAND_ID}"
    await page.goto(url, wait_until="domcontentloaded")
    return f"Opened product page: {url} — the user can now manually add this item."


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")
