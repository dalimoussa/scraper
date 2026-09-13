/**
 * Bet365 Sports Odds Data Normalizer
 * Conforms strictly to BET365 SPORTS ODDS DISPLAY SPECIFICATION
 * 
 * Normalizes all markets and selections into:
 * FORMAT A — SIMPLE ODDS: { format: 'A', selection: '...', odds: '...' }
 * FORMAT B — LINE + ODDS: { format: 'B', selection: '...', line: '...', odds: '...' }
 */

const OUTRIGHT_SPORTS = new Set([
  'Cycling',
  'Golf',
  'F1',
  'Formula 1'
]);

/**
 * Checks whether an event is an outright competition or head-to-head match.
 */
function isOutrightEvent(sport, event) {
  if (OUTRIGHT_SPORTS.has(sport)) return true;
  // Outright indicator in competition or missing away participant
  const comp = (event.competition || '').toLowerCase();
  const away = (event.away || '').trim();
  const home = (event.home || '').toLowerCase();

  if (comp.includes('outright') || comp.includes('top finishes') || comp.includes('championship winner')) {
    return true;
  }
  if (!away && (home.includes('to win') || home.includes('winner') || home.includes('outright'))) {
    return true;
  }
  return false;
}

/**
 * Normalizes an entire event and all its markets.
 */
function normalizeEvent(event, sport) {
  const isOutright = isOutrightEvent(sport, event);
  const home = (event.home || '').trim();
  const away = (event.away || '').trim();
  const competition = (event.competition || '').trim();
  const date = event.date || '';
  const kickoff = event.kickoff || event.time || date;

  // Extract markets (support nested 'Game Lines' and direct market objects)
  const rawMarkets = event.markets || event.odds || {};
  const normalizedMarkets = {};

  for (const [key, value] of Object.entries(rawMarkets)) {
    if (key === 'Game Lines' && typeof value === 'object' && value !== null) {
      // Unpack nested Game Lines markets
      for (const [subKey, subVal] of Object.entries(value)) {
        normalizedMarkets[subKey] = normalizeMarket(subKey, subVal, sport, home, away);
      }
    } else {
      normalizedMarkets[key] = normalizeMarket(key, value, sport, home, away);
    }
  }

  // Clean event title for outrights: never display "Home vs Away" or empty "vs"
  let displayTitle = '';
  if (isOutright) {
    displayTitle = competition || home.replace(/ - To Win$/, '') || 'Outright Competition';
  } else {
    displayTitle = `${home || 'Team 1'} vs ${away || 'Team 2'}`;
  }

  return {
    id: event.id || Math.random().toString(36).substr(2, 9),
    sport,
    isOutright,
    competition,
    date,
    kickoff,
    home: isOutright ? '' : home,
    away: isOutright ? '' : away,
    displayTitle,
    markets: normalizedMarkets,
    raw: event
  };
}

/**
 * Normalizes a single market's data into Format A or Format B items.
 */
