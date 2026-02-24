/**
 * app.js — NBA Polymarket Edge Frontend
 * Handles all the UI logic: fetching data, rendering game cards,
 * showing modal details, auto-refresh, etc.
 *
 * Architecture:
 *   1. On load → fetchDashboard() → renders game cards + alerts
 *   2. User taps game card → openGameModal(gameData) → shows detail view
 *   3. Auto-refresh timer keeps data fresh
 */

// ============================================================
// STATE
// ============================================================
let dashboardData = null;        // Cached dashboard data
let currentView = 'cards';       // 'cards' or 'compact'
let refreshTimer = null;         // Auto-refresh interval
let isLoading = false;           // Prevents duplicate fetches

// ============================================================
// INITIALIZATION
// ============================================================

document.addEventListener('DOMContentLoaded', () => {
  // Set today's date in the header
  const dateEl = document.getElementById('currentDate');
  if (dateEl) {
    dateEl.textContent = new Date().toLocaleDateString('en-US', {
      weekday: 'short', month: 'short', day: 'numeric'
    });
  }

  // Load initial data
  fetchDashboard();

  // Set up auto-refresh (5 minutes default)
  setupAutoRefresh();

  // Handle browser back button closing modal
  window.addEventListener('popstate', closeModal);

  // Close modal with Escape key
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeModal();
  });
});

// ============================================================
// DATA FETCHING
// ============================================================

async function fetchDashboard(forceRefresh = false) {
  if (isLoading) return;
  isLoading = true;

  const refreshBtn = document.getElementById('refreshBtn');
  const refreshDot = document.getElementById('refreshDot');

  // Update UI to show loading state
  refreshBtn?.classList.add('spinning');
  if (refreshDot) refreshDot.className = 'refresh-dot loading';
  document.getElementById('lastUpdated').textContent = 'Updating...';

  try {
    const url = forceRefresh ? '/api/dashboard?refresh=true' : '/api/dashboard';
    const response = await fetch(url);

    if (!response.ok) {
      throw new Error(`Server error: ${response.status}`);
    }

    const data = await response.json();

    if (data.error) {
      throw new Error(data.message || data.error);
    }

    // Save data and render
    dashboardData = data;
    renderDashboard(data);

    // Update refresh indicator
    if (refreshDot) refreshDot.className = 'refresh-dot';
    updateLastUpdated(data.last_updated, data.from_cache);

  } catch (error) {
    console.error('Failed to fetch dashboard:', error);
    showError(error.message);
    if (refreshDot) refreshDot.className = 'refresh-dot stale';
  } finally {
    isLoading = false;
    refreshBtn?.classList.remove('spinning');
  }
}

// Called when user hits the Refresh button
function refreshData() {
  fetchDashboard(true);
}

// ============================================================
// AUTO-REFRESH LOGIC
// ============================================================

function setupAutoRefresh() {
  // Clear any existing timer
  if (refreshTimer) clearInterval(refreshTimer);

  // Decide refresh rate based on time of day
  // Within 1 hour of tipoff → faster refresh
  const refreshInterval = getRefreshInterval();

  refreshTimer = setInterval(() => {
    fetchDashboard(false);  // Use cache if fresh enough
    // Recalculate interval each time (game times change)
    setupAutoRefresh();
  }, refreshInterval);

  console.log(`Auto-refresh set to ${refreshInterval / 1000}s`);
}

function getRefreshInterval() {
  const now = new Date();
  const hour = now.getHours();

  // NBA games typically start 7pm-10pm ET
  // Between 6pm-midnight, refresh more frequently
  if (hour >= 18 && hour <= 23) {
    return 60 * 1000;    // 1 minute during prime time
  }
  return 5 * 60 * 1000;  // 5 minutes otherwise
}

// ============================================================
// RENDERING
// ============================================================

function renderDashboard(data) {
  const { games = [], alerts = [], stats = {} } = data;

  // Show main content, hide loading/error
  document.getElementById('loadingScreen').classList.add('hidden');
  document.getElementById('errorScreen').classList.add('hidden');

  if (!games || games.length === 0) {
    document.getElementById('noGamesScreen').classList.remove('hidden');
    document.getElementById('mainContent').classList.add('hidden');
    return;
  }

  document.getElementById('noGamesScreen').classList.add('hidden');
  document.getElementById('mainContent').classList.remove('hidden');

  // Render stats bar
  renderStatsBar(stats);

  // Render value alerts
  renderAlerts(alerts);

  // Render game cards
  renderGames(games);
}

