async ({asin, quantity}) => {
    // Fetch product page for fresh ATC data
    const resp = await fetch(`/dp/${asin}?almBrandId=VUZHIFdob2xlIEZvb2Rz&fpw=alm&s=wholefoods`, {
        credentials: 'include', headers: { 'Accept': 'text/html' }
    });
    const html = await resp.text();
    const doc = new DOMParser().parseFromString(html, 'text/html');

    // Extract product info
    const titleEl = doc.querySelector('#productTitle');
    const title = titleEl ? titleEl.textContent.trim() : '';

    const priceEl = doc.querySelector('.a-price .a-offscreen');
    const price = priceEl ? priceEl.textContent.trim() : '';

    // Extract add-to-cart payload
    const atcEl = doc.querySelector('[data-action="fresh-add-to-cart"]');
    if (!atcEl) {
        return { success: false, reason: 'Item unavailable at this store (no add-to-cart on product page)' };
    }

    let atcData;
    try {
        atcData = JSON.parse(atcEl.getAttribute('data-fresh-add-to-cart'));
    } catch(e) {
        return { success: false, reason: 'Failed to parse add-to-cart data' };
    }

    // Add to cart
    const payload = { ...atcData };
    if (quantity > 1) payload.quantity = quantity;

    const addResp = await fetch('/alm/addtofreshcart', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        body: JSON.stringify(payload)
    });

    if (addResp.ok) {
        return { success: true, title, asin, price, quantity };
    }

    return { success: false, reason: 'Item unavailable at this store (HTTP ' + addResp.status + ')' };
}
