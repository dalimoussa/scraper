from playwright.sync_api import sync_playwright
import time, re, json, os

def parse_soccer_dom(lines):
    matches = []
    curr_comp = "Football"
    i = 0
    date_regex = re.compile(r'^(Lun|Mar|Mer|Jeu|Ven|Sam|Dim|Mon|Tue|Wed|Thu|Fri|Sat|Sun)\.?\s+\d+', re.I)
    time_regex = re.compile(r'^\d{1,2}:\d{2}$')
    known_leagues = ['Premier League', 'La Liga', 'Serie A', 'Bundesliga', 'Ligue 1', 'Champions League', 'Europa League', 'Conference League', 'EFL Cup', 'FA Cup', 'Coppa Italia', 'Copa del Rey', 'Coupe de France', 'Championship', 'League 1', 'League 2']
    
    while i < len(lines):
        line = lines[i]
        if any(k.lower() in line.lower() for k in known_leagues) and not date_regex.match(line) and not time_regex.match(line) and not re.match(r'^\d', line):
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
                    od1, odX, od2 = None, None, None
                    end_idx = i + 4
                    for j in range(i + 3, min(i + 18, len(lines) - 1)):
                        if lines[j] == '1' and re.match(r'^\d+\.\d+$', lines[j+1]):
                            od1 = lines[j+1]
                        elif lines[j] == 'X' and re.match(r'^\d+\.\d+$', lines[j+1]):
                            odX = lines[j+1]
                        elif lines[j] == '2' and re.match(r'^\d+\.\d+$', lines[j+1]) and od1 is not None and odX is not None:
                            od2 = lines[j+1]
                            end_idx = j + 2
                            break
                    if od1 and odX and od2:
                        match_id = str(abs(hash(f"{t1}_{t2}_{date_str}")) % 100000000)
                        matches.append({
                            "id": match_id,
                            "date": date_str,
                            "kickoff": time_cand,
                            "competition": curr_comp,
                            "home": t1,
                            "away": t2,
                            "markets": {
                                "Match Result": {"1": od1, "X": odX, "2": od2}
                            }
                        })
                        i = end_idx - 1
        i += 1
    return matches

def parse_tennis_dom(lines):
    matches = []
    curr_comp = "Tennis"
    i = 0
    date_regex = re.compile(r'^(Lun|Mar|Mer|Jeu|Ven|Sam|Dim|Mon|Tue|Wed|Thu|Fri|Sat|Sun)\.?\s+\d+', re.I)
    time_regex = re.compile(r'^\d{1,2}:\d{2}$')
    
    while i < len(lines):
        line = lines[i]
        if any(c in line for c in ['WTA', 'ATP', 'Challenger', 'Tour', 'Open', 'ITF', 'UTR', 'Coupe', 'Grand Slam']) and not date_regex.match(line) and not time_regex.match(line) and not re.match(r'^\d', line):
            curr_comp = line
            i += 1
            continue
            
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
    return matches

def parse_basketball_dom(lines):
    matches = []
    curr_comp = "Basketball"
    i = 0
    date_regex = re.compile(r'^(Lun|Mar|Mer|Jeu|Ven|Sam|Dim|Mon|Tue|Wed|Thu|Fri|Sat|Sun)\.?\s+\d+', re.I)
    time_regex = re.compile(r'^\d{1,2}:\d{2}$')
    
    while i < len(lines):
        line = lines[i]
        if any(k in line for k in ['Champions League', 'NBA', 'Euroleague', 'Eurocup', 'NCAA', 'Liga', 'Pro A', 'BBL', 'Serie A', 'Basketball', 'Cup']) and not date_regex.match(line) and not time_regex.match(line) and not re.match(r'^\d', line):
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
                    for j in range(i + 3, min(i + 25, len(lines) - 1)):
                        if lines[j].lower() in ['money line', 'vainqueur du match', 'to win']:
                            if j + 2 < len(lines) and re.match(r'^\d+\.\d+$', lines[j+1]) and re.match(r'^\d+\.\d+$', lines[j+2]):
                                ml_1 = lines[j+1]
                                ml_2 = lines[j+2]
                                end_idx = j + 3
                                break
                        if lines[j].lower() == 'spread':
                            if j + 4 < len(lines) and re.match(r'^[+-]?\d+\.?\d*$', lines[j+1]) and re.match(r'^\d+\.\d+$', lines[j+2]):
                                spread_h = f"{lines[j+1]} ({lines[j+2]})"
                                spread_a = f"{lines[j+3]} ({lines[j+4]})"
                        if lines[j].lower() == 'total':
                            if j + 4 < len(lines) and 'O' in lines[j+1] and re.match(r'^\d+\.\d+$', lines[j+2]):
                                tot_line = lines[j+1].replace('O', '').strip()
                                tot_o = lines[j+2]
                                tot_u = lines[j+4]
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
    return matches

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    page = browser.contexts[0].pages[0]
    
    sports_to_scrape = [
        ("Soccer", "Football", parse_soccer_dom),
        ("Tennis", "Tennis", parse_tennis_dom),
        ("Basketball", "Basketball", parse_basketball_dom)
    ]
    
    all_results = {}
    
    for sport_label, nav_name, parser_fn in sports_to_scrape:
        print(f"\n[*] Scraping {sport_label}...")
        
        # 1. Reset to home
        page.goto("https://www.bet365.com/", wait_until="domcontentloaded")
        time.sleep(2.5)
        
        # 2. Click sport bar icon
        clicked = page.evaluate('''(sName) => {
            const els = Array.from(document.querySelectorAll('.crr-6'));
            const m = els.find(e => e.innerText.trim().toLowerCase() === sName.toLowerCase());
            if (m) {
                m.click();
                return true;
            }
            return false;
        }''', nav_name)
        
        if not clicked:
            print(f"  [Warning] Could not find nav button for {nav_name}")
            continue
            
        time.sleep(3.0)
        lines = page.evaluate("() => document.body.innerText.split('\\n').map(l => l.trim()).filter(Boolean);")
        print(f"  Captured {len(lines)} lines from DOM")
        
        matches = parser_fn(lines)
        print(f"  [OK] {sport_label}: {len(matches)} live matches parsed from DOM!")
        for m in matches[:3]:
            print(f"    + {m['competition']}: {m['home']} vs {m['away']} -> {list(m['markets'].keys())}")
            
        all_results[sport_label] = matches

    print(f"\n[Summary] Total live matches extracted: {sum(len(v) for v in all_results.values())}")
