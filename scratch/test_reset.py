import time
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    context = browser.contexts[0]
    page = [pg for pg in context.pages if "bet365" in pg.url][0]
    
    print("Doing full reload to https://www.bet365.com/...")
    page.goto("https://www.bet365.com/", wait_until="load")
    time.sleep(4.0)
    print("URL after reload:", page.url)
    lines = page.evaluate("() => document.body.innerText.split('\\n').map(l => l.trim()).filter(Boolean);")
    print(f"Total lines: {len(lines)}")
    for l in lines[:20]:
        print("  ", l)
