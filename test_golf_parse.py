import time
import sys
import re
from bet365_internal import ensure_chrome_cdp

sys.stdout.reconfigure(encoding="utf-8")
ensure_chrome_cdp(9222)
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    ctx = browser.contexts[0]
    page = ctx.pages[0]

    # Navigate to Golf
    page.goto("https://www.bet365.fr/#/HO/", wait_until="domcontentloaded")
    time.sleep(2.0)
    page.evaluate("""() => {
        const els = Array.from(document.querySelectorAll('.lhs-8, .lhs-1b, .crr-f2'));
        const m = els.find(e => (e.innerText || '').trim().toLowerCase() === 'golf');
        if (m) m.click();
    }""")
    time.sleep(3.0)

    # Click Vainqueur final
    page.evaluate("""() => {
        const els = Array.from(document.querySelectorAll('*'));
        const m = els.find(e => (e.innerText || '').trim().toLowerCase() === 'vainqueur final' && e.children.length === 0);
        if (m) m.click();
    }""")
    time.sleep(3.0)

    lines = [l.strip() for l in page.inner_text("body").split("\n") if l.strip()]
    odd_re = re.compile(r'^\d+([.,]\d+)?$')
    print("Total lines:", len(lines))

    # Look for golfers and odds
    golfers = {}
    for i in range(len(lines) - 1):
        name = lines[i]
        val = lines[i+1].replace(',', '.')
        if (odd_re.match(val) and 1.5 <= float(val) <= 1000.0 and
            len(name) > 3 and not odd_re.match(name) and not name.isdigit() and
            not any(b in name.lower() for b in ['vainqueur', 'paris', 'misez', 'gagnez', 'options', 'open', 'tournoi', 'afficher', 'tout voir'])):
            golfers[name] = val

    print(f"Captured {len(golfers)} golfers:")
    for g, o in list(golfers.items())[:10]:
        print(f"  {g}: {o}")
