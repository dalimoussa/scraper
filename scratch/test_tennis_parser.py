from playwright.sync_api import sync_playwright
import re

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    page = browser.contexts[0].pages[0]
    lines = page.evaluate("() => document.body.innerText.split('\\n').map(l => l.trim()).filter(Boolean);")
    
    matches = []
    curr_comp = "Tennis"
    i = 0
    date_regex = re.compile(r'^(Lun|Mar|Mer|Jeu|Ven|Sam|Dim|Mon|Tue|Wed|Thu|Fri|Sat|Sun)\.?\s+\d+', re.I)
    time_regex = re.compile(r'^\d{1,2}:\d{2}$')
    
    while i < len(lines):
        line = lines[i]
        # Competition header
        if any(c in line for c in ['WTA', 'ATP', 'Challenger', 'Tour', 'Open', 'ITF', 'UTR', 'Coupe', 'Grand Slam']) and not date_regex.match(line) and not time_regex.match(line) and not re.match(r'^\d', line):
            curr_comp = line
            i += 1
            continue
            
        # Match date
        if date_regex.match(line):
            date_str = line
            if i + 3 < len(lines):
                p1 = lines[i+1]
                p2 = lines[i+2]
                time_cand = lines[i+3]
                if time_regex.match(time_cand) and len(p1) > 2 and len(p2) > 2:
                    od1, od2 = None, None
                    end_idx = i + 4
                    for j in range(i + 3, min(i + 14, len(lines) - 1)):
                        if lines[j] == '1' and re.match(r'^\d+\.\d+$', lines[j+1]):
                            od1 = lines[j+1]
                        elif lines[j] == '2' and re.match(r'^\d+\.\d+$', lines[j+1]) and od1 is not None:
                            od2 = lines[j+1]
                            end_idx = j + 2
                            break
                    if od1 and od2:
                        match_id = str(abs(hash(f"{p1}_{p2}_{date_str}")) % 100000000)
                        matches.append({
                            "id": match_id,
                            "date": date_str,
                            "kickoff": time_cand,
                            "competition": curr_comp,
                            "home": p1,
                            "away": p2,
                            "markets": {
                                "To Win Match": {"1": od1, "2": od2}
                            }
                        })
                        i = end_idx - 1
        i += 1

    print(f"Total Tennis matches extracted: {len(matches)}")
    for m in matches:
        comp = m['competition']
        h = m['home']
        a = m['away']
        ko = m['kickoff']
        d = m['date']
        o1 = m['markets']['To Win Match']['1']
        o2 = m['markets']['To Win Match']['2']
        print(f"  [{comp}] {h} vs {a} @ {ko} ({d}) -> 1: {o1} | 2: {o2}")
