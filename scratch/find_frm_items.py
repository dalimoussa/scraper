from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    context = browser.contexts[0]
    page = [pg for pg in context.pages if "bet365" in pg.url][0]
    
    items = page.evaluate('''() => {
        const els = Array.from(document.querySelectorAll('[class*="frm-"]'));
        return els.map(e => ({
            tag: e.tagName,
            cls: e.className,
            text: e.innerText.trim()
        })).filter(x => x.text && x.text.length < 30);
    }''')
    for item in items[:30]:
        print(item)
