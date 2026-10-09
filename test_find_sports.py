import time
import sys
from bet365_internal import ensure_chrome_cdp

sys.stdout.reconfigure(encoding="utf-8")
ensure_chrome_cdp(9222)
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    ctx = browser.contexts[0]
    page = ctx.pages[0]
    print("Current URL:", page.url)

    for _ in range(20):
        t = page.inner_text("body")
        if len(t) > 500:
            break
        time.sleep(0.5)

    print("Body length:", len(page.inner_text("body")))

    sports = ["Football", "Tennis", "Basketball", "Handball", "Cyclisme", "Golf", "Formule 1"]
    for sp in sports:
        res = page.evaluate("""(name) => {
            const all = Array.from(document.querySelectorAll('*'));
            const matches = all.filter(el => {
                if (!el.innerText) return false;
                return el.innerText.trim().toLowerCase() === name.toLowerCase() && el.children.length === 0;
            });
            return matches.map(el => ({
                tag: el.tagName,
                class: el.className,
                parentTag: el.parentElement ? el.parentElement.tagName : '',
                parentClass: el.parentElement ? el.parentElement.className : '',
                text: el.innerText.trim()
            }));
        }""", sp)
        print(f"Sport '{sp}': {len(res)} leaf elements found:")
        for r in res[:3]:
            print(f"  <{r['tag']} class='{r['class']}'> in <{r['parentTag']} class='{r['parentClass']}'>")
