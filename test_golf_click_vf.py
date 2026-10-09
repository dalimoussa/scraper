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

    # Go to Golf page
    page.goto("https://www.bet365.fr/#/HO/", wait_until="domcontentloaded")
    time.sleep(2.0)
    page.evaluate("""() => {
        const els = Array.from(document.querySelectorAll('.lhs-8, .lhs-1b, .crr-f2'));
        const m = els.find(e => (e.innerText || '').trim().toLowerCase() === 'golf');
        if (m) m.click();
    }""")
    time.sleep(3.0)

    # Click first 'Vainqueur final'
    clicked_vf = page.evaluate("""() => {
        const els = Array.from(document.querySelectorAll('*'));
        const m = els.find(e => (e.innerText || '').trim().toLowerCase() === 'vainqueur final' && e.children.length === 0);
        if (m) {
            m.click();
            return {clicked: true, text: m.innerText};
        }
        return {clicked: false};
    }""")
    print("Clicked Vainqueur final:", clicked_vf)
    time.sleep(3.0)
    print("Current URL:", page.url)
    lines = [l.strip() for l in page.inner_text("body").split("\n") if l.strip()]
    print(f"Total lines: {len(lines)}")
    for i, l in enumerate(lines[:60]):
        print(f"  {i}: {l}")
