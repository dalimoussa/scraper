from playwright.sync_api import sync_playwright
import re, time

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    page = browser.contexts[0].pages[0]
    
    # Navigate to Football cleanly
    print("Resetting to home...")
    page.goto("https://www.bet365.com/", wait_until="domcontentloaded")
    time.sleep(2.5)
    
    print("Clicking Football...")
    page.evaluate('''() => {
        const els = Array.from(document.querySelectorAll('.crr-6'));
        const m = els.find(e => e.innerText.trim().toLowerCase() === 'football');
        if (m) m.click();
    }''')
    time.sleep(3.0)
    
    lines = page.evaluate("() => document.body.innerText.split('\\n').map(l => l.trim()).filter(Boolean);")
    print(f"Captured {len(lines)} lines from Football page")
    
    matches = []
    curr_comp = "Football"
    i = 0
    date_regex = re.compile(r'^(Lun|Mar|Mer|Jeu|Ven|Sam|Dim|Mon|Tue|Wed|Thu|Fri|Sat|Sun)\.?\s+\d+', re.I)
    time_regex = re.compile(r'^\d{1,2}:\d{2}$')
    
    known_leagues = ['Premier League', 'La Liga', 'Serie A', 'Bundesliga', 'Ligue 1', 'Champions League', 'Europa League', 'Conference League', 'EFL Cup', 'FA Cup', 'Coppa Italia', 'Copa del Rey', 'Coupe de France', 'Championship', 'League 1', 'League 2']
    
    while i < len(lines):
        line = lines[i]
        
        # Check for league header
        if any(k.lower() in line.lower() for k in known_leagues) and not date_regex.match(line) and not time_regex.match(line) and not re.match(r'^\d', line):
            curr_comp = line
            i += 1
            continue
            
        # Match date
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

    print(f"Total Soccer matches extracted: {len(matches)}")
    for m in matches:
        comp = m['competition']
        h = m['home']
        a = m['away']
        ko = m['kickoff']
        d = m['date']
        mk = m['markets']['Match Result']
        print(f"  [{comp}] {h} vs {a} @ {ko} ({d}) -> 1: {mk['1']} | X: {mk['X']} | 2: {mk['2']}")
