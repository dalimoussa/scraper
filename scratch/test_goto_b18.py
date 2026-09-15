import time
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    context = browser.contexts[0]
    page = [pg for pg in context.pages if "bet365" in pg.url][0]
    
    print("Navigating directly to https://www.bet365.com/#/AS/B18/ ...")
    page.goto("https://www.bet365.com/#/AS/B18/", wait_until="load")
    time.sleep(3.5)
    print("Current URL:", page.url)
    lines = page.evaluate("() => document.body.innerText.split('\\n').map(l => l.trim()).filter(Boolean);")
    print(f"Total lines: {len(lines)}")
    for l in lines[:30]:
        print("  ", l)
