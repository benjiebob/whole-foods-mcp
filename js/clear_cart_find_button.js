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
