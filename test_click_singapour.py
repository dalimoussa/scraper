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

    # Click GP de Singapour
    print("Clicking GP de Singapour...")
    clicked = page.evaluate("""() => {
        const els = Array.from(document.querySelectorAll('*'));
        const m = els.find(e => e.innerText && e.innerText.trim().toLowerCase().includes('gp de singapour') && e.children.length === 0);
        if (m) {
            m.click();
            return {clicked: true, tag: m.tagName, class: m.className, text: m.innerText};
        }
        return {clicked: false};
    }""")
    print("Clicked result:", clicked)
    time.sleep(3.0)
    print("Current URL:", page.url)
    lines = [l.strip() for l in page.inner_text("body").split("\n") if l.strip()]
    print(f"Lines count: {len(lines)}")
    for i, l in enumerate(lines[:35]):
        print(f"{i}: {l}")
