from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    context = browser.contexts[0]
    pages = [pg for pg in context.pages if "bet365" in pg.url]
    if not pages:
        print("No bet365 page found!")
        exit(1)
    page = pages[0]
    print("Page URL:", page.url)
    lines = page.evaluate("() => document.body.innerText.split('\\n').map(l => l.trim()).filter(Boolean);")
    print(f"Total lines: {len(lines)}")
    for idx, l in enumerate(lines[:120]):
        print(f"{idx}: {l}")
