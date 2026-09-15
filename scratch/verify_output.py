import json
with open("all_matches.json", "r", encoding="utf-8") as f:
    data = json.load(f)
for s in data:
    sp = s.get("sport")
    ms = s.get("matches", [])
    m0 = ms[0] if ms else {}
    home = m0.get("home", "")
    away = m0.get("away", "")
    markets = list(m0.get("markets", {}).keys())[:3]
    print(f"{sp}: {len(ms)} matches | sample: {home} vs {away} | markets: {markets}")
total = sum(len(s["matches"]) for s in data)
print(f"TOTAL: {total} matches across {len(data)} sports")
