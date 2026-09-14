/**
 * BET365 SPORTS ODDS DISPLAY — APPLICATION CONTROLLER
 * Strictly conforms to BET365 SPORTS ODDS DISPLAY SPECIFICATION
 */

(function () {
  'use strict';

  // Sport Metadata & Display Icons
  const SPORT_CONFIG = {
    'Soccer': { icon: '⚽', label: 'Soccer' },
    'EPL': { icon: '🏆', label: 'Premier League' },
    'Tennis': { icon: '🎾', label: 'Tennis' },
    'US Open': { icon: '🎾', label: 'US Open' },
    'US Open Women': { icon: '🎾', label: 'US Open Women' },
    'Basketball': { icon: '🏀', label: 'Basketball' },
    'American Football': { icon: '🏈', label: 'American Football' },
    'MLB': { icon: '⚾', label: 'MLB' },
    'Handball': { icon: '🤾', label: 'Handball' },
    'Ice Hockey': { icon: '🏒', label: 'Ice Hockey' },
    'Rugby League': { icon: '🏉', label: 'Rugby League' },
    'Rugby Union': { icon: '🏉', label: 'Rugby Union' },
    'Cricket': { icon: '🏏', label: 'Cricket' },
    'Volleyball': { icon: '🏐', label: 'Volleyball' },
    'Esports': { icon: '🎮', label: 'Esports' },
    'Cycling': { icon: '🚴', label: 'Cycling' },
    'Golf': { icon: '⛳', label: 'Golf' },
    'F1': { icon: '🏎️', label: 'Formula 1' },
    'Formula 1': { icon: '🏎️', label: 'Formula 1' }
  };

  // State
  const state = {
    rawSports: [],
    normalizedEvents: [],
    activeSport: 'ALL',
    activeCompetition: 'ALL',
    searchQuery: '',
    betSlip: new Map(), // key: eventId::marketName::selection -> Bet Object
    stake: 10.00
  };

  // DOM Elements
  const el = {
    sportsNav: document.getElementById('sportsNav'),
    compNav: document.getElementById('compNav'),
    eventsFeed: document.getElementById('eventsFeed'),
    feedTitle: document.getElementById('feedTitle'),
    searchInput: document.getElementById('searchInput'),
    searchClear: document.getElementById('searchClear'),
    totalSportsStat: document.getElementById('totalSportsStat'),
    totalEventsStat: document.getElementById('totalEventsStat'),
    betslipList: document.getElementById('betslipList'),
    betslipCount: document.getElementById('betslipCount'),
    betslipHeaderCount: document.getElementById('betslipHeaderCount'),
    stakeInput: document.getElementById('stakeInput'),
    totalOddsVal: document.getElementById('totalOddsVal'),
    potentialReturnVal: document.getElementById('potentialReturnVal'),
    placeBetBtn: document.getElementById('placeBetBtn'),
    clearSlipBtn: document.getElementById('clearSlipBtn'),
    toastContainer: document.getElementById('toastContainer')
  };

  // Initialize Application
  async function init() {
    setupEventListeners();
    await loadData();
  }

  // Load JSON Dataset
  async function loadData() {
    try {
      el.eventsFeed.innerHTML = '<div class="empty-feed"><div class="empty-icon">⏳</div><div>Loading Bet365 Odds Dataset...</div></div>';
      
      const response = await fetch('./all_matches.json?t=' + Date.now());
      if (!response.ok) {
        throw new Error(`Failed to load all_matches.json: ${response.status}`);
      }
      const data = await response.json();
      state.rawSports = data;

      // Normalize all events using Bet365Normalizer
      state.normalizedEvents = [];
      for (const sportObj of data) {
        const sport = sportObj.sport;
        for (const rawMatch of (sportObj.matches || [])) {
          const norm = window.Bet365Normalizer.normalizeEvent(rawMatch, sport);
          state.normalizedEvents.push(norm);
        }
      }

      // Update header statistics
      if (el.totalSportsStat) el.totalSportsStat.textContent = state.rawSports.length;
      if (el.totalEventsStat) el.totalEventsStat.textContent = state.normalizedEvents.length;

      // Render Navigation Tabs & Default Feed
      renderSportsNav();
      renderFeed();
    } catch (err) {
      console.error('Data loading error:', err);
      el.eventsFeed.innerHTML = `
        <div class="empty-feed">
          <div class="empty-icon">⚠️</div>
          <div><strong>Could not load all_matches.json</strong></div>
          <div style="font-size:0.8rem; margin-top:0.5rem; color:#ff6b6b;">${err.message}</div>
        </div>
      `;
    }
  }

  // Setup Event Listeners
  function setupEventListeners() {
    // Search input
    el.searchInput.addEventListener('input', (e) => {
      state.searchQuery = e.target.value.trim().toLowerCase();
      el.searchClear.style.display = state.searchQuery ? 'block' : 'none';
      renderFeed();
    });

    el.searchClear.addEventListener('click', () => {
      el.searchInput.value = '';
      state.searchQuery = '';
      el.searchClear.style.display = 'none';
      renderFeed();
    });

    // Stake input change
    el.stakeInput.addEventListener('input', (e) => {
      const val = parseFloat(e.target.value);
      state.stake = isNaN(val) || val < 0 ? 0 : val;
      updateBetSlipSummary();
    });

    // Clear betslip
    el.clearSlipBtn.addEventListener('click', () => {
      state.betSlip.clear();
      updateBetSlipUI();
      syncOddsButtons();
    });

    // Place bet action
    el.placeBetBtn.addEventListener('click', () => {
      if (state.betSlip.size === 0) return;
      const count = state.betSlip.size;
      const potReturn = el.potentialReturnVal.textContent;
      showToast(`✅ Bet placed successfully! ${count} selection(s) for ${potReturn}`);
      state.betSlip.clear();
      updateBetSlipUI();
      syncOddsButtons();
    });
  }

  // Render Sports Navigation Bar
  function renderSportsNav() {
    el.sportsNav.innerHTML = '';

    // "All Sports" Tab
    const allTab = document.createElement('button');
    allTab.className = `sport-tab ${state.activeSport === 'ALL' ? 'active' : ''}`;
    allTab.innerHTML = `🌐 All Sports <span class="sport-count">${state.normalizedEvents.length}</span>`;
    allTab.addEventListener('click', () => {
      state.activeSport = 'ALL';
      state.activeCompetition = 'ALL';
      updateActiveSportTabs();
      renderCompNav();
      renderFeed();
    });
    el.sportsNav.appendChild(allTab);

    // Individual Sports Tabs
    for (const sportObj of state.rawSports) {
      const sportName = sportObj.sport;
      const cfg = SPORT_CONFIG[sportName] || { icon: '🏅', label: sportName };
      const count = (sportObj.matches || []).length;

      const btn = document.createElement('button');
      btn.className = `sport-tab ${state.activeSport === sportName ? 'active' : ''}`;
      btn.dataset.sport = sportName;
      btn.innerHTML = `${cfg.icon} ${cfg.label} <span class="sport-count">${count}</span>`;
      btn.addEventListener('click', () => {
        state.activeSport = sportName;
        state.activeCompetition = 'ALL';
        updateActiveSportTabs();
        renderCompNav();
        renderFeed();
      });
      el.sportsNav.appendChild(btn);
    }

    renderCompNav();
  }

  function updateActiveSportTabs() {
    document.querySelectorAll('.sport-tab').forEach(tab => {
      if (state.activeSport === 'ALL') {
        tab.classList.toggle('active', tab.textContent.includes('All Sports'));
      } else {
        tab.classList.toggle('active', tab.dataset.sport === state.activeSport);
      }
    });
  }

  // Render Secondary Competition Chips
  function renderCompNav() {
    el.compNav.innerHTML = '';

    const eventsForSport = state.activeSport === 'ALL' 
      ? state.normalizedEvents 
      : state.normalizedEvents.filter(e => e.sport === state.activeSport);

    const compCounts = new Map();
    for (const ev of eventsForSport) {
      if (ev.competition) {
        compCounts.set(ev.competition, (compCounts.get(ev.competition) || 0) + 1);
      }
    }

    if (compCounts.size <= 1) {
      el.compNav.parentElement.style.display = 'none';
      return;
    }
    el.compNav.parentElement.style.display = 'block';

    // All Competitions Chip
    const allChip = document.createElement('button');
    allChip.className = `comp-chip ${state.activeCompetition === 'ALL' ? 'active' : ''}`;
    allChip.textContent = `All Competitions (${eventsForSport.length})`;
    allChip.addEventListener('click', () => {
      state.activeCompetition = 'ALL';
      renderCompNav();
      renderFeed();
    });
    el.compNav.appendChild(allChip);

    // Specific Competition Chips
    for (const [comp, count] of compCounts.entries()) {
      const chip = document.createElement('button');
      chip.className = `comp-chip ${state.activeCompetition === comp ? 'active' : ''}`;
      chip.textContent = `${comp} (${count})`;
      chip.addEventListener('click', () => {
        state.activeCompetition = comp;
        renderCompNav();
        renderFeed();
      });
      el.compNav.appendChild(chip);
    }
  }

  // Filter Events
  function getFilteredEvents() {
    return state.normalizedEvents.filter(ev => {
      // Sport match
      if (state.activeSport !== 'ALL' && ev.sport !== state.activeSport) {
        return false;
      }
      // Competition match
      if (state.activeCompetition !== 'ALL' && ev.competition !== state.activeCompetition) {
        return false;
      }
      // Search query
      if (state.searchQuery) {
        const q = state.searchQuery;
        const matchesTitle = ev.displayTitle.toLowerCase().includes(q);
        const matchesComp = (ev.competition || '').toLowerCase().includes(q);
        const matchesHome = (ev.home || '').toLowerCase().includes(q);
        const matchesAway = (ev.away || '').toLowerCase().includes(q);
        
        // Also search inside outright participants
        let matchesOutright = false;
        if (ev.isOutright) {
          for (const items of Object.values(ev.markets)) {
            for (const it of items) {
              if (it.selection.toLowerCase().includes(q)) {
                matchesOutright = true;
                break;
              }
            }
          }
        }
        if (!matchesTitle && !matchesComp && !matchesHome && !matchesAway && !matchesOutright) {
          return false;
        }
      }
      return true;
    });
  }

  // Render Main Events Feed
  function renderFeed() {
    const filtered = getFilteredEvents();
    
    // Update feed section title
    const sportLabel = state.activeSport === 'ALL' ? 'All Events' : (SPORT_CONFIG[state.activeSport]?.label || state.activeSport);
    const compLabel = state.activeCompetition !== 'ALL' ? ` · ${state.activeCompetition}` : '';
    el.feedTitle.innerHTML = `
      <span>${sportLabel}${compLabel}</span>
      <span class="badge">${filtered.length}</span>
    `;

    if (filtered.length === 0) {
      el.eventsFeed.innerHTML = `
        <div class="empty-feed">
          <div class="empty-icon">🔍</div>
          <div>No events found matching your filter or search.</div>
        </div>
      `;
      return;
    }

    const fragment = document.createDocumentFragment();
    for (const ev of filtered) {
      const card = createEventCard(ev);
      fragment.appendChild(card);
    }

    el.eventsFeed.innerHTML = '';
    el.eventsFeed.appendChild(fragment);
  }

  // Create Sport-Specific Event Card
  function createEventCard(ev) {
    if (ev.isOutright) {
      return renderOutrightCard(ev);
    }

    const sport = ev.sport;
    if (sport === 'Soccer' || sport === 'EPL') {
      return renderSoccerCard(ev);
    } else if (sport.includes('Tennis') || sport.includes('US Open')) {
      return renderTennisCard(ev);
    } else if (sport === 'American Football') {
      return renderAmericanFootballCard(ev);
    } else if (sport === 'MLB') {
      return renderMLBCard(ev);
    } else if (sport === 'Basketball') {
      return renderBasketballCard(ev);
    } else if (sport === 'Ice Hockey') {
      return renderIceHockeyCard(ev);
    } else if (sport.includes('Rugby')) {
      return renderRugbyCard(ev);
    } else if (sport === 'Handball') {
      return renderHandballCard(ev);
    } else if (sport === 'Cricket') {
      return renderCricketCard(ev);
    } else if (sport === 'Volleyball') {
      return renderVolleyballCard(ev);
    } else if (sport === 'Esports') {
      return renderEsportsCard(ev);
    }

    // Default Head-to-Head fallback
    return renderGenericH2HCard(ev);
  }

  // Card Header Generator
  function createCardHeader(ev) {
    const cfg = SPORT_CONFIG[ev.sport] || { icon: '🏅', label: ev.sport };
    const div = document.createElement('div');
    div.className = 'card-header';
    div.innerHTML = `
      <div class="card-meta-left">
        <span class="sport-tag">${cfg.icon} ${cfg.label}</span>
        <span class="comp-badge">${escapeHtml(ev.competition || '')}</span>
      </div>
      <div class="card-time">
        <span>⏰ ${escapeHtml(ev.kickoff || ev.date || '')}</span>
      </div>
    `;
    return div;
  }

  // Head to Head Matchup Display
  function createH2HMatchup(ev) {
    const div = document.createElement('div');
    div.className = 'h2h-matchup';
    div.innerHTML = `
      <div class="teams-wrapper">
        <div class="team-row">
          <span class="team-badge-pill">1</span>
          <span>${escapeHtml(ev.home || 'Home')}</span>
        </div>
        <div class="team-row">
          <span class="team-badge-pill">2</span>
          <span>${escapeHtml(ev.away || 'Away')}</span>
        </div>
      </div>
    `;
    return div;
  }

  /* ==========================================================================
     1. FOOTBALL / SOCCER / EPL RENDERER
     Markets:
     - Match Result: 1 [odds] | X [odds] | 2 [odds]
     - Both Teams to Score: Yes [odds] | No [odds]
     - Half Time/Full Time: 1/1, 1/X, 1/2, X/1, X/X, X/2, 2/1, 2/X, 2/2
     - Correct Score: 1-0, 2-0, 2-1, etc.
     All SIMPLE ODDS (Format A)
     ========================================================================== */
  function renderSoccerCard(ev) {
    const card = document.createElement('div');
    card.className = 'event-card';
    card.appendChild(createCardHeader(ev));
    card.appendChild(createH2HMatchup(ev));

    const markets = ev.markets;

    // Match Result (1 X 2)
    if (markets['Match Result']) {
      const section = document.createElement('div');
      section.className = 'market-section';
      section.innerHTML = `<div class="market-label">Match Result (1X2)</div>`;
      
      const group = document.createElement('div');
      group.className = 'odds-group grid-3';
      
      for (const item of markets['Match Result']) {
        group.appendChild(createOddsButton(ev, 'Match Result', item));
      }
      section.appendChild(group);
      card.appendChild(section);
    }

    // Both Teams to Score (Yes / No)
    if (markets['Both Teams to Score']) {
      const section = document.createElement('div');
      section.className = 'market-section';
      section.innerHTML = `<div class="market-label">Both Teams to Score</div>`;
      
      const group = document.createElement('div');
      group.className = 'odds-group grid-2';
      
      for (const item of markets['Both Teams to Score']) {
        group.appendChild(createOddsButton(ev, 'Both Teams to Score', item));
      }
      section.appendChild(group);
      card.appendChild(section);
    }

    // Half Time / Full Time (Collapsible 3x3 Grid)
    if (markets['Half Time/Full Time'] && markets['Half Time/Full Time'].length > 0) {
      const coll = createCollapsibleMarket('Half Time / Full Time', () => {
        const group = document.createElement('div');
        group.className = 'odds-group grid-3';
        for (const item of markets['Half Time/Full Time']) {
          group.appendChild(createOddsButton(ev, 'Half Time/Full Time', item));
        }
        return group;
      });
      card.appendChild(coll);
    }

    // Correct Score (Collapsible Grid)
    if (markets['Correct Score'] && markets['Correct Score'].length > 0) {
      const coll = createCollapsibleMarket('Correct Score', () => {
        const grid = document.createElement('div');
        grid.className = 'correct-score-grid';
        for (const item of markets['Correct Score']) {
          grid.appendChild(createOddsButton(ev, 'Correct Score', item));
        }
        return grid;
      });
      card.appendChild(coll);
    }

    return card;
  }

  /* ==========================================================================
     2. TENNIS / US OPEN / US OPEN WOMEN RENDERER
     Markets:
     - Match Winner / To Win Match: 1 [odds] | 2 [odds]
     - First Set Winner: 1 [odds] | 2 [odds]
     - Set Betting: 2-0, 2-1, 0-2, 1-2
     - Total Games: Over [line] [odds] | Under [line] [odds]
     - 1st Set Correct Score: 6-0, 6-1, etc.
     ========================================================================== */
  function renderTennisCard(ev) {
    const card = document.createElement('div');
    card.className = 'event-card';
    card.appendChild(createCardHeader(ev));
    card.appendChild(createH2HMatchup(ev));

    const markets = ev.markets;

    // To Win Match / Match Winner (1 | 2)
    const mwKey = markets['To Win Match'] ? 'To Win Match' : (markets['Match Winner'] ? 'Match Winner' : (markets['To Win'] ? 'To Win' : null));
    if (mwKey && markets[mwKey]) {
      const section = document.createElement('div');
      section.className = 'market-section';
      section.innerHTML = `<div class="market-label">To Win Match</div>`;
      
      const group = document.createElement('div');
      group.className = 'odds-group grid-2';
      
      for (const item of markets[mwKey]) {
        group.appendChild(createOddsButton(ev, mwKey, item));
      }
      section.appendChild(group);
      card.appendChild(section);
    }

    // First Set Winner (1 | 2)
    if (markets['First Set Winner']) {
      const section = document.createElement('div');
      section.className = 'market-section';
      section.innerHTML = `<div class="market-label">First Set Winner</div>`;
      
      const group = document.createElement('div');
      group.className = 'odds-group grid-2';
      
      for (const item of markets['First Set Winner']) {
        group.appendChild(createOddsButton(ev, 'First Set Winner', item));
      }
      section.appendChild(group);
      card.appendChild(section);
    }

    // Total Games (Line + Odds)
    const tgKey = markets['Total Games'] ? 'Total Games' : (markets['Total'] ? 'Total' : null);
    if (tgKey && markets[tgKey]) {
      const section = document.createElement('div');
      section.className = 'market-section';
      section.innerHTML = `<div class="market-label">Total Games (Over / Under)</div>`;
      
      const group = document.createElement('div');
      group.className = 'odds-group grid-2';
      
      for (const item of markets[tgKey]) {
        group.appendChild(createOddsButton(ev, tgKey, item));
      }
      section.appendChild(group);
      card.appendChild(section);
    }

    // Set Betting (Collapsible)
    if (markets['Set Betting'] && markets['Set Betting'].length > 0) {
      const coll = createCollapsibleMarket('Set Betting', () => {
        const group = document.createElement('div');
        group.className = 'odds-group grid-2';
        for (const item of markets['Set Betting']) {
          group.appendChild(createOddsButton(ev, 'Set Betting', item));
        }
        return group;
      });
      card.appendChild(coll);
    }

    // 1st Set Correct Score (Collapsible Grid)
    if (markets['1st Set Correct Score'] && markets['1st Set Correct Score'].length > 0) {
      const coll = createCollapsibleMarket('1st Set Correct Score', () => {
        const grid = document.createElement('div');
        grid.className = 'correct-score-grid';
        for (const item of markets['1st Set Correct Score']) {
          grid.appendChild(createOddsButton(ev, '1st Set Correct Score', item));
        }
        return grid;
      });
      card.appendChild(coll);
    }

    return card;
  }

  /* ==========================================================================
     3. AMERICAN FOOTBALL RENDERER
     Markets:
     - Spread: Team 1 +3 — 1.91, Team 2 -3 — 1.91 (Line + Odds)
     - Money Line: Team 1 — 1.80, Team 2 — 2.10 (Simple Odds)
     ========================================================================== */
  function renderAmericanFootballCard(ev) {
    const card = document.createElement('div');
    card.className = 'event-card';
    card.appendChild(createCardHeader(ev));
    card.appendChild(createH2HMatchup(ev));

    const markets = ev.markets;

    // Spread (Line + Odds)
    if (markets['Spread']) {
      const section = document.createElement('div');
      section.className = 'market-section';
      section.innerHTML = `<div class="market-label">Spread (Handicap)</div>`;
      const group = document.createElement('div');
      group.className = 'odds-group grid-2';
      for (const item of markets['Spread']) {
        group.appendChild(createOddsButton(ev, 'Spread', item));
      }
      section.appendChild(group);
      card.appendChild(section);
    }

    // Money Line (Simple Odds)
    if (markets['Money Line']) {
      const section = document.createElement('div');
      section.className = 'market-section';
      section.innerHTML = `<div class="market-label">Money Line</div>`;
      const group = document.createElement('div');
      group.className = 'odds-group grid-2';
      for (const item of markets['Money Line']) {
        group.appendChild(createOddsButton(ev, 'Money Line', item));
      }
      section.appendChild(group);
      card.appendChild(section);
    }

    return card;
  }

  /* ==========================================================================
     4. MLB / BASEBALL RENDERER
     Markets:
     - Money Line: Team 1 — odds, Team 2 — odds (Simple Odds)
     - Run Line: Team 1 +1.5 — odds, Team 2 -1.5 — odds (Line + Odds)
     - Total: Over 15.5 — odds, Under 15.5 — odds (Line + Odds)
     ========================================================================== */
  function renderMLBCard(ev) {
    const card = document.createElement('div');
    card.className = 'event-card';
    card.appendChild(createCardHeader(ev));
    card.appendChild(createH2HMatchup(ev));

    const markets = ev.markets;

    // Money Line
    if (markets['Money Line']) {
      const section = document.createElement('div');
      section.className = 'market-section';
      section.innerHTML = `<div class="market-label">Money Line</div>`;
      const group = document.createElement('div');
      group.className = 'odds-group grid-2';
      for (const item of markets['Money Line']) {
        group.appendChild(createOddsButton(ev, 'Money Line', item));
      }
      section.appendChild(group);
      card.appendChild(section);
    }

    // Run Line (Line + Odds)
    if (markets['Run Line']) {
      const section = document.createElement('div');
      section.className = 'market-section';
      section.innerHTML = `<div class="market-label">Run Line</div>`;
      const group = document.createElement('div');
      group.className = 'odds-group grid-2';
      for (const item of markets['Run Line']) {
        group.appendChild(createOddsButton(ev, 'Run Line', item));
      }
      section.appendChild(group);
      card.appendChild(section);
    }

    // Total (Line + Odds)
    if (markets['Total']) {
      const section = document.createElement('div');
      section.className = 'market-section';
      section.innerHTML = `<div class="market-label">Total Runs (Over / Under)</div>`;
      const group = document.createElement('div');
      group.className = 'odds-group grid-2';
      for (const item of markets['Total']) {
        group.appendChild(createOddsButton(ev, 'Total', item));
      }
      section.appendChild(group);
      card.appendChild(section);
    }

    return card;
  }

  /* ==========================================================================
     5. BASKETBALL RENDERER
     Markets:
     - Point Spread / Spread: Team 1 +1.5 — odds, Team 2 -1.5 — odds (Line + Odds)
     - Moneyline / Money Line: Team 1 — odds, Team 2 — odds (Simple Odds)
     - Total Points / Total: Over [line] — odds, Under [line] — odds (Line + Odds)
     ========================================================================== */
  function renderBasketballCard(ev) {
    const card = document.createElement('div');
    card.className = 'event-card';
    card.appendChild(createCardHeader(ev));
    card.appendChild(createH2HMatchup(ev));

    const markets = ev.markets;

    // Point Spread / Spread / Handicap (Line + Odds)
    const spreadKey = markets['Point Spread'] ? 'Point Spread' : (markets['Spread'] ? 'Spread' : (markets['Handicap'] ? 'Handicap' : null));
    if (spreadKey && markets[spreadKey]) {
      const section = document.createElement('div');
      section.className = 'market-section';
      section.innerHTML = `<div class="market-label">Point Spread</div>`;
      const group = document.createElement('div');
      group.className = 'odds-group grid-2';
      for (const item of markets[spreadKey]) {
        group.appendChild(createOddsButton(ev, spreadKey, item));
      }
      section.appendChild(group);
      card.appendChild(section);
    }

    // Moneyline / Money Line (Simple Odds)
    const mlKey = markets['Moneyline'] ? 'Moneyline' : (markets['Money Line'] ? 'Money Line' : null);
    if (mlKey && markets[mlKey]) {
      const section = document.createElement('div');
      section.className = 'market-section';
      section.innerHTML = `<div class="market-label">Moneyline</div>`;
      const group = document.createElement('div');
      group.className = 'odds-group grid-2';
      for (const item of markets[mlKey]) {
        group.appendChild(createOddsButton(ev, mlKey, item));
      }
      section.appendChild(group);
      card.appendChild(section);
    }

    // Total Points / Total (Line + Odds)
    const totalKey = markets['Total Points'] ? 'Total Points' : (markets['Total'] ? 'Total' : null);
    if (totalKey && markets[totalKey]) {
      const section = document.createElement('div');
      section.className = 'market-section';
      section.innerHTML = `<div class="market-label">Total Points (Over / Under)</div>`;
      const group = document.createElement('div');
      group.className = 'odds-group grid-2';
      for (const item of markets[totalKey]) {
        group.appendChild(createOddsButton(ev, totalKey, item));
      }
      section.appendChild(group);
      card.appendChild(section);
    }

    return card;
  }

  /* ==========================================================================
     6. ICE HOCKEY RENDERER
     Markets:
     - Money Line: Team 1 — odds, Team 2 — odds (Simple Odds)
     ========================================================================== */
  function renderIceHockeyCard(ev) {
    const card = document.createElement('div');
    card.className = 'event-card';
    card.appendChild(createCardHeader(ev));
    card.appendChild(createH2HMatchup(ev));

    const markets = ev.markets;
    const mlKey = markets['Money Line'] ? 'Money Line' : (markets['To Win'] ? 'To Win' : null);

    if (mlKey && markets[mlKey]) {
      const section = document.createElement('div');
      section.className = 'market-section';
      section.innerHTML = `<div class="market-label">Money Line</div>`;
      const group = document.createElement('div');
      group.className = 'odds-group grid-2';
      for (const item of markets[mlKey]) {
        group.appendChild(createOddsButton(ev, mlKey, item));
      }
      section.appendChild(group);
      card.appendChild(section);
    }

    return card;
  }

  /* ==========================================================================
     7 & 8. RUGBY LEAGUE & RUGBY UNION RENDERER
     Markets:
     - To Win: Team 1 — odds, Team 2 — odds (Simple Odds)
     - Handicap: Team 1 +X — odds, Team 2 +X/-X — odds (Line + Odds)
     - Total: Over X — odds, Under X — odds (Line + Odds)
     ========================================================================== */
  function renderRugbyCard(ev) {
    const card = document.createElement('div');
    card.className = 'event-card';
    card.appendChild(createCardHeader(ev));
    card.appendChild(createH2HMatchup(ev));

    const markets = ev.markets;

    // To Win (Simple Odds)
    const winKey = markets['To Win'] ? 'To Win' : (markets['Money Line'] ? 'Money Line' : null);
    if (winKey && markets[winKey]) {
      const section = document.createElement('div');
      section.className = 'market-section';
      section.innerHTML = `<div class="market-label">To Win</div>`;
      const group = document.createElement('div');
      group.className = 'odds-group grid-2';
      for (const item of markets[winKey]) {
        group.appendChild(createOddsButton(ev, winKey, item));
      }
      section.appendChild(group);
      card.appendChild(section);
    }

    // Handicap (Line + Odds)
    if (markets['Handicap']) {
      const section = document.createElement('div');
      section.className = 'market-section';
      section.innerHTML = `<div class="market-label">Handicap</div>`;
      const group = document.createElement('div');
      group.className = 'odds-group grid-2';
      for (const item of markets['Handicap']) {
        group.appendChild(createOddsButton(ev, 'Handicap', item));
      }
      section.appendChild(group);
      card.appendChild(section);
    }

    // Total (Line + Odds)
    if (markets['Total']) {
      const section = document.createElement('div');
      section.className = 'market-section';
      section.innerHTML = `<div class="market-label">Total Points (Over / Under)</div>`;
      const group = document.createElement('div');
      group.className = 'odds-group grid-2';
      for (const item of markets['Total']) {
        group.appendChild(createOddsButton(ev, 'Total', item));
      }
      section.appendChild(group);
      card.appendChild(section);
    }

    return card;
  }

  /* ==========================================================================
     9. HANDBALL RENDERER
     Markets:
     - Full Time Result / Match Result: 1 [odds] | X [odds] | 2 [odds]
     - Total Goals / Total: Over [line] [odds] | Under [line] [odds]
     - Handicap / Spread: 1 [line] [odds] | 2 [line] [odds]
     ========================================================================== */
  function renderHandballCard(ev) {
    const card = document.createElement('div');
    card.className = 'event-card';
    card.appendChild(createCardHeader(ev));
    card.appendChild(createH2HMatchup(ev));

    const markets = ev.markets;

    // Full Time Result (1 X 2)
    const ftKey = markets['Full Time Result'] ? 'Full Time Result' : (markets['Match Result'] ? 'Match Result' : (markets['Money Line'] ? 'Money Line' : null));
    if (ftKey && markets[ftKey]) {
      const section = document.createElement('div');
      section.className = 'market-section';
      section.innerHTML = `<div class="market-label">Full Time Result</div>`;
      const items = markets[ftKey];
      const group = document.createElement('div');
      group.className = items.length === 3 ? 'odds-group grid-3' : 'odds-group grid-2';
      for (const item of items) {
        group.appendChild(createOddsButton(ev, ftKey, item));
      }
      section.appendChild(group);
      card.appendChild(section);
    }

    // Total Goals (Line + Odds)
    const totKey = markets['Total Goals'] ? 'Total Goals' : (markets['Total'] ? 'Total' : null);
    if (totKey && markets[totKey]) {
      const section = document.createElement('div');
      section.className = 'market-section';
      section.innerHTML = `<div class="market-label">Total Goals (Over / Under)</div>`;
      const group = document.createElement('div');
      group.className = 'odds-group grid-2';
      for (const item of markets[totKey]) {
        group.appendChild(createOddsButton(ev, totKey, item));
      }
      section.appendChild(group);
      card.appendChild(section);
    }

    // Handicap / Spread (Line + Odds)
    const hdKey = markets['Handicap / Spread'] ? 'Handicap / Spread' : (markets['Handicap'] ? 'Handicap' : (markets['Spread'] ? 'Spread' : null));
    if (hdKey && markets[hdKey]) {
      const section = document.createElement('div');
      section.className = 'market-section';
      section.innerHTML = `<div class="market-label">Handicap / Spread</div>`;
      const group = document.createElement('div');
      group.className = 'odds-group grid-2';
      for (const item of markets[hdKey]) {
        group.appendChild(createOddsButton(ev, hdKey, item));
      }
      section.appendChild(group);
      card.appendChild(section);
    }

    return card;
  }

  /* ==========================================================================
     10. CRICKET RENDERER
     Markets:
     - To Win: Team 1 — odds, Team 2 — odds (Simple Odds)
     - Total: Over X — odds, Under X — odds (Line + Odds)
     ========================================================================== */
  function renderCricketCard(ev) {
    const card = document.createElement('div');
    card.className = 'event-card';
    card.appendChild(createCardHeader(ev));
    card.appendChild(createH2HMatchup(ev));

    const markets = ev.markets;
    const winKey = markets['To Win'] ? 'To Win' : (markets['Money Line'] ? 'Money Line' : null);

    if (winKey && markets[winKey]) {
      const section = document.createElement('div');
      section.className = 'market-section';
      section.innerHTML = `<div class="market-label">To Win Match</div>`;
      const group = document.createElement('div');
      group.className = 'odds-group grid-2';
      for (const item of markets[winKey]) {
        group.appendChild(createOddsButton(ev, winKey, item));
      }
      section.appendChild(group);
      card.appendChild(section);
    }

    if (markets['Total']) {
      const section = document.createElement('div');
      section.className = 'market-section';
      section.innerHTML = `<div class="market-label">Total Runs</div>`;
      const group = document.createElement('div');
      group.className = 'odds-group grid-2';
      for (const item of markets['Total']) {
        group.appendChild(createOddsButton(ev, 'Total', item));
      }
      section.appendChild(group);
      card.appendChild(section);
    }

    return card;
  }

  /* ==========================================================================
     11. VOLLEYBALL RENDERER
     Markets:
     - To Win: Team 1 — odds, Team 2 — odds (Simple Odds)
     - Handicap: Team 1 +X/-X — odds, Team 2 +X/-X — odds (Line + Odds)
     ========================================================================== */
  function renderVolleyballCard(ev) {
    const card = document.createElement('div');
    card.className = 'event-card';
    card.appendChild(createCardHeader(ev));
    card.appendChild(createH2HMatchup(ev));

    const markets = ev.markets;
    const winKey = markets['To Win'] ? 'To Win' : (markets['Money Line'] ? 'Money Line' : null);

    if (winKey && markets[winKey]) {
      const section = document.createElement('div');
      section.className = 'market-section';
      section.innerHTML = `<div class="market-label">To Win Match</div>`;
      const group = document.createElement('div');
      group.className = 'odds-group grid-2';
      for (const item of markets[winKey]) {
        group.appendChild(createOddsButton(ev, winKey, item));
      }
      section.appendChild(group);
      card.appendChild(section);
    }

    if (markets['Handicap']) {
      const section = document.createElement('div');
      section.className = 'market-section';
      section.innerHTML = `<div class="market-label">Sets / Points Handicap</div>`;
      const group = document.createElement('div');
      group.className = 'odds-group grid-2';
      for (const item of markets['Handicap']) {
        group.appendChild(createOddsButton(ev, 'Handicap', item));
      }
      section.appendChild(group);
      card.appendChild(section);
    }

    return card;
  }

  /* ==========================================================================
     12. ESPORTS RENDERER
     Markets:
     - To Win: Team 1 — odds, Team 2 — odds (Simple Odds)
     - Handicap: Team 1 +X/-X — odds, Team 2 +X/-X — odds (Line + Odds)
     - Total: Over X — odds, Under X — odds (Line + Odds)
     ========================================================================== */
  function renderEsportsCard(ev) {
    const card = document.createElement('div');
    card.className = 'event-card';
    card.appendChild(createCardHeader(ev));
    card.appendChild(createH2HMatchup(ev));

    const markets = ev.markets;
    const winKey = markets['To Win'] ? 'To Win' : (markets['Money Line'] ? 'Money Line' : null);

    if (winKey && markets[winKey]) {
      const section = document.createElement('div');
      section.className = 'market-section';
      section.innerHTML = `<div class="market-label">Match Winner</div>`;
      const group = document.createElement('div');
      group.className = 'odds-group grid-2';
      for (const item of markets[winKey]) {
        group.appendChild(createOddsButton(ev, winKey, item));
      }
      section.appendChild(group);
      card.appendChild(section);
    }

    if (markets['Handicap']) {
      const section = document.createElement('div');
      section.className = 'market-section';
      section.innerHTML = `<div class="market-label">Map Handicap</div>`;
      const group = document.createElement('div');
      group.className = 'odds-group grid-2';
      for (const item of markets['Handicap']) {
        group.appendChild(createOddsButton(ev, 'Handicap', item));
      }
      section.appendChild(group);
      card.appendChild(section);
    }

    if (markets['Total']) {
      const section = document.createElement('div');
      section.className = 'market-section';
      section.innerHTML = `<div class="market-label">Total Maps (Over / Under)</div>`;
      const group = document.createElement('div');
      group.className = 'odds-group grid-2';
      for (const item of markets['Total']) {
        group.appendChild(createOddsButton(ev, 'Total', item));
      }
      section.appendChild(group);
      card.appendChild(section);
    }

    return card;
  }

  /* ==========================================================================
     13, 14 & 15. OUTRIGHT SPORTS (CYCLING, GOLF, F1)
     Strict Specification:
     - NOT a normal head-to-head event.
     - Competition represents a competition/race/tournament containing multiple participants.
     - Display each rider/golfer/driver as an individual selection:
       [ Participant Name ] ODDS
     - Do NOT display Cycling as Home Team vs Away Team.
     - Do NOT display Golf as Player 1 vs Player 2.
     - Do NOT display empty "away" participants.
     ========================================================================== */
  function renderOutrightCard(ev) {
    const card = document.createElement('div');
    card.className = 'event-card outright-card';

    const cfg = SPORT_CONFIG[ev.sport] || { icon: '🏆', label: ev.sport };

    // Available markets
    const marketNames = Object.keys(ev.markets).filter(k => (ev.markets[k] || []).length > 0);
    let activeMarket = marketNames.find(k => 
      k.toLowerCase().includes('race winner') || k.toLowerCase().includes('outright winner') || k.toLowerCase().includes('to win outright')
    ) || marketNames[0] || 'Outright Winner';

    // Outright Header
    const header = document.createElement('div');
    header.className = 'outright-header';
    const renderHeaderContent = () => {
      const currentItems = ev.markets[activeMarket] || [];
      header.innerHTML = `
        <div class="outright-title-group">
          <span class="outright-icon">${cfg.icon}</span>
          <div>
            <div class="outright-title">${escapeHtml(ev.displayTitle)}</div>
            <div class="outright-meta">
              <span>📅 ${escapeHtml(ev.kickoff || ev.date || '')}</span>
              <span>🏁 ${currentItems.length} Contenders</span>
              <span class="sport-tag">${cfg.label}</span>
            </div>
          </div>
        </div>
      `;
    };
    renderHeaderContent();
    card.appendChild(header);

    // Contenders Filter Bar & Market Switcher
    const filterBar = document.createElement('div');
    filterBar.className = 'outright-filter-bar';
    filterBar.innerHTML = `
      <div class="outright-markets-nav"></div>
      <input type="text" class="outright-search" placeholder="Search participant..." />
    `;
    card.appendChild(filterBar);

    const marketsNav = filterBar.querySelector('.outright-markets-nav');
    const searchInput = filterBar.querySelector('.outright-search');

    // Contenders Grid
    const grid = document.createElement('div');
    grid.className = 'outright-grid';
    card.appendChild(grid);

    const renderGrid = (filterText = '') => {
      grid.innerHTML = '';
      const items = ev.markets[activeMarket] || [];
      const f = filterText.toLowerCase();
      const matching = items.filter(it => it.selection.toLowerCase().includes(f));

      if (matching.length === 0) {
        grid.innerHTML = '<div style="grid-column:1/-1; padding:1.5rem; text-align:center; color:var(--text-muted);">No participant matching search.</div>';
        return;
      }

      for (const item of matching) {
        grid.appendChild(createOddsButton(ev, activeMarket, item));
      }
    };

    const renderMarketsNav = () => {
      marketsNav.innerHTML = '';
      if (marketNames.length <= 1) {
        marketsNav.innerHTML = `<span style="font-size:0.8rem; font-weight:700; color:var(--text-dim); text-transform:uppercase;">Market: ${escapeHtml(activeMarket)}</span>`;
        return;
      }

      // Render tab chips for multiple markets (e.g. F1, Golf)
      for (const mName of marketNames) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = `comp-chip ${mName === activeMarket ? 'active' : ''}`;
        btn.style.margin = '2px';
        btn.textContent = mName;
        btn.addEventListener('click', () => {
          activeMarket = mName;
          renderMarketsNav();
          renderHeaderContent();
          renderGrid(searchInput.value.trim());
        });
        marketsNav.appendChild(btn);
      }
    };

    searchInput.addEventListener('input', (e) => {
      renderGrid(e.target.value.trim());
    });

    renderMarketsNav();
    renderGrid();

    return card;
  }

  // Generic Head to Head Card Fallback
  function renderGenericH2HCard(ev) {
    const card = document.createElement('div');
    card.className = 'event-card';
    card.appendChild(createCardHeader(ev));
    card.appendChild(createH2HMatchup(ev));

    for (const [mName, items] of Object.entries(ev.markets)) {
      if (!items || items.length === 0) continue;
      const section = document.createElement('div');
      section.className = 'market-section';
      section.innerHTML = `<div class="market-label">${escapeHtml(mName)}</div>`;

      const group = document.createElement('div');
      group.className = items.length === 2 ? 'odds-group grid-2' : (items.length === 3 ? 'odds-group grid-3' : 'odds-group grid-col');

      for (const it of items) {
        group.appendChild(createOddsButton(ev, mName, it));
      }
      section.appendChild(group);
      card.appendChild(section);
    }
    return card;
  }

  /* ==========================================================================
     THE ODDS BUTTON COMPONENT
     Format A (Simple Odds): [ SELECTION ] ODDS
     Format B (Line + Odds): [ SELECTION ] LINE ODDS
     ========================================================================== */
  function createOddsButton(ev, marketName, item) {
    const btn = document.createElement('button');
    btn.className = 'odds-btn';
    btn.type = 'button';

    const pickKey = `${ev.id}::${marketName}::${item.selection}::${item.line || ''}`;
    btn.dataset.pickKey = pickKey;

    if (state.betSlip.has(pickKey)) {
      btn.classList.add('selected');
    }

    if (item.format === 'B' && item.line) {
      // FORMAT B: Line + Odds -> [ SELECTION ] LINE ODDS
      btn.innerHTML = `
        <span class="sel-name" title="${escapeHtml(item.selection)}">${escapeHtml(item.selection)}</span>
        <span class="line-badge">${escapeHtml(item.line)}</span>
        <span class="odds-val">${escapeHtml(item.odds)}</span>
      `;
    } else {
      // FORMAT A: Simple Odds -> [ SELECTION ] ODDS
      btn.innerHTML = `
        <span class="sel-name" title="${escapeHtml(item.selection)}">${escapeHtml(item.selection)}</span>
        <span class="odds-val">${escapeHtml(item.odds)}</span>
      `;
    }

    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      toggleBetSelection(ev, marketName, item, pickKey, btn);
    });

    return btn;
  }

  // Toggle Bet Selection State
  function toggleBetSelection(ev, marketName, item, pickKey, btn) {
    if (state.betSlip.has(pickKey)) {
      state.betSlip.delete(pickKey);
      btn.classList.remove('selected');
      showToast(`Removed: ${item.selection}`);
    } else {
      state.betSlip.set(pickKey, {
        pickKey,
        eventId: ev.id,
        eventTitle: ev.displayTitle,
        sport: ev.sport,
        marketName,
        selection: item.selection,
        line: item.line || '',
        odds: parseFloat(item.odds) || 1.0,
        oddsStr: item.odds,
        format: item.format
      });
      btn.classList.add('selected');
      showToast(`Added to slip: ${item.selection} (${item.odds})`);
    }

    updateBetSlipUI();
  }

  // Synchronize button selection classes across feed
  function syncOddsButtons() {
    document.querySelectorAll('.odds-btn').forEach(btn => {
      const key = btn.dataset.pickKey;
      btn.classList.toggle('selected', state.betSlip.has(key));
    });
  }

  // Update Bet Slip UI & Calculations
  function updateBetSlipUI() {
    const items = Array.from(state.betSlip.values());
    const count = items.length;

    if (el.betslipCount) el.betslipCount.textContent = count;
    if (el.betslipHeaderCount) el.betslipHeaderCount.textContent = count;

    if (count === 0) {
      el.betslipList.innerHTML = `
        <div class="betslip-empty">
          <div style="font-size:1.5rem; margin-bottom:0.4rem;">🎟️</div>
          <div>Your Bet Slip is empty.</div>
          <div style="font-size:0.75rem; color:var(--text-muted); margin-top:0.25rem;">
            Click on any odds button to add selections.
          </div>
        </div>
      `;
      el.placeBetBtn.disabled = true;
      el.totalOddsVal.textContent = '0.00';
      el.potentialReturnVal.textContent = '$0.00';
      return;
    }

    el.placeBetBtn.disabled = false;
    el.betslipList.innerHTML = '';

    for (const bet of items) {
      const itemEl = document.createElement('div');
      itemEl.className = 'betslip-item';

      const lineDisplay = bet.line ? `<span class="line-badge" style="margin-left:0.3rem;">${escapeHtml(bet.line)}</span>` : '';

      itemEl.innerHTML = `
        <div class="betslip-item-header">
          <div class="betslip-item-title" title="${escapeHtml(bet.eventTitle)}">
            ${escapeHtml(bet.eventTitle)}
          </div>
          <button class="betslip-remove" title="Remove selection">✕</button>
        </div>
        <div style="font-size:0.75rem; color:var(--text-muted); margin-bottom:0.35rem;">
          ${escapeHtml(bet.marketName)} · ${escapeHtml(bet.sport)}
        </div>
        <div class="betslip-pick">
          <div class="pick-name">
            <span>${escapeHtml(bet.selection)}</span>
            ${lineDisplay}
          </div>
          <div class="pick-odds">${bet.oddsStr}</div>
        </div>
      `;

      itemEl.querySelector('.betslip-remove').addEventListener('click', () => {
        state.betSlip.delete(bet.pickKey);
        updateBetSlipUI();
        syncOddsButtons();
      });

      el.betslipList.appendChild(itemEl);
    }

    updateBetSlipSummary();
  }

  // Calculate Accumulator Combined Odds and Potential Return
  function updateBetSlipSummary() {
    const items = Array.from(state.betSlip.values());
    if (items.length === 0) {
      el.totalOddsVal.textContent = '0.00';
      el.potentialReturnVal.textContent = '$0.00';
      return;
    }

    let combinedOdds = 1.0;
    for (const bet of items) {
      combinedOdds *= bet.odds;
    }

    const potentialReturn = state.stake * combinedOdds;

    el.totalOddsVal.textContent = combinedOdds.toFixed(2);
    el.potentialReturnVal.textContent = '$' + potentialReturn.toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    });
  }

  // Collapsible Market Accordion Helper
  function createCollapsibleMarket(title, contentBuilder) {
    const wrapper = document.createElement('div');
    wrapper.className = 'collapsible-market';

    const trigger = document.createElement('button');
    trigger.className = 'collapsible-trigger';
    trigger.type = 'button';
    trigger.innerHTML = `
      <span>${escapeHtml(title)}</span>
      <span class="arrow">▼</span>
    `;

    const content = document.createElement('div');
    content.className = 'collapsible-content';

    let built = false;
    trigger.addEventListener('click', () => {
      const isOpen = content.classList.toggle('open');
      trigger.querySelector('.arrow').textContent = isOpen ? '▲' : '▼';
      if (isOpen && !built) {
        content.appendChild(contentBuilder());
        built = true;
      }
    });

    wrapper.appendChild(trigger);
    wrapper.appendChild(content);
    return wrapper;
  }

  // Toast Notification Helper
  function showToast(message) {
    if (!el.toastContainer) return;
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.textContent = message;
    el.toastContainer.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(10px)';
      toast.style.transition = 'all 0.3s ease';
      setTimeout(() => toast.remove(), 300);
    }, 2400);
  }

  function escapeHtml(str) {
    return String(str || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  // Start
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
