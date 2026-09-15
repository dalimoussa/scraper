import time
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    context = browser.contexts[0]
    page = [pg for pg in context.pages if "bet365" in pg.url][0]
    
    sports = [
        ("Soccer", "Football"),
        ("Tennis", "Tennis"),
        ("Basketball", "Basketball"),
        ("Golf", "Golf"),
        ("F1", "Formule 1"),
        ("Cycling", "Cyclisme"),
        ("Handball", "Handball")
    ]
    
    for s_name, label in sports:
        page.goto("https://www.bet365.com/#/AZ/", wait_until="load")
        time.sleep(2.5)
        
        clicked = page.evaluate('''(targetLabel) => {
            const spans = Array.from(document.querySelectorAll('span.azm-38, [class*="azm-"]'));
            const el = spans.find(e => (e.innerText || '').trim().toLowerCase() === targetLabel.toLowerCase());
            if (el) {
                // Click parent or element
                (el.parentElement || el).click();
                return true;
            }
            return false;
        }''', label)
        time.sleep(3.0)
        lines = page.evaluate("() => document.body.innerText.split('\\n').map(l => l.trim()).filter(Boolean);")
        body_text = page.inner_text("body") or ""
        is_blocked = any(k in body_text for k in [
            "Impossible d'afficher ce contenu", 
            "Impossible to display this content", 
            "Page Not Available", 
            "Désolé, cette page n'est plus disponible"
        ])
        print(f"[{s_name}] Label '{label}' -> Clicked: {clicked} | URL: {page.url} | Lines: {len(lines)} | Blocked: {is_blocked}")