function renderStatsBar(stats) {
  setEl('statGames', stats.game_count ?? '—');
  setEl('statPoly', stats.polymarket_markets ?? '—');
  setEl('statAlerts', stats.value_alerts ?? '—');
  setEl('statInjuries', stats.injured_teams ?? '—');
}

function renderAlerts(alerts) {
  const container = document.getElementById('alertsContainer');
  const countEl = document.getElementById('alertCount');

  if (!alerts || alerts.length === 0) {
    container.innerHTML = '<p class="empty-state">No significant edges detected — markets look efficient</p>';
    if (countEl) countEl.textContent = '0';
    return;
  }

  if (countEl) countEl.textContent = alerts.length;

  container.innerHTML = alerts.map(alert => {
    const signal = alert.signal || 'none';
    const emoji = signal === 'green' ? '🟢' : signal === 'red' ? '🔴' : '🟡';
    const edge = alert.edge ? `${alert.edge > 0 ? '+' : ''}${alert.edge.toFixed(1)}%` : 'N/A';

    const badges = [];
    if (alert.has_injury) badges.push('🤕 Injury');
    if (alert.is_b2b) badges.push('⚡ B2B');

    return `
      <div class="alert-card signal-${signal}" onclick="openGameByTeam('${esc(alert.team)}')">
        <span class="alert-signal">${emoji}</span>
        <div class="alert-body">
          <div class="alert-team">${esc(alert.team)} <span style="color:var(--text-muted);font-weight:400;font-size:12px">vs ${esc(alert.opponent)}</span></div>
          <div class="alert-desc">${esc(alert.description)}${badges.length ? ' · ' + badges.join(' · ') : ''}</div>
        </div>
        <div class="alert-edge">
          <div class="alert-edge-value">${edge}</div>
          <div class="alert-edge-label">Edge</div>
        </div>
      </div>
    `;
  }).join('');
}

function renderGames(games) {
  const container = document.getElementById('gamesContainer');
  if (!games || games.length === 0) {
    container.innerHTML = '<p class="empty-state">No games found</p>';
    return;
  }

  container.innerHTML = games.map((gameData, idx) => renderGameCard(gameData, idx)).join('');
}

