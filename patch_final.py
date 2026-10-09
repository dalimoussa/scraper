target_path = r"C:\Users\medal\Downloads\bet365\test_sports_complet_final.py"
with open(target_path, "r", encoding="utf-8", errors="ignore") as f:
    content = f.read()

content = content.replace("PARALLEL_MATCHES = True", "PARALLEL_MATCHES = False", 1)

old_wait = """    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if FAST_MODE and ok[0] and raw[0] and 'PA;' in raw[0] and 'OD=' in raw[0]:
            break
        page.wait_for_timeout(POLL_MS)"""

new_wait = """    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            page.evaluate("window.scrollBy(0, 400);")
        except Exception:
            pass
        if FAST_MODE and ok[0] and raw[0] and 'PA;' in raw[0] and 'OD=' in raw[0]:
            break
        page.wait_for_timeout(POLL_MS)"""

if old_wait in content:
    content = content.replace(old_wait, new_wait, 1)

with open(target_path, "w", encoding="utf-8") as f:
    f.write(content)

print("[SUCCESS] test_sports_complet_final.py updated.")