function normalizeMarket(marketName, marketData, sport, home, away) {
  if (!marketData || typeof marketData !== 'object') {
    return [];
  }

  const items = [];
  const mName = marketName.toLowerCase().trim();

  // Helper for resolving team names from '1', '2', 'X'
  const resolveSelectionName = (key) => {
    if (key === '1') return home || 'Team 1';
    if (key === '2') return away || 'Team 2';
    if (key === 'X' || key === 'x') return 'Draw';
    if (key.toLowerCase() === 'over') return 'Over';
    if (key.toLowerCase() === 'under') return 'Under';
    return key;
  };

  for (const [rawKey, rawVal] of Object.entries(marketData)) {
    // Case 1: Value is an object with { line, odds }
    if (typeof rawVal === 'object' && rawVal !== null && rawVal.odds !== undefined) {
      const lineStr = (rawVal.line !== undefined && rawVal.line !== null) ? String(rawVal.line) : '';
      const oddsStr = String(rawVal.odds);

      let sel = rawKey;
      if (rawKey === '1') sel = home || 'Team 1';
      else if (rawKey === '2') sel = away || 'Team 2';
      else if (rawKey.toLowerCase() === 'over') sel = 'Over';
      else if (rawKey.toLowerCase() === 'under') sel = 'Under';

      items.push({
        format: 'B',
        rawKey,
        selection: sel,
        line: lineStr,
        odds: oddsStr
      });
      continue;
    }

    // Case 2: Value is a direct string or number (odds)
    const oddsStr = String(rawVal);

    // Check if the key itself contains line info (e.g. "+1.5", "-1.5", "O 221.5", "U 221.5")
    const totalMatch = rawKey.match(/^([OU])\s*([0-9.]+)/i);
    const handicapMatch = rawKey.match(/^([+-][0-9.]+)$/);

    if (totalMatch) {
      const isOver = totalMatch[1].toUpperCase() === 'O';
      items.push({
        format: 'B',
        rawKey,
        selection: isOver ? 'Over' : 'Under',
        line: totalMatch[2],
        odds: oddsStr
      });
    } else if (handicapMatch) {
      // Flat handicap key like "+1.5" -> line: "+1.5"
      const isHome = handicapMatch[1].startsWith('+');
      items.push({
        format: 'B',
        rawKey,
        selection: isHome ? (home || 'Team 1') : (away || 'Team 2'),
        line: handicapMatch[1],
        odds: oddsStr
      });
    } else {
      // Format A: Simple Odds
      let sel = rawKey;

      // For Soccer Match Result, preserve standard 1 / X / 2 labeling
      if (mName === 'match result') {
        sel = rawKey; // '1', 'X', '2'
      } else if (mName === 'match winner' && (sport.includes('Tennis') || sport === 'Tennis')) {
        // Tennis specification: display 1 [odds] | 2 [odds]
        sel = rawKey; // '1', '2'
      } else if (mName === 'money line' || mName === 'to win') {
        if (rawKey === '1') sel = home || 'Team 1';
        else if (rawKey === '2') sel = away || 'Team 2';
      }

      items.push({
        format: 'A',
        rawKey,
        selection: sel,
        odds: oddsStr
      });
    }
  }

  // Canonical Ordering per Bet365 Specification
  if (mName === 'match result') {
    const order1X2 = { '1': 1, 'x': 2, 'X': 2, '2': 3 };
    items.sort((a, b) => (order1X2[a.rawKey] || 99) - (order1X2[b.rawKey] || 99));
  } else if (mName === 'both teams to score') {
    const orderBTTS = { 'yes': 1, 'no': 2 };
    items.sort((a, b) => (orderBTTS[a.rawKey.toLowerCase()] || 99) - (orderBTTS[b.rawKey.toLowerCase()] || 99));
  } else if (mName === 'half time/full time') {
    const orderHTFT = {
      '1/1': 1, '1/x': 2, '1/X': 2, '1/2': 3,
      'x/1': 4, 'X/1': 4, 'x/x': 5, 'X/X': 5, 'x/2': 6, 'X/2': 6,
      '2/1': 7, '2/x': 8, '2/X': 8, '2/2': 9
    };
    items.sort((a, b) => (orderHTFT[a.rawKey] || 99) - (orderHTFT[b.rawKey] || 99));
  } else if (mName === 'total') {
    const orderTotal = { 'over': 1, 'under': 2 };
    items.sort((a, b) => (orderTotal[a.selection.toLowerCase()] || 99) - (orderTotal[b.selection.toLowerCase()] || 99));
  } else if (mName.includes('win') && OUTRIGHT_SPORTS.has(sport)) {
    // Sort outright contenders by odds ascending (favorites first)
    items.sort((a, b) => (parseFloat(a.odds) || 9999) - (parseFloat(b.odds) || 9999));
  }

  return items;
}

// Export for Node environment (testing) and browser window
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    isOutrightEvent,
    normalizeEvent,
    normalizeMarket
  };
} else if (typeof window !== 'undefined') {
  window.Bet365Normalizer = {
    isOutrightEvent,
    normalizeEvent,
    normalizeMarket
  };
}
