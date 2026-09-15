import time
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    context = browser.contexts[0]
    page = [pg for pg in context.pages if "bet365" in pg.url][0]
    
    # Click Basketball
    clicked = page.evaluate('''() => {
        const all = Array.from(document.querySelectorAll('*'));
        // Find element that has text 'Basketball' and has no children (the innermost element)
        const el = all.find(e => e.innerText && e.innerText.trim() === 'Basketball' && e.children.length === 0);
        if (el) {
            // Click its parent or the element itself
            el.click();
            return {
                tag: el.tagName,
                cls: el.className,
                parentTag: el.parentElement ? el.parentElement.tagName : '',
                parentCls: el.parentElement ? el.parentElement.className : ''
            };
        }
        return null;
    }''')
    print("Clicked Basketball:", clicked)
    time.sleep(3.0)
    print("URL after click:", page.url)
    lines = page.evaluate("() => document.body.innerText.split('\\n').map(l => l.trim()).filter(Boolean);")
    print(f"Total lines: {len(lines)}")
    for l in lines[:30]:
        print("  ", l)