function renderGameCard(gameData, idx) {
  const game = gameData.game || {};
  const analysis = gameData.analysis || {};
  const homeAnalysis = analysis.home || {};
  const awayAnalysis = analysis.away || {};
  const homeInjury = gameData.home_injury_summary || {};
  const awayInjury = gameData.away_injury_summary || {};

  const homeTeam = game.home_team || 'Home Team';
  const awayTeam = game.away_team || 'Away Team';
  const homeAbbrev = game.home_abbrev || shortName(homeTeam);
  const awayAbbrev = game.away_abbrev || shortName(awayTeam);

  // Game status
  const status = game.status || 'Scheduled';
  const statusClass = status === 'In Progress' ? 'status-live' :
                      status === 'Final'       ? 'status-final' : 'status-scheduled';
  const statusText = status === 'In Progress' ? '● LIVE' : status.toUpperCase();

  // Game time display
  const gameTime = formatGameTime(game.game_time_utc || game.game_time);

  // Alert level for left border
  const alertLevel = analysis.game_alert_level || 'low';

  // Polymarket prices
  const homePoly = homeAnalysis.poly_prob;   // e.g. 62.5
  const awayPoly = awayAnalysis.poly_prob;

  // Sportsbook probs
  const homeBook = homeAnalysis.book_prob;
  const awayBook = awayAnalysis.book_prob;

  // Sportsbook American odds
  const oddsConsensus = gameData.odds?.consensus || {};
  const homeAmericanOdds = oddsConsensus.home_odds;
  const awayAmericanOdds = oddsConsensus.away_odds;

  // Edge signals
  const homeEdge = homeAnalysis.edge || {};
  const awayEdge = awayAnalysis.edge || {};

  // Pick the more significant edge for the pill
  const homeAbsEdge = Math.abs(homeEdge.edge || 0);
  const awayAbsEdge = Math.abs(awayEdge.edge || 0);
  const mainEdge = homeAbsEdge >= awayAbsEdge ? homeEdge : awayEdge;
  const mainEdgeSignal = mainEdge.signal || 'none';
  const mainEdgeText = mainEdge.abs_edge ? `${mainEdge.abs_edge.toFixed(1)}% edge` : 'No edge';

  // Probability bar widths (0-100 for CSS)
  const homePolyWidth = homePoly ? Math.max(10, Math.min(90, homePoly)) : 50;
  const awayPolyWidth = awayPoly ? Math.max(10, Math.min(90, awayPoly)) : 50;

  // Flags
  const homeIsB2B = homeAnalysis.is_b2b || gameData.home_b2b?.is_back_to_back;
  const awayIsB2B = awayAnalysis.is_b2b || gameData.away_b2b?.is_back_to_back;
  const homeHasInjury = homeInjury.out_count > 0;
  const awayHasInjury = awayInjury.out_count > 0;

  // Build injury chips
  const injuryChips = buildInjuryChips(homeTeam, homeInjury, awayTeam, awayInjury);

  // Live score display
  const isLive = status === 'In Progress';
  const liveScoreHtml = isLive ? `
    <div class="live-score-row">
      <span class="live-score-team">${awayAbbrev}</span>
      <span class="live-score-num">${game.away_score ?? 0}</span>
      <span class="live-score-sep"> — </span>
      <span class="live-score-num">${game.home_score ?? 0}</span>
      <span class="live-score-team">${homeAbbrev}</span>
      ${game.period ? `<span class="live-period">Q${game.period}</span>` : ''}
    </div>
  ` : '';

  return `
    <div class="game-card ${alertLevel !== 'low' ? `alert-${alertLevel}` : ''}"
         onclick="openGameModal(${idx})"
         data-game-idx="${idx}">

      <!-- Header: time + status -->
      <div class="game-card-header">
        <span class="game-time">${gameTime}</span>
        <span class="game-status-badge ${statusClass}">${statusText}</span>
      </div>

      <!-- Main outcomes area: Polymarket-style -->
      <div class="game-outcomes">

        <!-- Matchup line -->
        <div class="matchup-line">
          <span class="matchup-teams">${awayAbbrev} @ ${homeAbbrev}</span>
          <div class="matchup-meta">
            ${homeIsB2B ? '<span class="flag flag-b2b">B2B</span>' : ''}
            ${awayIsB2B ? '<span class="flag flag-b2b">B2B</span>' : ''}
            ${(homeHasInjury || awayHasInjury) ? '<span class="flag flag-injury">🤕 Injuries</span>' : ''}
          </div>
        </div>

        <!-- Two outcome cards side-by-side -->
        <div class="outcome-row">

          <!-- Away team (underdog-style = "no" color usually) -->
          <div class="outcome-btn no-side"
               style="--prob-width: ${awayPolyWidth}%">
            <div class="outcome-team-name">${esc(awayTeam)}</div>
            <div class="outcome-home-tag">Away</div>
            <div class="outcome-price-row">
              ${awayPoly != null
                ? `<span class="poly-price">${awayPoly.toFixed(1)}</span><span class="poly-pct">%</span>`
                : `<span class="poly-price na">—</span>`}
            </div>
            ${awayBook != null
              ? `<div class="outcome-book-label">Books</div>
                 <div class="outcome-book-odds">${awayBook.toFixed(1)}% ${awayAmericanOdds ? `(${fmtOdds(awayAmericanOdds)})` : ''}</div>`
              : `<div class="outcome-book-odds" style="color:var(--text-muted)">No odds</div>`}
          </div>

          <!-- Home team (favorite-style = "yes" color usually) -->
          <div class="outcome-btn yes-side"
               style="--prob-width: ${homePolyWidth}%">
            <div class="outcome-team-name">${esc(homeTeam)}</div>
            <div class="outcome-home-tag">Home ★</div>
            <div class="outcome-price-row">
              ${homePoly != null
                ? `<span class="poly-price">${homePoly.toFixed(1)}</span><span class="poly-pct">%</span>`
                : `<span class="poly-price na">—</span>`}
            </div>
            ${homeBook != null
              ? `<div class="outcome-book-label">Books</div>
                 <div class="outcome-book-odds">${homeBook.toFixed(1)}% ${homeAmericanOdds ? `(${fmtOdds(homeAmericanOdds)})` : ''}</div>`
              : `<div class="outcome-book-odds" style="color:var(--text-muted)">No odds</div>`}
          </div>

        </div>

        <!-- Edge indicator -->
        <div class="edge-indicator">
          <div class="edge-pill signal-${mainEdgeSignal}">
            <span class="edge-pill-dot"></span>
            ${mainEdgeSignal !== 'none' ? mainEdgeText : 'No significant edge'}
          </div>
        </div>

      </div>

      <!-- Live score bar -->
      ${liveScoreHtml}

      <!-- Injury chips -->
      ${injuryChips ? `<div class="injury-chips">${injuryChips}</div>` : ''}

      <!-- Tap hint -->
      <div class="card-tap-hint">Tap for full breakdown →</div>
    </div>
  `;
}

