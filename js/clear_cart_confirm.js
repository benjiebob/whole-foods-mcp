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
