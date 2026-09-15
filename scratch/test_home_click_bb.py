import time
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    context = browser.contexts[0]
    page = [pg for pg in context.pages if "bet365" in pg.url][0]
    
    print("Step 1: Navigating to https://www.bet365.com/ ...")
    page.goto("https://www.bet365.com/", wait_until="load")
    time.sleep(3.5)
    
    print("Step 2: Clicking Basketball in home bar...")
    clicked = page.evaluate('''() => {
        const els = Array.from(document.querySelectorAll('[class*="crr-"]'));
        const el = els.find(e => e.children.length === 0 && (e.innerText || '').trim().toLowerCase().includes('basket'));
        if (el) {
            el.click();
            return true;
        }
        return false;
    }''')
    print("Clicked:", clicked)
    time.sleep(3.0)
    print("URL after click:", page.url)
    lines = page.evaluate("() => document.body.innerText.split('\\n').map(l => l.trim()).filter(Boolean);")
    body_text = page.inner_text("body") or ""
    is_blocked = "Impossible d'afficher ce contenu" in body_text
    print(f"Total lines: {len(lines)} | Blocked: {is_blocked}")
    for l in lines[:25]:
        print("  ", l)
