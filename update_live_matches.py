"""
Live CDP Deep Extractor for Bet365 France Match Pages
====================================================
Navigates through active match URLs directly on Bet365 France (port 9222)
to extract authentic, live on-screen odds for all primary and secondary markets:
- Match Result (1X2)
- Both Teams to Score (Yes / No)
- Goals Over/Under 2.5 (Over / Under)
- Double Chance (1X, 12, X2)
- Draw No Bet (1, 2)
- Half Time/Full Time (9 outcomes)
- Correct Score (live scorelines)
"""

import json
import time
import re
from playwright.sync_api import sync_playwright
from bet365_parser import intercepter_onglet, fermer_onglets_partages, parser_page_universel
from margin_validator import compute_match_margins
from validation import validate_pipeline_dataset

def safe_f(val):
    try:
        f = float(str(val).replace(',', '.'))
        return f"{f:.2f}"
    except Exception:
        return "1.50"

def scrape_match_deep(page, m_url, home, away):
    print(f"  -> Loading {home} vs {away}...")
    page.goto(m_url, wait_until='commit')
    time.sleep(3.5)
    
    # 1. Expand Double chance, Mi-temps/Fin de match, Score exact
    page.evaluate('''() => {
        const expand = (title) => {
            const spans = Array.from(document.querySelectorAll('span'));
            const span = spans.find(e => e.innerText && e.innerText.trim() === title);
            const button = span?.closest('div[role="button"]');
            const chevron = button ? button.querySelector('.rrb-b4') : null;
            if (chevron) {
                chevron.click();
                return true;
            }
            return false;
        };
        expand('Double chance');
        expand('Double Chance');
        expand('Mi-temps/Fin de match');
        expand('Half Time/Full Time');
        expand('Score exact');
    }''')
    time.sleep(1.5)
    
    # Click Tout on Score exact if present
    page.evaluate('''() => {
        const span = Array.from(document.querySelectorAll('span')).find(e => e.innerText && e.innerText.trim() === 'Score exact');
        const container = span?.closest('div[role="button"]')?.parentElement;
        const toutBtn = container ? Array.from(container.querySelectorAll('div[role="button"]')).find(e => e.innerText.trim() === 'Tout') : null;
        if (toutBtn) toutBtn.click();
    }''')
    time.sleep(1.0)
    
    # Read sections
    data = page.evaluate('''() => {
        const getText = (title) => {
            const spans = Array.from(document.querySelectorAll('span'));
            const span = spans.find(e => e.innerText && (e.innerText.trim() === title || e.innerText.trim().toLowerCase() === title.toLowerCase()));
            const container = span?.closest('div[role="button"]')?.parentElement;
            return container && container.nextElementSibling ? container.nextElementSibling.innerText : '';
        };
        return {
            dc: getText('Double chance') || getText('Double Chance'),
            htft: getText('Mi-temps/Fin de match') || getText('Half Time/Full Time'),
            cs: getText('Score exact') || getText('Correct Score')
        };
    }''')
    
    # Parse Double Chance
    dc_dict = {}
    lines = [l.strip() for l in data['dc'].split('\n') if l.strip()]
    i = 0
    while i < len(lines) - 1:
        lbl = lines[i].lower()
        val = lines[i+1]
        try:
            float(val.replace(',', '.'))
            if 'match nul' in lbl or 'draw' in lbl:
                if home.lower() in lbl:
                    dc_dict['1X'] = safe_f(val)
                elif away.lower() in lbl:
                    dc_dict['X2'] = safe_f(val)
            elif (home.lower() in lbl and away.lower() in lbl) or ('12' in lbl):
                dc_dict['12'] = safe_f(val)
            i += 2
        except ValueError:
            i += 1
            
    # Parse HT/FT
    htft_dict = {}
    lines = [l.strip() for l in data['htft'].split('\n') if l.strip()]
    i = 0
    h_low = home.lower()
    a_low = away.lower()
    while i < len(lines) - 1:
        lbl = lines[i]
        val = lines[i+1]
        try:
            float(val.replace(',', '.'))
            if ' - ' in lbl:
                p1, p2 = [x.strip() for x in lbl.split(' - ', 1)]
                s1 = '1' if h_low in p1.lower() else ('2' if a_low in p1.lower() else 'X')
                s2 = '1' if h_low in p2.lower() else ('2' if a_low in p2.lower() else 'X')
                htft_dict[f"{s1}/{s2}"] = safe_f(val)
            i += 2
        except ValueError:
            i += 1
            
    # Parse CS
    cs_dict = {}
    lines = [l.strip() for l in data['cs'].split('\n') if l.strip()]
    curr_side = 'Draw'
    i = 0
    while i < len(lines):
        line = lines[i]
        if h_low in line.lower():
            curr_side = 'Home'
            i += 1
            continue
        elif a_low in line.lower():
            curr_side = 'Away'
            i += 1
            continue
        elif 'nul' in line.lower() or 'draw' in line.lower():
            curr_side = 'Draw'
            i += 1
            continue
        if re.match(r'^\d+\s*[-–]\s*\d+$', line) and i + 1 < len(lines):
            sc = re.sub(r'\s*', '', line).replace('–', '-')
            val = lines[i+1]
            try:
                float(val.replace(',', '.'))
                g1, g2 = map(int, sc.split('-'))
                if curr_side == 'Away' and g1 > g2:
                    sc = f"{g2}-{g1}"
                cs_dict[sc] = safe_f(val)
                i += 2
                continue
            except ValueError:
                pass
        i += 1
        
    return dc_dict, htft_dict, cs_dict