function buildInjuryChips(homeTeam, homeInjury, awayTeam, awayInjury) {
  const chips = [];

  // Home team injuries
  if (homeInjury.all_injuries && homeInjury.all_injuries.length > 0) {
    homeInjury.all_injuries.slice(0, 3).forEach(inj => {
      const dotClass = inj.is_out ? 'out' : inj.is_questionable ? 'questionable' : 'probable';
      chips.push(`
        <div class="injury-chip">
          <span class="injury-chip-dot ${dotClass}"></span>
          ${esc(inj.player_name.split(' ').pop())} (${inj.status})
        </div>
      `);
    });
  }

  // Away team injuries
  if (awayInjury.all_injuries && awayInjury.all_injuries.length > 0) {
    awayInjury.all_injuries.slice(0, 3).forEach(inj => {
      const dotClass = inj.is_out ? 'out' : inj.is_questionable ? 'questionable' : 'probable';
      chips.push(`
        <div class="injury-chip">
          <span class="injury-chip-dot ${dotClass}"></span>
          ${esc(inj.player_name.split(' ').pop())} (${inj.status})
        </div>
      `);
    });
  }

  return chips.join('');
}

// ============================================================
// MODAL — Game Detail View
// ============================================================

function openGameModal(gameIdx) {
  if (!dashboardData || !dashboardData.games) return;

  const gameData = dashboardData.games[gameIdx];
  if (!gameData) return;

  renderModal(gameData);

  document.getElementById('modalOverlay').classList.remove('hidden');
  document.body.style.overflow = 'hidden';

  // Push to history so back button works
  history.pushState({ modal: true }, '');
}

function openGameByTeam(teamName) {
  if (!dashboardData || !dashboardData.games) return;

  const idx = dashboardData.games.findIndex(g => {
    const game = g.game || {};
    return game.home_team === teamName || game.away_team === teamName;
  });

  if (idx !== -1) openGameModal(idx);
}

function closeModal() {
  document.getElementById('modalOverlay').classList.add('hidden');
  document.body.style.overflow = '';
}

