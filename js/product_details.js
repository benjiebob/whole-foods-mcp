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
            const k = label.textContent.trim().replace(/[:\s]+$/, '');
            const v = value.textContent.trim();
            if (k && v && k.length < 50) details[k] = v.substring(0, 200);
        }
    }

    // Size / weight
    let size = '';
    const sizeEl = doc.querySelector('#variation_size_name .selection, .a-size-base:has(+ #priceblock_ourprice)');
    if (sizeEl) size = sizeEl.textContent.trim();

    // Product image URL
    let imageUrl = '';
    const imgEl = doc.querySelector('#landingImage, #imgTagWrapperId img, #main-image-container img');
    if (imgEl) {
        // Prefer data-old-hires (full resolution) over src (may be placeholder)
        imageUrl = imgEl.getAttribute('data-old-hires') || imgEl.getAttribute('src') || '';
    }

    // ATC availability
    const atcEl = doc.querySelector('[data-action="fresh-add-to-cart"]');
    let hasATC = false;
    if (atcEl) hasATC = true;

    return { asin, title, price, description, features: bullets.slice(0, 8), details, size, imageUrl, hasATC };
}
