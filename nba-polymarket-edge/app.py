"""
app.py — NBA Polymarket Edge: Flask Backend
This file serves the frontend HTML and provides all the API endpoints
that the frontend JavaScript calls to get data.

Run this with: python app.py
Then open http://localhost:5000 in your browser.
"""

import os
import time
import logging
import json
from datetime import datetime, date
from flask import Flask, render_template, jsonify, request
from dotenv import load_dotenv

# Load environment variables from .env file (ODDS_API_KEY, etc.)
load_dotenv()

# Set up logging so we can see what's happening in the terminal
# This is very helpful for debugging!
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# Import our data modules
# Each module handles one data source
from data.polymarket import get_nba_markets, find_matching_market
from data.nba_stats import (
    get_todays_games,
    get_team_players_with_stats,
    get_all_player_season_stats,
    get_team_home_away_record,
    check_back_to_back,
    get_team_pace_stats,
    get_all_teams,
    get_head_to_head,
    NBA_API_AVAILABLE
)
from data.injuries import get_all_injuries, get_team_injuries, get_injury_impact_summary
from data.odds import get_nba_odds, find_matching_odds, format_american_odds
from data.simulator import run_game_simulation
from data.analyzer import analyze_game, sort_games_by_interest, generate_value_alerts

# Create the Flask app
app = Flask(__name__)

# --- Simple in-memory cache for the combined data ---
# We cache the full dashboard data to avoid hammering all APIs
_dashboard_cache = {}
DASHBOARD_CACHE_TTL = 300  # 5 minutes by default


def get_cached_dashboard():
    """Return cached dashboard data if it's still fresh."""
    cache = _dashboard_cache.get('data')
    timestamp = _dashboard_cache.get('timestamp', 0)
    if cache and (time.time() - timestamp < DASHBOARD_CACHE_TTL):
        logger.info(f"Returning cached dashboard data ({int(time.time() - timestamp)}s old)")
        return cache
    return None


def set_dashboard_cache(data):
    """Save dashboard data to the cache."""
    _dashboard_cache['data'] = data
    _dashboard_cache['timestamp'] = time.time()


# ============================================================
# MAIN ROUTE — serves the frontend HTML
# ============================================================

@app.route('/')
def index():
    """Serve the main dashboard HTML page."""
    return render_template('index.html')


# ============================================================
# API ROUTES — called by the frontend JavaScript
# ============================================================

