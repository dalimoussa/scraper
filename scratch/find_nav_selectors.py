from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    context = browser.contexts[0]
    page = [pg for pg in context.pages if "bet365" in pg.url][0]
    
    info = page.evaluate('''() => {
        const results = [];
        const all = Array.from(document.querySelectorAll('*'));
        for (const el of all) {
            const txt = (el.innerText || '').trim();
            if (txt === 'Football' || txt === 'Tennis' || txt === 'Basketball' || txt === 'Handball' || txt === 'Golf' || txt === 'Formule 1' || txt === 'Cyclisme') {
                results.push({
                    tag: el.tagName,
                    class: el.className,
                    text: txt,
                    parentClass: el.parentElement ? el.parentElement.className : ''
                });
            }
        }
        return results.slice(0, 20);
    }''')
    for item in info:
        print(item)
