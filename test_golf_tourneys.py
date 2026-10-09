import time
import sys
from bet365_internal import ensure_chrome_cdp, parse_golf_outright_page

sys.stdout.reconfigure(encoding="utf-8")
ensure_chrome_cdp(9222)
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    ctx = browser.contexts[0]
    page = ctx.pages[0]

    # Navigate to home
    page.goto("https://www.bet365.fr/#/HO/", wait_until="domcontentloaded")
    time.sleep(2.5)

    # Click Golf in sidebar
    page.evaluate("""() => {
        const els = Array.from(document.querySelectorAll('.lhs-8, .lhs-1b'));
        const m = els.find(e => (e.innerText || '').trim().toLowerCase() === 'golf');
        if (m) m.click();
    }""")
    time.sleep(2.5)
    print("Page URL after Golf click:", page.url)

    # Click Open d'Espagne
    clicked_espagne = page.evaluate("""() => {
        const els = Array.from(document.querySelectorAll('*'));
        const m = els.find(e => {
            const t = (e.innerText || '').trim().toLowerCase();
            return (t.includes("espagne") && t.includes("open")) && e.children.length === 0;
        });
        if (m) {
            m.click();
            return {clicked: true, text: m.innerText};
        }
        return {clicked: false};
    }""")
    print("Clicked tourney:", clicked_espagne)
    time.sleep(3.0)
    print("URL after click:", page.url)

    lines_after = [l.strip() for l in page.inner_text("body").split("\n") if l.strip()]
    outrights = parse_golf_outright_page(lines_after, "Open d'Espagne")
    print(f"Captured {len(outrights)} outright odds for Open d'Espagne:")
    for k, v in list(outrights.items())[:10]:
        print(f"  {k}: {v}")