@app.route('/api/dashboard')
def api_dashboard():
    """
    Main data endpoint — returns everything needed for the dashboard.
    Combines data from all sources: NBA schedule, Polymarket, sportsbooks, injuries.

    The frontend calls this on load and every 5 minutes.
    Response format: { games: [...], alerts: [...], last_updated: '...' }
    """
    force_refresh = request.args.get('refresh', 'false').lower() == 'true'

    # Return cached data unless refresh is forced
    if not force_refresh:
        cached = get_cached_dashboard()
        if cached:
            return jsonify({**cached, 'from_cache': True})

    logger.info("Building fresh dashboard data...")
    start_time = time.time()

    try:
        # --- Step 1: Get today's NBA games ---
        logger.info("Step 1: Fetching today's games...")
        games = get_todays_games()

        if not games:
            logger.warning("No games found for today")
            return jsonify({
                'games': [],
                'alerts': [],
                'message': 'No NBA games scheduled today',
                'last_updated': datetime.now().isoformat(),
                'stats': {'game_count': 0}
            })

        logger.info(f"Found {len(games)} games today")

        # --- Step 2: Fetch all supporting data in parallel (sequentially for safety) ---
        logger.info("Step 2: Fetching Polymarket markets...")
        polymarket_markets = get_nba_markets()
        logger.info(f"Got {len(polymarket_markets)} Polymarket markets")

        logger.info("Step 3: Fetching sportsbook odds...")
        sportsbook_odds = get_nba_odds()
        logger.info(f"Got odds for {len(sportsbook_odds)} games")

        logger.info("Step 4: Fetching injury reports...")
        all_injuries = get_all_injuries()
        logger.info(f"Got injuries for {len(all_injuries)} teams")

        logger.info("Step 5: Fetching player season stats...")
        all_player_stats = get_all_player_season_stats()
        logger.info(f"Got stats for {len(all_player_stats)} players")

        # --- Step 3: Build the full analysis for each game ---
        analyzed_games = []

        for game in games:
            home_team = game.get('home_team', '')
            away_team = game.get('away_team', '')
            home_id = game.get('home_team_id')
            away_id = game.get('away_team_id')

            logger.info(f"Analyzing: {away_team} @ {home_team}")

            try:
                # Match this game to Polymarket and sportsbook data
                poly_market = find_matching_market(home_team, away_team, polymarket_markets)
                odds = find_matching_odds(home_team, away_team, sportsbook_odds)

                # Get injury reports for both teams
                home_injuries = get_team_injuries(home_team, all_injuries)
                away_injuries = get_team_injuries(away_team, all_injuries)

                # Get injury summary for both teams
                home_injury_summary = get_injury_impact_summary(home_team, all_injuries)
                away_injury_summary = get_injury_impact_summary(away_team, all_injuries)

                # Get home/away records
                home_record = {}
                away_record = {}
                if home_id:
                    home_record = get_team_home_away_record(home_id)
                if away_id:
                    away_record = get_team_home_away_record(away_id)

                # Check back-to-back status
                home_b2b_info = {}
                away_b2b_info = {}
                if home_id:
                    home_b2b_info = check_back_to_back(home_id)
                if away_id:
                    away_b2b_info = check_back_to_back(away_id)

                # Get head-to-head history between these teams
                h2h_data = {}
                if home_id and away_id:
                    h2h_data = get_head_to_head(home_id, away_id)

                # Get players with stats for simulation
                simulation = None
                home_players_data = []
                away_players_data = []

                if home_id and away_id and all_player_stats:
                    home_players_data = get_team_players_with_stats(home_id, all_player_stats)
                    away_players_data = get_team_players_with_stats(away_id, all_player_stats)

                    if home_players_data and away_players_data:
                        simulation = run_game_simulation(
                            home_players_data,
                            away_players_data,
                            home_injuries,
                            away_injuries
                        )

                # Run the full analysis
                game_analysis = analyze_game(
                    game=game,
                    polymarket_data=poly_market,
                    odds_data=odds,
                    simulation=simulation,
                    home_b2b=home_b2b_info.get('is_back_to_back', False),
                    away_b2b=away_b2b_info.get('is_back_to_back', False),
                )

                # Add extra display data to the analysis
                game_analysis['h2h'] = h2h_data
                game_analysis['home_injury_summary'] = home_injury_summary
                game_analysis['away_injury_summary'] = away_injury_summary
                game_analysis['home_record'] = home_record
                game_analysis['away_record'] = away_record
                game_analysis['home_b2b'] = home_b2b_info
                game_analysis['away_b2b'] = away_b2b_info
                game_analysis['home_players'] = home_players_data[:8]  # Top 8 for display
                game_analysis['away_players'] = away_players_data[:8]

                analyzed_games.append(game_analysis)

            except Exception as e:
                logger.error(f"Error analyzing game {home_team} vs {away_team}: {e}", exc_info=True)
                # Still include the game with basic info, even if analysis failed
                analyzed_games.append({
                    'game': game,
                    'analysis': {'error': str(e)},
                    'home_injury_summary': {'has_injuries': False},
                    'away_injury_summary': {'has_injuries': False},
                })

        # --- Step 4: Sort by interest and generate alerts ---
        analyzed_games = sort_games_by_interest(analyzed_games)
        value_alerts = generate_value_alerts(analyzed_games)

        # --- Step 5: Build the final response ---
        elapsed = round(time.time() - start_time, 2)
        logger.info(f"Dashboard built in {elapsed}s: {len(analyzed_games)} games, {len(value_alerts)} alerts")

        result = {
            'games': analyzed_games,
            'alerts': value_alerts,
            'last_updated': datetime.now().isoformat(),
            'from_cache': False,
            'stats': {
                'game_count': len(games),
                'polymarket_markets': len(polymarket_markets),
                'sportsbook_games': len(sportsbook_odds),
                'injured_teams': len(all_injuries),
                'value_alerts': len(value_alerts),
                'build_time_seconds': elapsed,
            }
        }

        # Cache the result
        set_dashboard_cache(result)
        return jsonify(result)

    except Exception as e:
        logger.error(f"Dashboard build failed: {e}", exc_info=True)
        return jsonify({
            'error': str(e),
            'message': 'Failed to load dashboard data. Check the terminal for details.',
            'games': [],
            'alerts': [],
        }), 500