function renderModal(gameData) {
  const game = gameData.game || {};
  const analysis = gameData.analysis || {};
  const homeA = analysis.home || {};
  const awayA = analysis.away || {};
  const homeInjury = gameData.home_injury_summary || {};
  const awayInjury = gameData.away_injury_summary || {};
  const simulation = gameData.simulation || null;
  const homeRecord = gameData.home_record || {};
  const awayRecord = gameData.away_record || {};
  const h2h = gameData.h2h || null;
  const homeB2B = gameData.home_b2b || {};
  const awayB2B = gameData.away_b2b || {};
  const oddsData = gameData.odds || {};

  const homeTeam = game.home_team || 'Home';
  const awayTeam = game.away_team || 'Away';

  document.getElementById('modalTitle').textContent = `${awayTeam} @ ${homeTeam}`;

  let html = '';

  // ---- 1. Probability Comparison ----
  html += `
    <div class="modal-section">
      <div class="modal-section-title">📊 Odds Comparison</div>
      <div class="prob-comparison">
        ${renderProbCard(homeTeam, homeA, 'Home ★', oddsData)}
        ${renderProbCard(awayTeam, awayA, 'Away', oddsData)}
      </div>
    </div>
  `;

  // ---- 2. Head-to-Head History ----
  if (h2h) {
    html += `
      <div class="modal-section">
        <div class="modal-section-title">🔄 Head-to-Head (This Season)</div>
        ${renderH2H(h2h, homeTeam, awayTeam)}
      </div>
    `;
  }

  // ---- 3. Back-to-Back Alerts ----
  if (homeB2B.is_back_to_back || awayB2B.is_back_to_back) {
    html += `<div class="modal-section"><div class="modal-section-title">⚡ Rest & Travel</div>`;
    if (homeB2B.is_back_to_back) {
      html += `<div class="b2b-alert">⚡ ${esc(homeTeam)} is on a back-to-back (played yesterday)</div>`;
    }
    if (awayB2B.is_back_to_back) {
      html += `<div class="b2b-alert">⚡ ${esc(awayTeam)} is on a back-to-back (played yesterday)</div>`;
    }
    html += `</div>`;
  }

  // ---- 4. Projected Box Score ----
  if (simulation) {
    html += `
      <div class="modal-section">
        <div class="modal-section-title">🎯 Projected Box Score</div>
        <div class="projection-grid">
          ${renderProjection(simulation.home, homeTeam)}
          ${renderProjection(simulation.away, awayTeam)}
        </div>
        ${renderGameTotalSummary(simulation.game)}
      </div>
    `;
  }

  // ---- 5. Injury Reports ----
  html += `
    <div class="modal-section">
      <div class="modal-section-title">🤕 Injury Report</div>
      <div class="injury-section-teams">
        ${renderInjuryTeam(homeTeam, homeInjury)}
        ${renderInjuryTeam(awayTeam, awayInjury)}
      </div>
    </div>
  `;

  // ---- 6. Home/Away Records ----
  if (homeRecord.home_wins != null || awayRecord.away_wins != null) {
    html += `
      <div class="modal-section">
        <div class="modal-section-title">🏟️ Home / Away Records</div>
        <div class="records-grid">
          ${renderRecordCard(homeTeam, homeRecord, 'home')}
          ${renderRecordCard(awayTeam, awayRecord, 'away')}
        </div>
      </div>
    `;
  }

  // ---- 7. Top Players ----
  const homePlayers = gameData.home_players || [];
  const awayPlayers = gameData.away_players || [];
  if (homePlayers.length > 0 || awayPlayers.length > 0) {
    html += `
      <div class="modal-section">
        <div class="modal-section-title">👟 Key Players</div>
        ${homePlayers.length > 0 ? `
          <div style="margin-bottom:var(--space-sm)">
            <div style="font-size:12px;font-weight:700;color:var(--text-secondary);margin-bottom:4px">${esc(homeTeam)}</div>
            ${renderPlayersTable(homePlayers, homeInjury)}
          </div>
        ` : ''}
        ${awayPlayers.length > 0 ? `
          <div>
            <div style="font-size:12px;font-weight:700;color:var(--text-secondary);margin-bottom:4px">${esc(awayTeam)}</div>
            ${renderPlayersTable(awayPlayers, awayInjury)}
          </div>
        ` : ''}
      </div>
    `;
  }

  document.getElementById('modalBody').innerHTML = html;
}

function renderProbCard(teamName, teamAnalysis, label, oddsData) {
  const polyProb = teamAnalysis.poly_prob;
  const bookProb = teamAnalysis.book_prob;
  const edge = teamAnalysis.edge || {};
  const edgeVal = edge.edge;

  let edgeClass = 'edge-neu';
  let edgeSign = '';
  if (edgeVal != null) {
    if (edgeVal > 2) { edgeClass = 'edge-pos'; edgeSign = '+'; }
    else if (edgeVal < -2) { edgeClass = 'edge-neg'; }
  }

  // Get American odds from consensus
  const consensus = oddsData?.consensus || {};
  const isHome = label.includes('Home');
  const americanOdds = isHome ? consensus.home_odds : consensus.away_odds;

  return `
    <div class="prob-team-card">
      <div class="prob-team-header">${esc(teamName)} · ${label}</div>
      <div class="prob-row">
        <span class="prob-row-label">Polymarket</span>
        <span class="prob-row-val poly">${polyProb != null ? polyProb.toFixed(1) + '%' : '—'}</span>
      </div>
      <div class="prob-row">
        <span class="prob-row-label">Sportsbooks</span>
        <span class="prob-row-val book">${bookProb != null ? bookProb.toFixed(1) + '%' : '—'}</span>
      </div>
      ${americanOdds != null ? `
      <div class="prob-row">
        <span class="prob-row-label">Moneyline</span>
        <span class="prob-row-val" style="color:var(--text-secondary)">${fmtOdds(americanOdds)}</span>
      </div>` : ''}
      <div class="prob-row">
        <span class="prob-row-label">Edge</span>
        <span class="prob-row-val ${edgeClass}">${edgeVal != null ? edgeSign + edgeVal.toFixed(1) + '%' : '—'}</span>
      </div>
    </div>
  `;
}

