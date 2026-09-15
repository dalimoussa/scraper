import time
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    context = browser.contexts[0]
    page = [pg for pg in context.pages if "bet365" in pg.url][0]
    
    # Clean reset
    page.goto("https://www.bet365.com/", wait_until="load")
    time.sleep(3.0)
    
    for sport in ["Football", "Tennis", "Basketball", "Golf", "F1"]:
        # Click sport
        clicked = page.evaluate('''(sName) => {
            const all = Array.from(document.querySelectorAll('*'));
            const match = all.find(e => {
                if (e.children.length > 0) return false;
                const t = (e.innerText || '').trim().toLowerCase();
                const target = sName.toLowerCase();
                return t === target 
                    || (target === 'soccer' && (t === 'football' || t === 'soccer'))
                    || (target === 'football' && (t === 'football' || t === 'soccer'))
                    || (target === 'tennis' && t === 'tennis')
                    || (target === 'basketball' && t.includes('basket'))
                    || (target === 'golf' && t === 'golf')
                    || (target === 'f1' && (t.includes('formule 1') || t.includes('formula 1') || t.includes('f1')));
            });
            if (match) {
                match.click();
                return true;
            }
            return false;
        }''', sport)
        time.sleep(2.5)
        lines = page.evaluate("() => document.body.innerText.split('\\n').map(l => l.trim()).filter(Boolean);")
        body_text = page.inner_text("body") or ""
        is_blocked = any(k in body_text for k in [
            "Impossible d'afficher ce contenu", 
            "Impossible to display this content", 
            "Page Not Available", 
            "Désolé, cette page n'est plus disponible"
        ])
        print(f"Sport: {sport} | Clicked: {clicked} | URL: {page.url} | Lines: {len(lines)} | Blocked: {is_blocked}")
        
        # Reset back to home for next sport
        page.goto("https://www.bet365.com/", wait_until="load")
        time.sleep(2.5)