@app.route('/api/game/<game_id>')
def api_game_detail(game_id: str):
    """
    Get detailed data for a specific game.
    Called when user taps/clicks a game card.
    """
    # Get the cached dashboard data first
    cached = get_cached_dashboard()
    if cached:
        games = cached.get('games', [])
        for game_data in games:
            g = game_data.get('game', {})
            if g.get('game_id') == game_id:
                return jsonify(game_data)

    return jsonify({'error': 'Game not found'}), 404


@app.route('/api/injuries')
def api_injuries():
    """
    Get the full injury report for all teams.
    """
    try:
        injuries = get_all_injuries()
        return jsonify({
            'injuries': injuries,
            'last_updated': datetime.now().isoformat(),
            'team_count': len(injuries),
        })
    except Exception as e:
        logger.error(f"Error fetching injuries: {e}")
        return jsonify({'error': str(e), 'injuries': {}}), 500


@app.route('/api/status')
def api_status():
    """
    Health check endpoint. Shows what APIs are working.
    Useful for debugging.
    """
    status = {
        'nba_api': NBA_API_AVAILABLE,
        'odds_api_key': bool(os.environ.get('ODDS_API_KEY')),
        'cached_dashboard': get_cached_dashboard() is not None,
        'server_time': datetime.now().isoformat(),
        'date': str(date.today()),
    }

    # Try to import optional packages
    try:
        import nbainjuries
        status['nbainjuries'] = True
    except ImportError:
        status['nbainjuries'] = False

    return jsonify(status)


@app.route('/api/convert-odds')
def api_convert_odds():
    """
    Utility endpoint: convert between odds formats.
    Query params: american=-180, probability=0.60, polymarket=0.60
    """
    from data.odds import american_odds_to_probability, probability_to_american_odds

    american = request.args.get('american')
    probability = request.args.get('probability')

    result = {}

    if american:
        try:
            odds = int(american)
            prob = american_odds_to_probability(odds)
            result = {
                'american': odds,
                'decimal': round(1 / prob, 3) if prob else None,
                'probability': round(prob * 100, 2) if prob else None,
                'polymarket_price': round(prob, 4) if prob else None,
            }
        except ValueError:
            return jsonify({'error': 'Invalid American odds format'}), 400

    elif probability:
        try:
            prob = float(probability)
            if prob > 1:
                prob = prob / 100  # Convert from percentage to decimal
            american_odds = probability_to_american_odds(prob)
            result = {
                'probability': round(prob * 100, 2),
                'american': american_odds,
                'decimal': round(1 / prob, 3) if prob else None,
                'polymarket_price': round(prob, 4) if prob else None,
                'formatted': format_american_odds(american_odds),
            }
        except ValueError:
            return jsonify({'error': 'Invalid probability format'}), 400

    else:
        return jsonify({'error': 'Provide american or probability parameter'}), 400

    return jsonify(result)


# ============================================================
# Error handlers
# ============================================================

@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Endpoint not found'}), 404


@app.errorhandler(500)
def server_error(e):
    return jsonify({'error': 'Internal server error'}), 500


# ============================================================
# Run the app
# ============================================================

if __name__ == '__main__':
    print("\n" + "=" * 60)
    print("   NBA Polymarket Edge — Starting Up")
    print("=" * 60)

    # Check what's available
    print(f"\n✓ nba_api: {'Available' if NBA_API_AVAILABLE else '❌ Not installed (pip install nba_api)'}")

    try:
        import nbainjuries
        print("✓ nbainjuries: Available")
    except ImportError:
        print("❌ nbainjuries: Not installed (pip install nbainjuries)")

    odds_key = os.environ.get('ODDS_API_KEY', '')
    print(f"✓ Odds API Key: {'Set' if odds_key else '❌ Not set (add to .env file)'}")

    print(f"\n→ Open http://localhost:5000 in your browser")
    print(f"→ Press Ctrl+C to stop the server")
    print("=" * 60 + "\n")

    # Start the Flask development server
    # debug=True means the server restarts automatically when you change code
    # host='0.0.0.0' makes it accessible from other devices on your network
    app.run(
        debug=True,
        host='0.0.0.0',
        port=5000,
        use_reloader=True
    )
