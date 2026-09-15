import re
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    context = browser.contexts[0]
    page = [pg for pg in context.pages if "bet365" in pg.url][0]
    lines = page.evaluate("() => document.body.innerText.split('\\n').map(l => l.trim()).filter(Boolean);")

date_regex = re.compile(r'^(Lun|Mar|Mer|Jeu|Ven|Sam|Dim|Mon|Tue|Wed|Thu|Fri|Sat|Sun)\.?\s+\d+', re.I)
time_regex = re.compile(r'^\d{1,2}:\d{2}$')

matches = []
curr_comp = "Basketball"
i = 0

while i < len(lines):
    line = lines[i]
    if any(k in line for k in ['Champions League', 'NBA', 'Euroleague', 'Eurocup', 'NCAA', 'Liga', 'Pro A', 'BBL', 'Serie A', 'Basketball', 'Cup', 'Qualifications']) and not date_regex.match(line) and not time_regex.match(line) and not re.match(r'^\d', line):
        curr_comp = line
        i += 1
        continue

    if date_regex.match(line):
        date_str = line
        if i + 3 < len(lines):
            t1 = lines[i+1]
            t2 = lines[i+2]
            time_cand = lines[i+3]
            if time_regex.match(time_cand) and len(t1) > 2 and len(t2) > 2:
                spread_h, spread_a, tot_line, tot_o, tot_u, ml_1, ml_2 = None, None, None, None, None, None, None
                end_idx = i + 4
                for j in range(i + 4, min(i + 25, len(lines))):
                    if date_regex.match(lines[j]) or (time_regex.match(lines[j]) and j > i + 3):
                        # Next match starts!
                        break
                    lj = lines[j].lower().strip()
                    if lj in ['money line', 'vainqueur', 'vainqueur du match', 'to win']:
                        if j + 2 < len(lines) and re.match(r'^\d+\.\d+$', lines[j+1]) and re.match(r'^\d+\.\d+$', lines[j+2]):
                            ml_1 = lines[j+1]
                            ml_2 = lines[j+2]
                            end_idx = max(end_idx, j + 3)
                            break # Vainqueur is typically the last market column
                    elif lj in ['spread', 'handicap', 'écart']:
                        if j + 4 < len(lines) and re.match(r'^[+-]?\d+\.?\d*$', lines[j+1]) and re.match(r'^\d+\.\d+$', lines[j+2]):
                            spread_h = f"{lines[j+1]} ({lines[j+2]})"
                            spread_a = f"{lines[j+3]} ({lines[j+4]})"
                            end_idx = max(end_idx, j + 5)
                    elif lj in ['total']:
                        if j + 4 < len(lines) and re.match(r'^\d+\.\d+$', lines[j+2]) and re.match(r'^\d+\.\d+$', lines[j+4]):
                            t_num = re.sub(r'^[PMOUpmou]\s*', '', lines[j+1]).strip()
                            tot_line = t_num
                            tot_o = lines[j+2]
                            tot_u = lines[j+4]
                            end_idx = max(end_idx, j + 5)
                if ml_1 and ml_2:
                    match_id = str(abs(hash(f"{t1}_{t2}_{date_str}")) % 100000000)
                    mkts = {"Money Line": {"1": ml_1, "2": ml_2}}
                    if spread_h and spread_a:
                        mkts["Point Spread"] = {"1": spread_h, "2": spread_a}
                    if tot_line and tot_o and tot_u:
                        mkts["Total Points"] = {"Over": f"Over {tot_line} ({tot_o})", "Under": f"Under {tot_line} ({tot_u})"}
                    matches.append({
                        "id": match_id,
                        "date": date_str,
                        "kickoff": time_cand,
                        "competition": curr_comp,
                        "home": t1,
                        "away": t2,
                        "markets": mkts
                    })
                    i = end_idx - 1
    i += 1

print(f"Extracted {len(matches)} matches:")
import json
print(json.dumps(matches, indent=2))
