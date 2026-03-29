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

        // Title
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

        // Price
        let price = '';
        const priceEl = el.querySelector('.a-price .a-offscreen');
        if (priceEl) price = priceEl.textContent.trim();

        // Description
        let description = '';
        const descEls = el.querySelectorAll('.a-size-base-plus, .a-color-base:not(h2 span)');
        for (const d of descEls) {
            const t = d.textContent.trim();
            if (t.length > 10 && t !== title && !t.startsWith('$')) {
                description = t.substring(0, 150);
                break;
            }
        }

        // Size/weight
        let size = '';
        const sizeEl = el.querySelector('.a-size-base.a-color-secondary, .a-row .a-size-base');
        if (sizeEl) {
            const t = sizeEl.textContent.trim();
            if (t.length < 50 && !t.startsWith('$')) size = t;
        }

        // Check if add-to-cart data exists (indicates availability)
        const atcEl = el.querySelector('[data-action="fresh-add-to-cart"]');

        results.push({ asin, title, price, canAddToCart: !!atcEl, description, size });
    }
    return results;
}
