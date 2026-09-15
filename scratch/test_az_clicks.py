import time
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    context = browser.contexts[0]
    page = [pg for pg in context.pages if "bet365" in pg.url][0]
    
    # Go to AZ
    page.goto("https://www.bet365.com/#/AZ/", wait_until="load")
    time.sleep(3.0)
    
    # Get all links/items under A-Z
    items = page.evaluate('''() => {
        const all = Array.from(document.querySelectorAll('*'));
        const azSection = all.filter(e => e.children.length === 0 && e.innerText && e.innerText.trim().length > 0 && e.innerText.trim().length < 30);
        return azSection.map(e => ({
            text: e.innerText.trim(),
            tag: e.tagName,
            cls: e.className
        }));
    }''')
    
    sports_to_check = ['Football', 'Tennis', 'Basketball', 'Handball', 'Cyclisme', 'Golf', 'Formule 1']
    for sp in sports_to_check:
        match = [x for x in items if x['text'].lower() == sp.lower()]
        print(f"Sport {sp}: {match}")
