import time
from playwright.sync_api import sync_playwright

SPORT_CODES = [
    ("Soccer", "B1"),
    ("Tennis", "B13"),
    ("Basketball", "B18"),
    ("Handball", "B7"),
    ("Cycling", "B16"),
    ("Golf", "B3"),
    ("F1", "B10")
]

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    context = browser.contexts[0]
    page = [pg for pg in context.pages if "bet365" in pg.url][0]

    for sport, code in SPORT_CODES:
        url = f"https://www.bet365.com/#/AS/{code}/"
        print(f"\nNavigating to {sport} ({url})...")
        page.evaluate(f"window.location.hash = '#/AS/{code}/';")
        time.sleep(3.0)
        
        body_text = page.inner_text("body") or ""
        lines = page.evaluate("() => document.body.innerText.split('\\n').map(l => l.trim()).filter(Boolean);")
        
        is_blocked = any(k in body_text for k in [
            "Impossible d'afficher ce contenu", 
            "Impossible to display this content", 
            "Page Not Available", 
            "Désolé, cette page n'est plus disponible"
        ])
        print(f"  Result: {len(lines)} DOM lines. Blocked: {is_blocked}")
        if is_blocked:
            print("  [ERROR] Page blocked or unavailable!")
        else:
            print("  Top 5 lines:", lines[:5])
