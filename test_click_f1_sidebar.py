import time
import sys
from bet365_internal import ensure_chrome_cdp

sys.stdout.reconfigure(encoding="utf-8")
ensure_chrome_cdp(9222)
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    ctx = browser.contexts[0]
    page = ctx.pages[0]

    # Navigate to home
    page.goto("https://www.bet365.fr/#/HO/", wait_until="domcontentloaded")
    time.sleep(3.0)

    # Click Formule 1 in sidebar
    print("Clicking Formule 1 in sidebar...")
    res = page.evaluate("""() => {
        const els = Array.from(document.querySelectorAll('.lhs-8, .lhs-1b, .crr-f2, .crr-3'));
        const m = els.find(e => {
            const t = (e.innerText || '').trim().toLowerCase();
            return t === 'formule 1' || t === 'formula 1';
        });
        if (m) {
            m.click();
            return {clicked: true, text: m.innerText, class: m.className};
        }
        return {clicked: false};
    }""")
    print("Formule 1 click result:", res)
    time.sleep(3.0)
    print("URL after click:", page.url)
    lines = [l.strip() for l in page.inner_text("body").split("\n") if l.strip()]
    print(f"Lines count: {len(lines)}")
    # Print lines that mention Grand Prix or drivers or courses
    for i, l in enumerate(lines[:60]):
        print(f"  {i}: {l}")
