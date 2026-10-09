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

    lines = [l.strip() for l in page.inner_text("body").split("\n") if l.strip()]
    for i in range(55, min(len(lines), 160)):
        print(f"{i}: {lines[i]}")