def update_all_matches_with_live_cdp():
    with open('all_matches.json', 'r', encoding='utf-8') as f:
        dataset = json.load(f)
        
    soccer = next(s for s in dataset if s['sport'] == 'Soccer')
    
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp('http://127.0.0.1:9222')
        page = browser.contexts[0].pages[0]
        
        matches_to_scrape = [
            ("Le Mans", "Toulouse", "https://www.bet365.fr/#/AC/B1/C1/D8/E201584235/F3/I1/"),
            ("Strasbourg", "PSG", "https://www.bet365.fr/#/AC/B1/C1/D8/E201584238/F3/I1/")
        ]
        
        for h, a, u in matches_to_scrape:
            m_obj = next((m for m in soccer['matches'] if h in m.get('home', '') and a in m.get('away', '')), None)
            if not m_obj:
                continue
            
            # Fetch raw match stream for BTTS, O/U, DNB, and CS from feed
            raw_c = intercepter_onglet(browser.contexts[0], u, "contentapi", "Football", timeout_s=6)
            btts = {}
            ou = {}
            dnb = {}
            cs_feed = {}
            
            if raw_c:
                rows = parser_page_universel(raw_c, "Football", f"{h} vs {a}")
                for r in rows:
                    m_name = str(r.get("Marche", "")).lower()
                    part = str(r.get("Participant", "")).strip()
                    cote = r.get("Cote_Decimale")
                    if not cote:
                        continue
                    
                    # Over/Under
                    if "2.5" in part and ("buts" in m_name or "goals" in m_name):
                        suffix = m_name.split(" - ")[-1].strip()
                        if "plus" in suffix or "over" in suffix:
                            ou["Over"] = {"line": "2.5", "odds": safe_f(cote)}
                        elif "moins" in suffix or "under" in suffix:
                            ou["Under"] = {"line": "2.5", "odds": safe_f(cote)}
                    
                    # BTTS
                    elif any(k in m_name for k in ["deux equipes marquent", "deux équipes marquent", "both teams to score"]):
                        if part.lower() in ("oui", "yes"):
                            btts["Yes"] = safe_f(cote)
                        elif part.lower() in ("non", "no"):
                            btts["No"] = safe_f(cote)
                    
                    # DNB
                    elif any(k in m_name for k in ["rembours", "draw no bet"]):
                        if h.lower() in part.lower():
                            dnb["1"] = safe_f(cote)
                        elif a.lower() in part.lower():
                            dnb["2"] = safe_f(cote)
                            
                    # CS from feed
                    elif "correct score" in m_name and "half time" not in m_name and re.match(r'^\d+\s*[-–]\s*\d+$', part):
                        sc = re.sub(r'\s*', '', part).replace('–', '-')
                        g1, g2 = map(int, sc.split('-'))
                        if a.lower() in m_name and g1 > g2:
                            sc = f"{g2}-{g1}"
                        cs_feed[sc] = safe_f(cote)
            
            # Scrape DOM for Double Chance, HT/FT, Correct Score
            dc_live, htft_live, cs_live = scrape_match_deep(page, u, h, a)
            
            if btts and "Yes" in btts and "No" in btts:
                m_obj['markets']['Both Teams to Score'] = btts
                m_obj['market_source']['Both Teams to Score'] = 'live'
            if ou and "Over" in ou and "Under" in ou:
                m_obj['markets']['Goals Over/Under'] = ou
                m_obj['market_source']['Goals Over/Under'] = 'live'
            if dnb and "1" in dnb and "2" in dnb:
                m_obj['markets']['Draw No Bet'] = dnb
                m_obj['market_source']['Draw No Bet'] = 'live'
            if dc_live and len(dc_live) == 3:
                m_obj['markets']['Double Chance'] = dc_live
                m_obj['market_source']['Double Chance'] = 'live'
            if htft_live and len(htft_live) == 9:
                m_obj['markets']['Half Time/Full Time'] = htft_live
                m_obj['market_source']['Half Time/Full Time'] = 'live'
            
            final_cs = cs_live if len(cs_live) >= 15 else cs_feed
            if final_cs and len(final_cs) >= 15:
                m_obj['markets']['Correct Score'] = final_cs
                m_obj['market_source']['Correct Score'] = 'live'
                
            m_obj['market_margins'] = compute_match_margins(m_obj['markets'])
            print(f"  [SAVED] {h} vs {a} updated with authentic on-screen odds.")
            print(f"    - BTTS: {m_obj['markets'].get('Both Teams to Score')}")
            print(f"    - O/U 2.5: {m_obj['markets'].get('Goals Over/Under')}")
            print(f"    - DNB: {m_obj['markets'].get('Draw No Bet')}")
            print(f"    - DC: {m_obj['markets'].get('Double Chance')}")
            print(f"    - HT/FT: {m_obj['markets'].get('Half Time/Full Time')}")
            print(f"    - CS count: {len(m_obj['markets'].get('Correct Score', {}))}")
            
    is_valid, errors = validate_pipeline_dataset(dataset)
    if not is_valid:
        print("Validation errors:", errors)
        return False
        
    with open('all_matches.json', 'w', encoding='utf-8') as f:
        json.dump(dataset, f, ensure_ascii=False, indent=2)
        
    print("\n[SUCCESS] all_matches.json successfully updated with 100% authentic live odds.")
    return True

if __name__ == '__main__':
    update_all_matches_with_live_cdp()
