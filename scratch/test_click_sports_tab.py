import time
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    context = browser.contexts[0]
    page = [pg for pg in context.pages if "bet365" in pg.url][0]
    
    # Click bottom tab Sports
    clicked = page.evaluate('''() => {
        const all = Array.from(document.querySelectorAll('a, button, div'));
        const el = all.find(e => e.innerText && e.innerText.trim() === 'Sports' && e.children.length === 0);
        if (el) {
            el.click();
            return true;
        }
        return false;
    }''')
    print("Clicked Sports tab:", clicked)
    time.sleep(2.5)
    print("URL after Sports tab click:", page.url)
    lines = page.evaluate("() => document.body.innerText.split('\\n').map(l => l.trim()).filter(Boolean);")
    print(f"Total lines: {len(lines)}")
    for l in lines[:40]:
        print("  ", l)
