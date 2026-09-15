import subprocess
import json
from datetime import datetime

raw = subprocess.check_output(['git', 'show', '891d594:all_matches.json']).decode('utf-8', errors='replace')
data = json.loads(raw)

today = datetime(2026, 9, 15, 17, 0, 0)
total_updated = 0

for group in data:
    sp = group.get("sport")
    matches = group.get("matches", [])
    for m in matches:
        d_str = m.get("date", "")
        k_str = m.get("kickoff", "")
        dt = None
        if k_str:
            for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
                try:
                    dt = datetime.strptime(k_str, fmt)
                    break
                except Exception:
                    pass
        if not dt and d_str:
            for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
                try:
                    dt = datetime.strptime(d_str, fmt)
                    break
                except Exception:
                    pass
        
        if dt and dt <= today:
            # Shift to upcoming
            new_dt = dt.replace(year=2026, month=9, day=16)
            m["date"] = new_dt.strftime("%d/%m/%Y")
            if k_str:
                time_part = k_str.split(" ")[-1] if " " in k_str else "18:00:00"
                m["kickoff"] = f"{new_dt.strftime('%d/%m/%Y')} {time_part}"
            total_updated += 1

with open("seed_matches.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f"Successfully generated seed_matches.json with {sum(len(s['matches']) for s in data)} matches. Adjusted {total_updated} expired dates.")
for s in data:
    print(f"  {s['sport']}: {len(s['matches'])} matches")
