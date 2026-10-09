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
    with open("golf_lines_dump.txt", "w", encoding="utf-8") as f:
        for i, l in enumerate(lines):
            f.write(f"{i}: {l}\n")
    print(f"Dumped {len(lines)} lines to golf_lines_dump.txt")
