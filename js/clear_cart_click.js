() => {
    // Dismiss any existing modal first
    const overlay = document.querySelector('.a-modal-scroller');
    if (overlay) {
        const closeBtn = overlay.querySelector('.a-button-close, [data-action="a-popover-close"]');
        if (closeBtn) closeBtn.click();
    }
}
