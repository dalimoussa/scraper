"""
bet365_parser.py
======================================
Module de parsing unifie gérant les 4 architectures réseau de Bet365.
Super Parseur mis à jour : Structure nette des marchés, des sélections, 
des lignes (Over/Under, Handicaps) et des vainqueurs de match.

Usage :
    python bet365_parser.py
"""

import json
import time
import re
import sys
import os
from collections import Counter
from fractions import Fraction
from playwright.sync_api import sync_playwright
from concurrent.futures import ThreadPoolExecutor, as_completed

# ─── PARAMÈTRES GLOBAUX ───────────────────────────────────────────────────────
CDP_PORT        = 9222
POLL_MS         = 150
TIMEOUT_S       = 8
NB_MAX          = 3  # Nombre maximal de compétitions/groupes
NB_MAX_MARCHES  = 3  # Nombre maximal de marchés ou fixtures détaillées

FAST_MODE       = True
BLOCK_HEAVY_RESOURCES = True
PARALLEL_MATCHES = True
MAX_MATCH_WORKERS = 5

ENABLE_DEBUG    = True
TRACE_LOG_FILE   = 'DEBUG_BET365_trace.log'


def log_trace(message):
    """Écrit un log de diagnostic dans le terminal et dans un fichier."""
    if not ENABLE_DEBUG:
        return
    ligne = '[TRACE] ' + str(message)
    print(ligne)
    try:
        with open(TRACE_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(ligne + '\n')
    except Exception:
        pass


COUPON_MATCH = "matchbettingcontentapi/coupon"
COUPON_OTHER = "othersportsmatch"

CHAMPIONNATS_VOULUS = {
    "France Super Cup", "Spain La Liga", "England Premier League",
    "England Championship", "England EFL Cup", "UEFA Champions League Qualifying",
    "UEFA Europa League Qualifying", "UEFA Conference League Qualifying",
    "Italy Serie A", "Italy Serie B", "Spain Segunda",
    "Germany Bundesliga I", "Germany Super Cup", "France Ligue 1",
    "Portugal Primeira Liga", "Copa Libertadores", "Copa Sudamericana",
}

SPORTS_DIRECTS = [
    {
        "nom": "Football", "url": "https://www.bet365.fr/#/AS/B1/K%5E5/",
        "mode": "football_dynamic", "api_splash": "splashcontentapi/soccertab", "coupon_api": COUPON_MATCH
    },
    {
        "nom": "Tennis", "url": "https://www.bet365.fr/#/AS/B13/K%5E5/",
        "mode": "splash_to_markets", "api_splash": "splashcontentapi/tennistab", "coupon_api": COUPON_MATCH
    },
    {
        "nom": "Formule 1", "url": "https://www.bet365.fr/#/AS/B10/",
        "mode": "splash_to_markets", "api_splash": "splashcontentapi/splash", "coupon_api": COUPON_OTHER
    },
    {
        "nom": "Rugby League", "url": "https://www.bet365.fr/#/AS/B19/",
        "mode": "splash_to_coupon", "api_splash": "splashcontentapi/getsplashpods", "coupon_api": COUPON_OTHER
    },
    {
        "nom": "Rugby XV", "url": "https://www.bet365.fr/#/AS/B8/K%5E5/", "mode": "splash_to_coupon", "api_splash": "splashcontentapi/competitions", "coupon_api": COUPON_OTHER
    },
    {
        "nom": "Golf", "url": "https://www.bet365.fr/#/AS/B7/",
        "mode": "splash_to_markets", "api_splash": "splashcontentapi/splash", "coupon_api": COUPON_OTHER
    },
    {
        "nom": "Cyclisme", "url": "https://www.bet365.fr/#/AS/B38/",
        "mode": "splash_to_coupon", "api_splash": "splashcontentapi/splash", "coupon_api": COUPON_OTHER
    },
    {
        "nom": "MMA", "url": "https://www.bet365.fr/#/AS/B162/",
        "mode": "splash_to_coupon", "api_splash": "splashcontentapi/splash", "coupon_api": COUPON_OTHER
    },
    {
        "nom": "Basket NBA", "url": "https://www.bet365.fr/#/AC/B18/C20604387/D48/E1453/F10/",
        "mode": "direct_markets", "api_splash": "matchmarketscontentapi/markets", "coupon_api": "contentapi"
    },
    {
        "nom": "Baseball", "url": "https://www.bet365.fr/#/AC/B16/C20525425/D48/E1096/F10/",
        "mode": "direct_markets", "api_splash": "matchmarketscontentapi/markets", "coupon_api": "contentapi"
    }
]

PV_DEFAULT_CHART_7 = [
    (1.0, 1.001, 0.0), (1.001, 1.002, 0.0), (1.002, 1.003, 0.001),
    (1.003, 1.004, 0.0015), (1.004, 1.006, 0.002), (1.006, 1.008, 0.003),
    (1.008, 1.01, 0.004), (1.01, 1.015, 0.005), (1.015, 1.02, 0.0075),
    (1.02, 1.025, 0.01), (1.025, 1.03, 0.015), (1.03, 1.04, 0.017),
    (1.04, 1.05, 0.02), (1.05, 1.06, 0.025), (1.06, 1.08, 0.03),
    (1.08, 1.1, 0.04), (1.1, 1.12, 0.04), (1.12, 1.15, 0.04),
    (1.15, 1.2, 0.05), (1.2, 1.25, 0.05), (1.25, 1.3, 0.05),
    (1.3, 1.35, 0.05), (1.35, 1.4, 0.05), (1.4, 1.45, 0.05),
    (1.45, 1.5, 0.05), (1.5, 1.55, 0.06), (1.55, 1.6, 0.06),
    (1.6, 1.7, 0.06), (1.7, 1.8, 0.06), (1.8, 1.9, 0.06),
    (1.9, 2.0, 0.06), (2.0, 2.1, 0.06), (2.1, 2.2, 0.07),
    (2.2, 2.3, 0.07), (2.3, 2.4, 0.07), (2.4, 2.5, 0.07),
    (2.5, 2.6, 0.08), (2.6, 2.7, 0.08), (2.7, 2.8, 0.08),
    (2.8, 2.9, 0.1), (2.9, 3.0, 0.1), (3.0, 3.2, 0.1),
    (3.2, 3.4, 0.15), (3.4, 3.6, 0.15), (3.6, 3.8, 0.15),
    (3.8, 4.0, 0.15), (4.0, 4.5, 0.2), (4.5, 5.0, 0.2),
    (5.0, 5.5, 0.25), (5.5, 6.0, 0.3), (6.0, 6.5, 0.4),
    (6.5, 7.0, 0.5), (7.0, 8.0, 0.7), (8.0, 9.0, 0.8),
    (9.0, 11.0, 1.0), (11.0, 13.0, 1.5), (13.0, 15.0, 2.0),
    (15.0, 17.0, 2.5), (17.0, 19.0, 3.0), (19.0, 21.0, 3.5),
    (21.0, 26.0, 4.0), (26.0, 31.0, 4.5), (31.0, 41.0, 5.0),
    (41.0, 51.0, 5.5), (51.0, 61.0, 6.0), (61.0, 71.0, 7.0),
    (71.0, 81.0, 8.0), (81.0, 91.0, 9.0), (91.0, 101.0, 10.0),
    (101.0, 121.0, 12.0), (121.0, 151.0, 14.0), (151.0, 201.0, 16.0),
    (201.0, 351.0, 18.0), (351.0, 501.0, 20.0), (501.0, 751.0, 25.0),
    (751.0, 1001.0, 35.0), (1001.0, 10001.0, 50.0),
]


def est_cyclisme(nom_sport):
    return str(nom_sport or '').strip().lower() in {'cyclisme', 'cycling'}


def appliquer_pv_fallback(row):
    """PV deduction disabled per user requirement - preserves exact on-screen decimal odds."""
    return False


def parse_bet365(raw):
    blocs = []
    for block in raw.split('|'):
        if not block.strip():
            continue
        parts = block.split(';')
        d = {'_type': parts[0]}
        for part in parts[1:]:
            if '=' in part:
                k, v = part.split('=', 1)
                d[k] = v
        blocs.append(d)
    return blocs


def fraction_to_decimal(s):
    try:
        if '/' in s:
            n, d = s.split('/')
            return round(int(n) / int(d) + 1.0, 2)
        return float(s) if s else 0.0
    except Exception:
        return 0.0


def appliquer_pv_js(page, resultats, ki, l3, fixture_started="0"):
    """
    Applique le Price Variance de Bet365 via le JS de la page.
    Remplace Cote_Fraction et Cote_Decimale par les valeurs ajustées.
    """
    JS_APPLY_PV = """
    (rows, ki, l3) => {
        const lib = window.PriceVarianceLib || window.ns_pricevariancelib || window.ns_pricevariancelib_util;
        if (!lib || !lib.pvOdds || typeof lib.pvOdds.getAdjustmentValue !== 'function') return rows;
        const toFraction = (decimal) => {
            const target = Number(decimal) - 1;
            let bestN = 0, bestD = 1, bestErr = Infinity;
            for (let d = 1; d <= 1000; d++) {
                const n = Math.round(target * d);
                const err = Math.abs(target - n / d);
                if (err < bestErr) { bestErr = err; bestN = n; bestD = d; }
            }
            return `${bestN}/${bestD}`;
        };
        return rows.map(function(row) {
            if (!row.fraction) return row;
            try {
                const parts = row.fraction.split('/');
                const raw = parts.length === 2
                    ? (Number(parts[0]) / Number(parts[1]) + 1).toFixed(4)
                    : Number(row.fraction).toFixed(4);
                const marketId = String(row.marketId || '40');
                const adjustment = lib.pvOdds.getAdjustmentValue(
                    raw, String(ki || '1'), String(l3 || ''), marketId, 'PV_CHARTS'
                );
                if (adjustment !== false && adjustment !== null && adjustment !== undefined) {
                    const adjustedRaw = Number(raw) - Number(adjustment || 0);
                    const decimals = Number(adjustedRaw) < 1.1 ? 3 : 2;
                    const factor = Math.pow(10, decimals);
                    const dec = Math.trunc((adjustedRaw + Number.EPSILON * adjustedRaw) * factor) / factor;
                    const adjustedFraction = toFraction(dec);
                    row.adjusted_fraction = adjustedFraction;
                    row.adjusted_decimal = dec;
                    row.adjustment = Number(adjustment || 0);
                }
            } catch(e) {}
            return row;
        });
    }
    """
    js_rows = []
    marche_to_ma = {
        "Résultat du match": "40", "Full Time Result": "40",
        "Se qualifie": "1094", "To Qualify": "1094",
        "Total de buts": "981", "Total Goals": "981",
        "Les deux équipes marquent": "10150", "Both Teams to Score": "10150",
        "Double chance": "10114", "Double Chance": "10114",
        "Résultat / Les deux équipes marquent": "50404",
    }
    for row in resultats:
        ma = marche_to_ma.get(row.get('Marche', ''), '40')
        js_rows.append({
            'fraction': row.get('Cote_Fraction', ''),
            'marketId': row.get('Marche_ID') or ma,
        })

    try:
        js_result = page.evaluate(JS_APPLY_PV, [js_rows, ki, l3])
        if js_result and len(js_result) == len(resultats):
            for row, jr in zip(resultats, js_result):
                if jr.get('adjusted_decimal'):
                    row['Cote_Fraction_PV'] = jr['adjusted_fraction']
                    row['Cote_Decimale_PV'] = jr['adjusted_decimal']
                    row['Cote_Fraction'] = jr['adjusted_fraction']
                    row['Cote_Decimale'] = jr['adjusted_decimal']
                    row['Cote_PV_Applique'] = True
    except Exception as e:
        print(f"      ⚠️ JS PV error: {e}")

    return resultats


def pd_vers_url(pd):
    """Convertit un identifiant PD Bet365 en URL canonique sans doubles slash."""
    pd = str(pd or '').strip()
    if '#IP#' in pd or pd.startswith('IP#'):
        code = pd.strip('#/').replace('IP#', '', 1).strip('#/')
        return "https://www.bet365.fr/#/IP/" + code + "/"
    segments = [s.strip('/') for s in pd.strip('#/').split('#') if s.strip('/')]
    return "https://www.bet365.fr/#/" + "/".join(segments) + "/"


def est_inplay(pd):
    return '#IP#' in pd or pd.startswith('IP#')


ALL_DATA = []


def enregistrer_reponse_brute(sport, tournoi, url, endpoint, raw):
    """Conserve chaque réponse API telle que reçue, sans parsing ni modification."""
    if not raw:
        return
    ALL_DATA.append({
        'Sport': sport or '',
        'Championnat': tournoi or '',
        'URL': url or '',
        'Endpoint': endpoint or '',
        'Data': raw,
    })


def nom_fichier_sport(nom):
    return ''.join(c if c.isalnum() else '_' for c in (nom or 'Sport')).strip('_') or 'Sport'


def nettoyer_resultats_export(resultats):
    """Exclut les marchés MMA agrégés qui ne sont pas rattachables à un combat."""
    nettoyes = []
    exclus = 0
    for row in resultats:
        marche = str(row.get('Marche', '') or '').strip()
        if str(row.get('Sport', '')).strip().lower() == 'mma' and marche.startswith('Tout -'):
            exclus += 1
            continue
        nettoyes.append(row)
    return nettoyes


def cote_finale_export(row):
    """Retourne prioritairement la cote effectivement associée à l’écran."""
    for key in ('Cote_Affichee', 'Cote_Decimale_Ecran', 'Cote_Decimale'):
        value = row.get(key)
        if value is not None and value != '':
            try:
                return float(value)
            except (TypeError, ValueError):
                pass
    return row.get('Cote_Decimale_Brute')


def normaliser_marche_export(row):
    marche = str(row.get('Marche', '') or '').strip()
    sport = str(row.get('Sport', '') or '').lower()
    participant = str(row.get('Participant', '') or '').strip()
    if 'baseball' not in sport:
        return marche

    if marche == 'Game Lines' and re.match(r'^[OU]\s*\d', participant, re.IGNORECASE):
        return 'Match - Total'
    if marche == 'Game Lines - Handicap':
        return 'Match - Handicap'
    if marche == 'Game Lines - Money Line':
        return 'Match - Vainqueur'
    if marche == 'Game Lines - Total':
        return 'Match - Total'
    if marche in {'1st Inning Runs - Vainqueur', '1e manche - Points - Vainqueur'}:
        return '1re manche - Total'
    if marche == 'A Run in the 1st Inning':
        return 'Course en 1re manche'
    if marche == 'Un point dans la 1re manche':
        return 'Au moins un point en 1re manche'

    marche = marche.replace('Team Alternative Totals - ', 'Total équipe alternatif - ')
    prefixe_equipe = 'Équipe - Total - Autres options - '
    if marche.startswith(prefixe_equipe):
        marche = 'Total équipe alternatif - ' + marche[len(prefixe_equipe):]

    if marche == 'Handicap sur les points - Autres options - Handicap':
        return 'Handicap alternatif - Points'
    if marche == 'Match - Cotes - Handicap':
        return 'Match - Handicap'
    if marche == 'Match - Cotes - Total':
        return 'Match - Total'
    if marche == 'Match - Cotes - Vainqueur':
        return 'Match - Vainqueur'
    if marche == 'Run Line - Handicap':
        return 'Run Line alternatif - Handicap'
    return marche


def normaliser_all_sport(resultats):
    return [{
        'Sport': r.get('Sport', ''),
        'Championnat': r.get('Tournoi', ''),
        'Équipe': r.get('Participant', ''),
        'Ligne': r.get('Ligne', ''),
        'Marché': normaliser_marche_export(r),
        'Cote': cote_finale_export(r),
    } for r in resultats]


def structurer_all_sport(resultats):
    structure = {}
    for r in resultats:
        sport = r.get('Sport', '') or 'Sport inconnu'
        championnat = r.get('Tournoi', '') or 'Championnat inconnu'
        marche = r.get('Marche', '') or 'Marché inconnu'
        participant = r.get('Participant', '') or 'Participant inconnu'
        cote = cote_finale_export(r)
        structure.setdefault(sport, {}).setdefault(championnat, {}).setdefault(marche, {})[participant] = cote
    return structure


def sauvegarder_sorties(resultats):
    par_sport = {}
    for row in resultats:
        par_sport.setdefault(row.get('Sport', 'Sport'), []).append(row)
    for sport, rows in par_sport.items():
        with open(f'{nom_fichier_sport(sport)}.json', 'w', encoding='utf-8') as f:
            json.dump(normaliser_all_sport(rows), f, ensure_ascii=False, indent=2)
    with open('all_data.json', 'w', encoding='utf-8') as f:
        json.dump(ALL_DATA, f, ensure_ascii=False, indent=2)
    with open('all_sport.json', 'w', encoding='utf-8') as f:
        json.dump(structurer_all_sport(resultats), f, ensure_ascii=False, indent=2)


def filtrer_coupon_pour_url(raw, url):
    if not raw or not url:
        return raw
    match_e = re.search(r'(?:^|[/#])E(\d+)(?:[/#]|$)', str(url))
    if not match_e:
        return raw
    token = '#E' + match_e.group(1) + '#'
    sections = re.split(r'(?=\|F\|)', raw)
    sections_filtrees = []
    for section in sections:
        if token not in section:
            continue
        blocs_ev = re.split(r'(?=\|EV;)', section)
        blocs_cibles = [bloc for bloc in blocs_ev if token in bloc]
        sections_filtrees.extend(blocs_cibles or [section])
    if sections_filtrees:
        return '|'.join(s.strip('|') for s in sections_filtrees)
    return raw


def sauvegarder_resultats_incremental(tous_resultats, nouvelles_lignes):
    if not nouvelles_lignes:
        return
    tous_resultats.extend(nouvelles_lignes)
    sports = sorted(set(r.get('Sport', 'Sport') or 'Sport' for r in nouvelles_lignes))
    for sport in sports:
        lignes_sport = [r for r in tous_resultats if (r.get('Sport', 'Sport') or 'Sport') == sport]
        uniques = [dict(t) for t in {tuple(d.items()) for d in lignes_sport}]
        uniques = nettoyer_resultats_export(uniques)
        try:
            with open(f'{nom_fichier_sport(sport)}.json', 'w', encoding='utf-8') as f:
                json.dump(normaliser_all_sport(uniques), f, ensure_ascii=False, indent=2)
        except Exception as e:
            log_trace(f'ERREUR_SAUVEGARDE_INCREMENTALE sport={sport} erreur={e}')


def sauvegarder_coupon_brut(raw, match_nom='', prefix='DEBUG_BET365'):
    if not ENABLE_DEBUG or not raw:
        return None
    nom_propre = ''.join(c if c.isalnum() else '_' for c in (match_nom or 'match'))
    timestamp = int(time.time() * 1000)
    nom_fichier = f'{prefix}_coupon_{nom_propre}_{timestamp}.txt'
    try:
        with open(nom_fichier, 'w', encoding='utf-8') as f:
            f.write(raw)
        return nom_fichier
    except Exception as e:
        return None


def parser_soccertab(raw):
    pattern = re.compile(r'D1002.*G40|G40.*D1002')
    blocs = parse_bet365(raw)
    trouves = []
    vus = set()
    for b in blocs:
        nom = b.get('NA', '').strip()
        pd = b.get('PD', '').strip()
        if not pd or not nom:
            continue
        if pattern.search(pd) and nom in CHAMPIONNATS_VOULUS:
            url = pd_vers_url(pd)
            if url not in vus:
                vus.add(url)
                trouves.append({'nom': nom, 'url': url})
    return trouves


def extraire_metadonnees_pv(parsed):
    classification_id = ""
    league_code = ""
    fixture_started = ""
    fixture_id = ""
    for b in parsed:
        t = b.get('_type')
        if t == 'CL' and b.get('CL'):
            classification_id = b.get('CL', '').strip()
        if t in ('CL', 'EV'):
            if not league_code and b.get('L3'):
                league_code = b.get('L3', '').strip()
            if not fixture_started and b.get('FS'):
                fixture_started = b.get('FS', '').strip()
        if t == 'EV':
            fixture_id = b.get('FI', '').strip() or fixture_id
            if b.get('FS'):
                fixture_started = b.get('FS', '').strip()
    return {
        'classification_id': classification_id,
        'league_code': league_code,
        'fixture_started': fixture_started or '0',
        'fixture_id': fixture_id,
    }


def parser_markets(raw):
    parsed  = parse_bet365(raw)
    joueurs = {}
    cotes   = {}
    matchs  = {}
    pv_meta = extraire_metadonnees_pv(parsed)
    league_code = pv_meta['league_code']
    classification_id = pv_meta['classification_id']

    for b in parsed:
        t = b.get('_type')
        if t == 'PA':
            id_brut = b.get('ID', '')
            fi      = b.get('FI', '')
            od      = b.get('OD', '')
            pd      = b.get('PD', '').strip()
            fd      = b.get('FD', '').strip()
            bc      = b.get('BC', '').strip()
            ki      = classification_id
            l3      = b.get('L3', league_code).strip() or league_code

            if id_brut.startswith('PC') and fi:
                id_num = id_brut[2:]
                joueurs[id_num] = {'nom': b.get('NA', '').strip()}
                if fi not in matchs:
                    matchs[fi] = {
                        'fi'        : fi, 'nom': fd, 'pd': pd,
                        'url'       : pd_vers_url(pd) if pd else '',
                        'heure'     : bc, 'ids': [],
                        'ki'        : ki,
                        'l3'        : l3,
                        'fixture_started': pv_meta.get('fixture_started', '0'),
                    }
                elif ki and not matchs[fi].get('ki'):
                    matchs[fi]['ki'] = ki
                matchs[fi]['ids'].append(id_num)
            elif od and fi:
                if fi not in cotes:
                    cotes[fi] = {}
                cotes[fi][id_brut] = od

    resultats = []
    for fi, match in matchs.items():
        c = cotes.get(fi, {})
        match['joueurs'] = [
            {
                'nom'           : joueurs.get(i, {}).get('nom', 'Inconnu'),
                'Cote_Fraction' : c.get(i, ''),
                'Cote_Decimale' : fraction_to_decimal(c.get(i, '')) if c.get(i) else None,
            }
            for i in match['ids']
        ]
        resultats.append(match)
    return resultats


def appliquer_combi_booste(resultats, nom_sport):
    if str(nom_sport).lower() != 'tennis':
        return resultats
    candidates = [
        r for r in resultats
        if r.get('Combi_Booste')
        and str(r.get('Marche_ID', '')) == '83'
        and r.get('Marche', '').strip() in ('To Win Match', 'Vainqueur - To Win Match')
    ]
    if len(candidates) != 2:
        return resultats
    vals = sorted(round(float(r.get('Cote_Decimale_Brute') or 0), 2) for r in candidates)
    if vals != [1.80, 2.00]:
        return resultats
    for r in candidates:
        r['Cote_Fraction_PV'] = '9/10'
        r['Cote_Decimale_PV'] = 1.90
        r['Cote_Fraction'] = '9/10'
        r['Cote_Decimale'] = 1.90
        r['Cote_Affichee'] = 1.90
        r['Combi_Booste_Applique'] = True
        r['Source_Cote'] = 'combi_booste_tennis'
    return resultats


def parser_basket_grilles(blocs, nom_sport, tournoi):
    lignes = []
    joueurs_ordre = []
    mg = ''
    ma = ''
    colonne = None
    pa_colonne = []

    def flush_colonne():
        if colonne is None:
            return
        for idx, b in enumerate(pa_colonne):
            if idx >= len(joueurs_ordre) or not b.get('OD', '').strip():
                continue
            lignes.append({
                'Sport': nom_sport, 'Tournoi': tournoi,
                'Marche': f"{mg or 'Joueurs'} - {ma or 'Joueur'}",
                'Marche_ID': b.get('MA', ''),
                'Participant': joueurs_ordre[idx], 'Ligne': colonne,
                'Cote_Fraction_Brute': b.get('OD', ''),
                'Cote_Decimale_Brute': fraction_to_decimal(b.get('OD', '')),
                'Cote_Fraction': b.get('OD', ''),
                'Cote_Decimale': fraction_to_decimal(b.get('OD', '')),
                'Cote_Decimale_Ecran': None, 'Cote_Affichee': None,
                'Source_Cote': 'api_brute_grille_basket',
                'Cote_PV_Applique': False, 'Combi_Booste': False,
            })

    for b in blocs:
        t = b.get('_type')
        if t == 'MG':
            flush_colonne()
            mg = b.get('NA', '').strip()
            ma = ''
            colonne = None
            pa_colonne = []
            joueurs_ordre = []
        elif t == 'MA':
            na = b.get('NA', '').strip()
            if na:
                ma = na
        elif t == 'CO':
            flush_colonne()
            colonne = b.get('NA', '').strip()
            pa_colonne = []
        elif t == 'PA':
            ident = b.get('ID', '').strip()
            na = b.get('NA', '').strip()
            if ident.startswith('PC') and na and colonne is None:
                joueurs_ordre.append(na)
            elif colonne is not None and b.get('OD', '').strip():
                pa_colonne.append(b)
    flush_colonne()
    return lignes


def parser_page_universel(raw, nom_sport, nom_event_fallback="Compétition"):
    blocs = parse_bet365(raw)
    resultats = []
    tournoi = nom_event_fallback
    current_mg = "Vainqueur"
    current_mg_id = ""
    current_ma = ""
    current_ma_id = ""
    current_team = ""
    current_team_id = ""
    current_combi_boost = False
    dict_participants = {}
    row_headers = []
    header_market_names = {}
    row_index = 0
    event_teams = []

    ignore_ma = {"Oui", "Non", "Gagnant/Placé 1/5 1-2-3", "Gagnant/Placé 1/4 1-2-3", 
                 "Paris principaux", "Pari personnalisé", "Course", "Principaux", "Qualifications", "All", "Matches"}

    for b in blocs:
        t = b.get('_type')
        if t == 'EV':
            tb = b.get('TB', '')
            if '¬' in tb:
                parties = tb.split('¬')
                tournoi = parties[2].split(',')[0].strip() if len(parties) >= 3 else parties[1].split(',')[0].strip()
            event_teams = [x for x in (b.get('N2', '').strip(), b.get('N3', '').strip()) if x]
        
        elif t == 'MG':
            if b.get('SY', '').strip() == 'fe' and b.get('FI', '').strip() and b.get('NA', '').strip():
                tournoi = b.get('NA', '').strip()
                current_mg = 'Vainqueur'
                current_mg_id = ''
                current_ma = ''
                current_ma_id = ''
                current_team = ''
                current_team_id = ''
                current_combi_boost = False
                row_headers = []
                row_index = 0

            na = b.get('NA', '').strip()
            if na and na not in ignore_ma:
                current_mg = na
                current_mg_id = b.get('ID', '').lstrip('M')
                current_combi_boost = b.get('BW', '').strip() == '1'
                current_ma = ""
                current_ma_id = ""
                current_team = ""
                current_team_id = ""
                row_headers = []
        
        elif t == 'MA':
            na = b.get('NA', '').strip()
            sy = b.get('SY', '').strip()
            if not na or na == " ":
                row_headers = []
            elif sy in ('db', 'dt', 'do') and b.get('FI', '').strip():
                if na in {'Vainqueur', 'Money Line'}:
                    current_ma = na
                    current_ma_id = b.get('ID', '').lstrip('M')
                    current_team = ''
                    current_team_id = ''
                else:
                    current_team = na
                    current_team_id = b.get('ID', '').lstrip('M')
            elif na and na not in ignore_ma and "Gagnant/Placé" not in na:
                current_ma = na
                current_ma_id = b.get('ID', '').lstrip('M')
            row_index = 0
        
        elif t == 'PA':
            id_raw = b.get('ID', '')
            od     = b.get('OD', '')
            na     = b.get('NA', '').strip()
            clean_id = ''.join(filter(str.isdigit, id_raw))
            
            if na and not od:
                if na in {'Handicap', 'Total', 'Vainqueur', 'Money Line', 'Run Line'}:
                    current_ma = na
                    current_ma_id = clean_id
                    header_market_names[clean_id] = na
                    row_headers = []
                else:
                    if clean_id:
                        dict_participants[clean_id] = na
                    row_headers.append(na)
                
            elif od:
                hd_clean = b.get('HD', '').strip()
                participant = hd_clean or na

                if (not hd_clean and current_ma.strip().lower() in {'vainqueur', 'money line'}
                        and row_index < len(event_teams)):
                    participant = event_teams[row_index]

                if not participant and current_team:
                    participant = current_team

                if not participant:
                    participant = dict_participants.get(clean_id, "")
                
                if not participant and row_index < len(row_headers):
                    participant = row_headers[row_index]
                    
                if not participant:
                    participant = "Inconnu"
                    
                participant = participant.replace(" - Oui", "").strip()

                marche_final = current_mg
                market_id_from_pa = b.get('MA', '').lstrip('M')
                market_from_pa = header_market_names.get(market_id_from_pa)
                if re.match(r'^[+-]?(?:\d+(?:\.\d+)?|\d+\.\d+)$', hd_clean):
                    market_from_pa = 'Handicap'
                elif re.match(r'^[PM]\s*\d', hd_clean, re.IGNORECASE):
                    market_from_pa = 'Total'
                elif not hd_clean and current_team:
                    market_from_pa = 'Vainqueur'
                if market_from_pa:
                    marche_final = f"{current_mg} - {market_from_pa}"
                elif current_ma and current_ma != current_mg and current_ma.strip():
                    marche_final = f"{current_mg} - {current_ma}"

                cote_brute = fraction_to_decimal(od)
                resultats.append({
                    "Sport"                  : nom_sport,
                    "Tournoi"                : tournoi,
                    "Marche"                 : marche_final,
                    "Marche_ID"              : current_ma_id or current_mg_id,
                    "Participant"            : participant,
                    "Cote_Fraction_Brute"   : od,
                    "Cote_Decimale_Brute"   : cote_brute,
                    "Cote_Fraction"          : od,
                    "Cote_Decimale"           : cote_brute,
                    "Cote_Decimale_Ecran"   : None,
                    "Cote_Affichee"         : None,
                    "Source_Cote"           : "api_brute",
                    "Cote_PV_Applique"      : False,
                    "Combi_Booste"          : current_combi_boost,
                })
                row_index += 1

    sports_pv_valides = {'Football', 'Tennis'}
    for row in resultats:
        if not row.get('Cote_PV_Applique') and (nom_sport in sports_pv_valides or row.get('Combi_Booste')):
            appliquer_pv_fallback(row)

    est_basket = 'basket' in str(nom_sport).lower() or any(
        b.get('L3', '').upper() in {'WNBA', 'NBA'} for b in blocs
    )
    if est_basket:
        resultats = [r for r in resultats if not (
            not r.get('Ligne') and r.get('Marche', '').split(' - ')[0] in {
                'Points', 'Rebonds', 'Passes décisives', 'Paniers à 3 points', 'Combinaisons'
            }
        )]
        resultats.extend(parser_basket_grilles(blocs, nom_sport, tournoi))

    appliquer_combi_booste(resultats, nom_sport)
    return resultats


def parser_splash(raw):
    parsed = parse_bet365(raw)
    fixtures = []
    vus = set()
    competition = 'Compétition'

    for b in parsed:
        if b.get('_type') == 'EV':
            tb = b.get('TB', '')
            parties = [p.strip() for p in tb.split('¬') if p.strip()]
            if len(parties) >= 2:
                competition = parties[1].split(',')[0].strip() or competition
            elif parties:
                competition = parties[0].split(',')[0].strip() or competition
            break

    for b in parsed:
        if b.get('_type') != 'PA':
            continue
        pd = b.get('PD', '').strip()
        if not pd or '#P' in pd or 'E729' in pd:
            continue
        url = pd_vers_url(pd)
        if not re.search(r'(?:^|/)E\d+(?:/|$)', url):
            continue
        if not re.search(r'(?:^|/)F(?:8|19)(?:/|$)', url):
            continue
        if url in vus:
            continue
        vus.add(url)
        nom = b.get('FD', '').strip() or b.get('NA', '').strip() or url
        fixtures.append({
            'nom': nom,
            'url': url,
            'inplay': est_inplay(pd),
        })

    if fixtures:
        return [{'nom': competition, 'marches': fixtures}]

    groupes_d50 = []
    for b in parsed:
        pd = b.get('PD', '').strip()
        if not pd or '#P' in pd:
            continue
        url = pd_vers_url(pd)
        if re.search(r'(?:^|/)E\d+(?:/|$)', url) and re.search(r'(?:^|/)F50(?:/|$)', url):
            if url not in {m.get('url') for m in groupes_d50}:
                groupes_d50.append({'nom': b.get('NA', '').strip() or b.get('FD', '').strip() or competition,
                                    'url': url, 'inplay': est_inplay(pd)})
    if groupes_d50:
        return [{'nom': competition, 'marches': groupes_d50}]

    tournois = []
    tournoi_courant = None
    for b in parsed:
        t = b.get('_type')
        if t in ('MG', 'MA'):
            nom = b.get('NA', '').strip()
            if nom:
                tournoi_courant = {'nom': nom, 'marches': []}
                tournois.append(tournoi_courant)
                pd = b.get('PD', '').strip()
                if pd and ('#AC#' in pd or '#IP#' in pd):
                    tournoi_courant['marches'].append({
                        'nom': nom, 'url': pd_vers_url(pd), 'inplay': est_inplay(pd)
                    })
        elif t == 'PA' and tournoi_courant:
            pd = b.get('PD', '').strip()
            nom = b.get('NA', '').strip()
            if pd and nom and '#P' not in pd and 'E729' not in pd:
                if '#AC#' in pd or '#IP#' in pd:
                    tournoi_courant['marches'].append({
                        'nom': nom, 'url': pd_vers_url(pd), 'inplay': est_inplay(pd)
                    })
    return [t for t in tournois if t['marches']]


def installer_filtre_ressources(page):
    if not BLOCK_HEAVY_RESOURCES:
        return
    def handler(route):
        try:
            if route.request.resource_type in {'image', 'font', 'media'}:
                route.abort()
            else:
                route.continue_()
        except Exception:
            try:
                route.continue_()
            except Exception:
                pass
    try:
        page.route('**/*', handler)
    except Exception:
        pass


def intercepter_onglet(context, url, api, nom_sport="Inconnu", timeout_s=TIMEOUT_S):
    t = time.time()
    page = context.new_page()
    installer_filtre_ressources(page)
    raw = [None]
    raw_secours = []
    ok = [False]
    nb_reponses = [0]
    event_token = None
    event_id = None
    match_event = re.search(r'(?:^|[/#])E(\d+)(?:[/#]|$)', str(url))
    if match_event:
        event_id = match_event.group(1)
        event_token = '#E' + event_id + '#'

    def contient_evenement(txt):
        if not event_id:
            return True
        return any(token in txt for token in (
            '#E' + event_id + '#',
            '%23E' + event_id + '%23',
            'E' + event_id,
        ))

    def endpoint_compatible(url_reponse, api_attendu):
        if api_attendu == 'contentapi':
            return any(x in url_reponse for x in (
                'matchbettingcontentapi/coupon',
                'matchmarketscontentapi/coupon',
                'matchmarketscontentapi/markets',
                'othersportsmatchbettingcontentapi/coupon',
                'othersportsmatchmarketscontentapi/coupon',
            ))
        return api_attendu in url_reponse

    def handler(response):
        if response.request.resource_type not in ("fetch", "xhr"):
            return
        try:
            txt = response.text()
            if not txt or '|' not in txt:
                return
            if endpoint_compatible(response.url, api):
                if event_id and not contient_evenement(txt):
                    return
                raw[0] = txt
                ok[0] = True
                nb_reponses[0] += 1
                print(f"    [CDP Stream] Réponse #{nb_reponses[0]} ({round(len(txt) / 1024, 1)} Ko) [{time.time() - t:.1f}s]")
            elif not event_token and len(raw_secours) < 20:
                raw_secours.append(txt)
        except Exception:
            pass

    page.on("response", handler)
    try:
        page.goto(url, wait_until="commit")
    except Exception:
        pass
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if FAST_MODE and ok[0] and raw[0] and 'PA;' in raw[0] and 'OD=' in raw[0]:
            break
        try:
            page.wait_for_timeout(POLL_MS)
        except Exception:
            break
    if not ok[0] and raw_secours and not event_token:
        avec_cotes = [x for x in raw_secours if 'PA;' in x and 'OD=' in x]
        raw[0] = max(avec_cotes or raw_secours, key=len)
        ok[0] = True
    try:
        page.close()
    except Exception:
        pass
    return raw[0]


def _worker_recuperer_match(task):
    m, nom_sport, api_coupon = task
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(f'http://127.0.0.1:{CDP_PORT}')
            if not browser.contexts:
                return m, None, 'aucun_contexte'
            context = browser.contexts[0]
            raw = intercepter_onglet(context, m.get('url', ''), api_coupon,
                                     nom_sport, timeout_s=12)
            return m, raw, None
    except Exception as e:
        return m, None, str(e)


def appliquer_pv_sur_url(context, url, resultats, meta):
    """PV disabled per user requirements - returns pure on-screen odds directly."""
    return resultats


def scraper_match_unique(context, url, tous_resultats):
    """Scrape un seul match à partir de son URL Bet365 complète."""
    print("\n" + "=" * 65)
    print("  🎯 MODE MATCH UNIQUE")
    print(f"  URL : {url}")
    print("=" * 65)

    api_coupon_unique = 'contentapi'
    raw = intercepter_onglet(context, url, api_coupon_unique, "Match unique", timeout_s=8)
    if not raw:
        print("  ❌ Aucun coupon reçu pour cette URL")
        return 0

    sport_match = 'Baseball' if re.search(r'[/#]B16[/#]', str(url)) else 'Match unique'
    blocs_match = parse_bet365(raw)
    tournoi_match = next((b.get('NA', '').strip() for b in blocs_match
                          if b.get('_type') == 'EV' and b.get('NA', '').strip()), 'Match unique')
    enregistrer_reponse_brute(sport_match, tournoi_match, url, api_coupon_unique, raw)
    sauvegarder_coupon_brut(raw, 'Match_unique')
    resultats = parser_page_universel(raw, sport_match, tournoi_match)
    meta = extraire_metadonnees_pv(parse_bet365(raw))
    resultats = appliquer_pv_sur_url(context, url, resultats, meta)
    sauvegarder_resultats_incremental(tous_resultats, resultats)
    print(f"  📊 {len(resultats)} résultats / {len(set(x.get('Marche') for x in resultats))} marchés")
    return 1


def main():
    url_unique = sys.argv[1] if len(sys.argv) > 1 else None
    if not url_unique:
        print("Usage: python bet365_parser.py <URL>")
        return

    sys.path.append(os.path.abspath("../bet365"))
    from bet365_internal import ensure_chrome_cdp
    ensure_chrome_cdp(CDP_PORT)
    tous_resultats = []
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        scraper_match_unique(context, url_unique, tous_resultats)


if __name__ == "__main__":
    main()
