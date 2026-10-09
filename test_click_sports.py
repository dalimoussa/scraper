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

    def click_sport(name):
        print(f"\n--- Testing click on '{name}' ---")
        clicked = page.evaluate("""(sportName) => {
            const els = Array.from(document.querySelectorAll('.crr-f2, .lhs-1b, .lhs-b8, .hsn-NavTab_Label'));
            const target = els.find(e => e.innerText && e.innerText.trim().toLowerCase() === sportName.toLowerCase());
            if (target) {
                target.click();
                return {clicked: true, tag: target.tagName, class: target.className};
            }
            return {clicked: false};
        }""", name)
        print("Clicked result:", clicked)
        time.sleep(3.0)
        print("New URL:", page.url)
        lines = [l.strip() for l in page.inner_text("body").split("\n") if l.strip()]
        print(f"DOM lines count: {len(lines)}")
        print("Sample 15 lines:")
        for l in lines[:15]:
            print("  ", l)
        return lines

    click_sport("Football")
    click_sport("Golf")
    click_sport("Formule 1")