function renderH2H(h2h, homeTeam, awayTeam) {
  const homeWins = h2h.home_wins || 0;
  const awayWins = h2h.away_wins || 0;
  const total = homeWins + awayWins;

  const homeBarPct = total > 0 ? Math.round((homeWins / total) * 100) : 50;
  const awayBarPct = 100 - homeBarPct;

  const recentGames = h2h.recent_games || [];

  return `
    <div class="h2h-card">
      <div class="h2h-header">Season series: <span class="h2h-win-count home">${homeWins}W</span> – <span class="h2h-win-count away">${awayWins}W</span></div>
      <div class="h2h-matchup-bar">
        <span class="h2h-team-label">${shortName(homeTeam)}</span>
        <div class="h2h-bar-track">
          <div class="h2h-bar-home" style="width:${homeBarPct}%"></div>
          <div class="h2h-bar-away" style="width:${awayBarPct}%"></div>
        </div>
        <span class="h2h-team-label right">${shortName(awayTeam)}</span>
      </div>
      ${recentGames.length > 0 ? `
        <div class="h2h-recent">
          <div style="font-size:10px;color:var(--text-muted);font-weight:700;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px">Recent Meetings</div>
          ${recentGames.slice(0, 5).map(g => `
            <div class="h2h-game-row">
              <span>${g.date || '—'}</span>
              <span>${esc(g.home_team || homeTeam)} ${g.home_score}–${g.away_score} ${esc(g.away_team || awayTeam)}</span>
              <span class="h2h-game-result ${g.home_won ? 'h2h-win' : 'h2h-loss'}">${g.home_won ? 'Home W' : 'Away W'}</span>
            </div>
          `).join('')}
        </div>
      ` : ''}
    </div>
  `;
}

function renderProjection(teamSim, teamName) {
  if (!teamSim) return `<div class="projection-card"><div class="projection-header">${esc(teamName)}</div><div style="padding:16px;color:var(--text-muted);font-size:12px">No projection data</div></div>`;

  const adjusted = teamSim.injury_adjusted || teamSim.full_strength;
  const fullStrength = teamSim.full_strength;
  const impact = teamSim.impact || {};

  const pts = adjusted?.team_points ?? '—';
  const ptsImpact = impact.points_impact;

  const players = adjusted?.players || [];
  const topPlayers = players
    .filter(p => !p.is_out)
    .sort((a, b) => (b.projected_minutes || 0) - (a.projected_minutes || 0))
    .slice(0, 7);

  return `
    <div class="projection-card">
      <div class="projection-header">${esc(teamName)}</div>
      <div class="projection-total">
        <span class="projection-pts">${typeof pts === 'number' ? pts.toFixed(1) : pts}</span>
        <span class="projection-pts-label">proj pts</span>
      </div>
      ${ptsImpact != null && ptsImpact < 0 ? `
        <div class="projection-impact">
          <span class="impact-label">Injury impact:</span>
          <span class="impact-value negative">${ptsImpact.toFixed(1)} pts</span>
        </div>
      ` : ''}
      <div class="stat-col-headers">
        <span>Player</span>
        <span class="stat-col">MIN</span>
        <span class="stat-col">PTS</span>
        <span class="stat-col">REB</span>
        <span class="stat-col">AST</span>
      </div>
      ${topPlayers.map(p => `
        <div class="player-row">
          <div>
            <div class="player-name">${esc(p.name || '—')}</div>
            <div class="player-pos">${p.position || ''}</div>
          </div>
          <div class="player-stat">${p.projected_minutes?.toFixed(0) ?? '—'}</div>
          <div class="player-stat highlight">${p.projected_points?.toFixed(1) ?? '—'}</div>
          <div class="player-stat">${p.projected_rebounds?.toFixed(1) ?? '—'}</div>
          <div class="player-stat">${p.projected_assists?.toFixed(1) ?? '—'}</div>
        </div>
      `).join('')}
      ${players.filter(p => p.is_out).map(p => `
        <div class="player-row is-out">
          <div>
            <div class="player-name">${esc(p.name || '—')}</div>
            <div class="player-pos" style="color:var(--red)">OUT</div>
          </div>
          <div class="player-stat">0</div>
          <div class="player-stat">—</div>
          <div class="player-stat">—</div>
          <div class="player-stat">—</div>
        </div>
      `).join('')}
    </div>
  `;
}

