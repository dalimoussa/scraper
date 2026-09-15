from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    page = browser.contexts[0].pages[0]
    print("Trying page.goto('https://www.bet365.com/', wait_until='domcontentloaded')...")
    page.goto("https://www.bet365.com/", wait_until="domcontentloaded")
    time.sleep(4)
    text = page.evaluate("() => document.body.innerText")
    print("URL now:", page.url)
    print("Contains Impossible?:", "Impossible" in text)
    print("Snippet:\n", text[:300])
