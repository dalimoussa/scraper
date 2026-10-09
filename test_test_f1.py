import time
import sys
from bet365_internal import ensure_chrome_cdp, parse_f1_from_dom_lines, resolve_f1_match

sys.stdout.reconfigure(encoding="utf-8")
ensure_chrome_cdp(9222)
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    ctx = browser.contexts[0]
    page = ctx.pages[0]

    # Ensure on home page
    if "/#/HO/" not in page.url and page.url != "https://www.bet365.fr/":
        page.goto("https://www.bet365.fr/#/HO/", wait_until="domcontentloaded")
        time.sleep(2.0)

    # Click GP de Singapour
    clicked = page.evaluate("""() => {
        const els = Array.from(document.querySelectorAll('*'));
        const m = els.find(e => e.innerText && e.innerText.trim().toLowerCase() === 'gp de singapour' && e.children.length === 0);
        if (m) {
            m.click();
            return true;
        }
        return false;
    }""")
    print("Clicked GP de Singapour:", clicked)
    time.sleep(2.5)

    lines = [l.strip() for l in page.inner_text("body").split("\n") if l.strip()]
    gp_name, mkts = parse_f1_from_dom_lines(lines)
    print("Parsed GP name:", gp_name)
    print("Markets:", list(mkts.keys()))
    for mkt, odds in mkts.items():
        print(f"  {mkt}: {len(odds)} items -> {list(odds.items())[:5]}")
