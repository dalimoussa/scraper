import time
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    context = browser.contexts[0]
    page = [pg for pg in context.pages if "bet365" in pg.url][0]
    
    print("Initial URL:", page.url)
    # Find element with text 'Accueil' or 'Sports'
    clicked = page.evaluate('''() => {
        const all = Array.from(document.querySelectorAll('*'));
        const el = all.find(e => e.innerText && e.innerText.trim() === 'Accueil' && e.children.length === 0);
        if (el) {
            el.click();
            return true;
        }
        return false;
    }''')
    print("Clicked Accueil:", clicked)
    time.sleep(3.0)
    print("After click URL:", page.url)
    
    lines = page.evaluate("() => document.body.innerText.split('\\n').map(l => l.trim()).filter(Boolean);")
    print(f"Total lines now: {len(lines)}")
    for l in lines[:15]:
        print("  ", l)