function renderGameTotalSummary(gameSim) {
  if (!gameSim) return '';
  return `
    <div style="display:flex;gap:8px;margin-top:8px">
      <div style="flex:1;background:var(--bg-card);border:1px solid var(--border-subtle);border-radius:var(--radius-sm);padding:10px 14px;text-align:center">
        <div style="font-size:10px;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.5px">Proj. Total (Full)</div>
        <div style="font-size:22px;font-weight:800;color:var(--poly-teal);font-family:var(--font-mono)">${gameSim.projected_total_full?.toFixed(1) ?? '—'}</div>
      </div>
      <div style="flex:1;background:var(--bg-card);border:1px solid var(--border-subtle);border-radius:var(--radius-sm);padding:10px 14px;text-align:center">
        <div style="font-size:10px;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.5px">Proj. Total (Adj.)</div>
        <div style="font-size:22px;font-weight:800;color:var(--poly-teal);font-family:var(--font-mono)">${gameSim.projected_total_adjusted?.toFixed(1) ?? '—'}</div>
        ${gameSim.total_impact < 0 ? `<div style="font-size:10px;color:var(--red);font-weight:700">${gameSim.total_impact.toFixed(1)} pts from injuries</div>` : ''}
      </div>
    </div>
  `;
}

function renderInjuryTeam(teamName, injurySummary) {
  const injuries = injurySummary.all_injuries || [];

  if (injuries.length === 0) {
    return `
      <div class="injury-team-block">
        <div class="injury-team-name">${esc(teamName)}</div>
        <div style="padding:10px 16px;font-size:12px;color:var(--green)">✓ No reported injuries</div>
      </div>
    `;
  }

  return `
    <div class="injury-team-block">
      <div class="injury-team-name">${esc(teamName)}</div>
      ${injuries.map(inj => {
        const badgeClass = inj.status === 'OUT' ? 'inj-out' :
                          inj.status === 'DOUBTFUL' ? 'inj-doubtful' :
                          inj.status === 'QUESTIONABLE' ? 'inj-questionable' : 'inj-probable';
        return `
          <div class="injury-row">
            <div class="injury-player-info">
              <div class="injury-player-name">${esc(inj.player_name)}</div>
              <div class="injury-player-desc">${esc(inj.reason || 'Not specified')}</div>
            </div>
            <span class="inj-badge ${badgeClass}">${inj.status}</span>
          </div>
        `;
      }).join('')}
    </div>
  `;
}

function renderRecordCard(teamName, record, homeOrAway) {
  if (!record || Object.keys(record).length === 0) {
    return `
      <div class="record-card">
        <div class="record-card-team">${esc(teamName)}</div>
        <div style="font-size:11px;color:var(--text-muted)">Record not available</div>
      </div>
    `;
  }

  const isHome = homeOrAway === 'home';
  const relevantWins = isHome ? record.home_wins : record.away_wins;
  const relevantLosses = isHome ? record.home_losses : record.away_losses;
  const relevantPct = isHome ? record.home_pct : record.away_pct;

  return `
    <div class="record-card">
      <div class="record-card-team">${esc(teamName)}</div>
      <div class="record-row">
        <span>${isHome ? 'Home' : 'Away'} Record</span>
        <span class="record-val">${relevantWins ?? '?'}-${relevantLosses ?? '?'}</span>
      </div>
      <div class="record-row">
        <span>${isHome ? 'Home' : 'Away'} Win%</span>
        <span class="record-val">${relevantPct != null ? relevantPct + '%' : '—'}</span>
      </div>
      <div class="record-row">
        <span>Overall Home</span>
        <span class="record-val">${record.home_wins ?? '?'}-${record.home_losses ?? '?'}</span>
      </div>
      <div class="record-row">
        <span>Overall Away</span>
        <span class="record-val">${record.away_wins ?? '?'}-${record.away_losses ?? '?'}</span>
      </div>
    </div>
  `;
}

