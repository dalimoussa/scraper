from playwright.sync_api import sync_playwright
import time

TARGET_SPORTS = ["Football", "Tennis", "Basketball", "Golf", "Formule 1"]

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    page = browser.contexts[0].pages[0]
    
    for sport in TARGET_SPORTS:
        print(f"\n--- Testing {sport} ---")
        page.goto("https://www.bet365.com/", wait_until="domcontentloaded")
        time.sleep(2.5)
        
        # Click the sport in .crr-6
        clicked = page.evaluate('''(sName) => {
            const els = Array.from(document.querySelectorAll('.crr-6'));
            const match = els.find(e => e.innerText.trim().toLowerCase() === sName.toLowerCase());
            if (match) {
                match.click();
                return true;
            }
            return false;
        }''', sport)
        
        if not clicked:
            print(f"Could not find button for {sport}")
            continue
            
        time.sleep(3.0)
        url = page.url
        text = page.evaluate("() => document.body.innerText")
        is_blocked = "Impossible" in text or "Désolé" in text
        print(f"URL: {url}")
        print(f"Blocked?: {is_blocked}")
        if not is_blocked:
            lines = [l.strip() for l in text.split('\n') if l.strip()]
            print(f"Lines count: {len(lines)}")
            print("Preview:", lines[:10])
        else:
            print("Page was blocked or empty!")
