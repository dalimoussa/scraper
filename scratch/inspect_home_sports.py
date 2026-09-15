import time
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    context = browser.contexts[0]
    page = [pg for pg in context.pages if "bet365" in pg.url][0]
    
    time.sleep(3.0)
    
    sports = page.evaluate('''() => {
        const all = Array.from(document.querySelectorAll('*'));
        const items = [];
        for (const el of all) {
            if (el.children.length === 0 && el.innerText && el.innerText.trim().length > 0 && el.innerText.trim().length < 25) {
                items.push({
                    text: el.innerText.trim(),
                    tag: el.tagName,
                    cls: el.className,
                    parentCls: el.parentElement ? el.parentElement.className : ''
                });
            }
        }
        return items;
    }''')
    seen = set()
    print("Found leaf elements:")
    for s in sports:
        t = s['text']
        if t not in seen:
            seen.add(t)
            if any(k in t.lower() for k in ['foot', 'tenn', 'basket', 'golf', 'hand', 'cycl', 'formu', 'f1', 'sport']):
                print(f"  {t} -> <{s['tag']} class='{s['cls']}'> (parent: {s['parentCls']})")