function renderPlayersTable(players, injurySummary) {
  const injuredNames = new Set(
    (injurySummary.all_injuries || []).filter(i => i.is_out).map(i => i.player_name.toLowerCase())
  );

  return `
    <div style="background:var(--bg-card);border:1px solid var(--border-subtle);border-radius:var(--radius-md);overflow:hidden">
      <div class="stat-col-headers">
        <span>Player</span>
        <span class="stat-col">MIN</span>
        <span class="stat-col">PPG</span>
        <span class="stat-col">RPG</span>
        <span class="stat-col">APG</span>
      </div>
      ${players.map(p => {
        const isOut = injuredNames.has((p.name || '').toLowerCase());
        return `
          <div class="player-row ${isOut ? 'is-out' : ''}">
            <div>
              <div class="player-name">${esc(p.name || '—')}</div>
              <div class="player-pos">${p.position || ''} ${isOut ? '· OUT' : ''}</div>
            </div>
            <div class="player-stat">${p.minutes?.toFixed(0) ?? '—'}</div>
            <div class="player-stat highlight">${p.points?.toFixed(1) ?? '—'}</div>
            <div class="player-stat">${p.rebounds?.toFixed(1) ?? '—'}</div>
            <div class="player-stat">${p.assists?.toFixed(1) ?? '—'}</div>
          </div>
        `;
      }).join('')}
    </div>
  `;
}

// ============================================================
// VIEW TOGGLE
// ============================================================

function setView(view) {
  currentView = view;
  const container = document.getElementById('gamesContainer');

  document.getElementById('viewCards').classList.toggle('active', view === 'cards');
  document.getElementById('viewCompact').classList.toggle('active', view === 'compact');

  container?.classList.toggle('compact-view', view === 'compact');
}

// ============================================================
// SHOW STATES
// ============================================================

function showError(message) {
  document.getElementById('loadingScreen').classList.add('hidden');
  document.getElementById('mainContent').classList.add('hidden');
  document.getElementById('errorScreen').classList.remove('hidden');
  const msgEl = document.getElementById('errorMessage');
  if (msgEl) msgEl.textContent = message || 'Failed to load data. Check the terminal.';
}

function updateLastUpdated(isoString, fromCache) {
  const el = document.getElementById('lastUpdated');
  if (!el) return;

  const dot = document.getElementById('refreshDot');

  if (isoString) {
    const d = new Date(isoString);
    const mins = Math.round((Date.now() - d.getTime()) / 60000);
    el.textContent = mins < 1 ? 'Just now' : `${mins}m ago`;

    if (mins > 10 && dot) {
      dot.className = 'refresh-dot stale';
    }
  } else {
    el.textContent = fromCache ? 'Cached' : 'Updated';
  }
}

// ============================================================
// HELPER FUNCTIONS
// ============================================================

// Escape HTML to prevent XSS
function esc(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// Set inner text of an element by ID
function setEl(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

// Format American odds: -180 -> "-180", +155 -> "+155"
function fmtOdds(odds) {
  if (odds == null) return '—';
  return odds > 0 ? `+${odds}` : String(odds);
}

// Get team short name (last word of full name: "Boston Celtics" -> "Celtics")
function shortName(fullName) {
  if (!fullName) return '';
  const parts = fullName.split(' ');
  return parts[parts.length - 1];
}

// Format game time from UTC ISO string to local time
function formatGameTime(timeStr) {
  if (!timeStr) return 'TBD';

  // If it's already a formatted string (not ISO), return as-is
  if (!timeStr.includes('T') && !timeStr.includes('-')) {
    return timeStr;
  }

  try {
    const d = new Date(timeStr);
    if (isNaN(d.getTime())) return timeStr;

    return d.toLocaleTimeString('en-US', {
      hour: 'numeric',
      minute: '2-digit',
      timeZoneName: 'short'
    });
  } catch {
    return timeStr;
  }
}
