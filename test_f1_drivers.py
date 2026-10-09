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

    # Ensure on home
    page.goto("https://www.bet365.fr/#/HO/", wait_until="domcontentloaded")
    time.sleep(2.5)

    # Click Formule 1
    page.evaluate("""() => {
        const els = Array.from(document.querySelectorAll('.lhs-8, .lhs-1b'));
        const m = els.find(e => (e.innerText || '').trim().toLowerCase() === 'formule 1');
        if (m) m.click();
    }""")
    time.sleep(2.5)
    print("Page URL after Formule 1 click:", page.url)

    # Click Grand Prix de Singapour
    clicked_gp = page.evaluate("""() => {
        const els = Array.from(document.querySelectorAll('*'));
        const m = els.find(e => (e.innerText || '').trim().toLowerCase().includes('singapour') && e.children.length === 0);
        if (m) {
            m.click();
            return {clicked: true, text: m.innerText};
        }
        return {clicked: false};
    }""")
    print("Clicked GP:", clicked_gp)
    time.sleep(2.5)
    print("Page URL after GP click:", page.url)

    lines = [l.strip() for l in page.inner_text("body").split("\n") if l.strip()]
    print(f"Total lines: {len(lines)}")
    for i, l in enumerate(lines):
        if any(driver in l.lower() for driver in ['norris', 'verstappen', 'piastri', 'leclerc', 'russell', 'hamilton', 'sainz', 'vainqueur']):
            print(f"--- MATCH AT {i}: {l} ---")
            for j in range(max(0, i-5), min(len(lines), i+30)):
                print(f"  {j}: {lines[j]}")
            break
