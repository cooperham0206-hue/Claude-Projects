"""
nba_stats.py — NBA Data Wrapper
Uses the nba_api Python package to pull game schedules, player stats,
rosters, and more directly from NBA.com (free, no auth needed).

IMPORTANT: NBA.com rate-limits requests, so we:
1. Add small delays between API calls (0.5-1 second)
2. Cache results in memory so we don't re-fetch the same data
"""

import time
import logging
from datetime import datetime, date, timedelta
from functools import lru_cache
import json

logger = logging.getLogger(__name__)

# Try to import nba_api — if not installed, provide helpful error
try:
    from nba_api.stats.endpoints import (
        scoreboardv2,          # Today's games and live scores
        playergamelogs,        # Player game-by-game logs
        leaguegamefinder,      # Find games by team/date
        commonteamroster,      # Team roster
        playercareerstats,     # Player career averages
        leaguedashplayerstats, # All players' season averages
        teamgamelogs,          # Team game logs (for home/away records)
        leaguedashteamstats,   # Team season stats (pace, etc.)
    )
    from nba_api.stats.static import teams as nba_teams_static
    from nba_api.stats.static import players as nba_players_static
    from nba_api.live.nba.endpoints import scoreboard as live_scoreboard
    NBA_API_AVAILABLE = True
    logger.info("nba_api loaded successfully")
except ImportError:
    NBA_API_AVAILABLE = False
    logger.error("nba_api not installed! Run: pip install nba_api")

# --- Simple in-memory cache ---
# Stores: { cache_key: (data, timestamp) }
_cache = {}

def _get_cache(key: str, ttl_seconds: int = 300) -> object | None:
    """Return cached data if it exists and hasn't expired."""
    if key in _cache:
        data, timestamp = _cache[key]
        if time.time() - timestamp < ttl_seconds:
            logger.debug(f"Cache hit: {key}")
            return data
    return None

def _set_cache(key: str, data: object) -> None:
    """Store data in the cache with current timestamp."""
    _cache[key] = (data, time.time())

def _delay():
    """Small delay to avoid rate-limiting by NBA.com."""
    time.sleep(0.6)


# NBA team ID to abbreviation and full name mapping
# We use this to cross-reference team IDs from different endpoints
def get_all_teams() -> list[dict]:
    """
    Get a list of all NBA teams with their IDs, abbreviations, and full names.
    This is static data that rarely changes.
    """
    if not NBA_API_AVAILABLE:
        return []

    cache_key = "all_teams"
    cached = _get_cache(cache_key, ttl_seconds=3600)  # Cache for 1 hour
    if cached:
        return cached

    try:
        all_teams = nba_teams_static.get_teams()
        # Each team looks like: {'id': 1610612737, 'full_name': 'Atlanta Hawks',
        #                        'abbreviation': 'ATL', 'nickname': 'Hawks',
        #                        'city': 'Atlanta', 'state': 'Georgia', 'year_founded': 1949}
        _set_cache(cache_key, all_teams)
        return all_teams
    except Exception as e:
        logger.error(f"Error fetching team list: {e}")
        return []


def get_team_id(team_name_or_abbrev: str) -> int | None:
    """
    Look up a team's NBA.com ID by name or abbreviation.
    Example: 'Boston Celtics' or 'BOS' -> 1610612738
    """
    all_teams = get_all_teams()
    search = team_name_or_abbrev.upper()

    for team in all_teams:
        if (team['abbreviation'].upper() == search or
            team['full_name'].upper() == team_name_or_abbrev.upper() or
            team['nickname'].upper() == team_name_or_abbrev.upper() or
            team['city'].upper() in team_name_or_abbrev.upper()):
            return team['id']

    return None


def get_todays_games() -> list[dict]:
    """
    Get today's NBA games using the live scoreboard endpoint.
    Returns a list of game dicts with team names, scores, and status.

    Each game dict:
    {
        'game_id': '0022301234',
        'home_team': 'Boston Celtics',
        'away_team': 'Miami Heat',
        'home_abbrev': 'BOS',
        'away_abbrev': 'MIA',
        'home_team_id': 1610612738,
        'away_team_id': 1610612748,
        'game_time': '7:30 PM ET',
        'game_time_utc': '2024-01-15T00:30:00Z',
        'status': 'Scheduled',  # or 'In Progress', 'Final'
        'home_score': 0,
        'away_score': 0,
        'period': 0,
        'game_clock': '',
    }
    """
    cache_key = f"todays_games_{date.today()}"
    cached = _get_cache(cache_key, ttl_seconds=60)  # Refresh every 60 seconds for live scores
    if cached:
        return cached

    if not NBA_API_AVAILABLE:
        logger.warning("nba_api not available, returning empty games list")
        return []

    try:
        logger.info("Fetching today's NBA games from live scoreboard...")
        _delay()

        # Use the live scoreboard for real-time data
        board = live_scoreboard.ScoreBoard()
        games_data = board.get_dict()

        games = []
        game_list = games_data.get('scoreboard', {}).get('games', [])

        for game in game_list:
            home = game.get('homeTeam', {})
            away = game.get('awayTeam', {})

            # Get full team names from static data
            home_full = _get_full_team_name(home.get('teamId'))
            away_full = _get_full_team_name(away.get('teamId'))

            # Parse game status
            status_text = game.get('gameStatusText', 'TBD').strip()
            game_status = game.get('gameStatus', 1)  # 1=scheduled, 2=live, 3=final

            if game_status == 1:
                status = 'Scheduled'
            elif game_status == 2:
                status = 'In Progress'
            elif game_status == 3:
                status = 'Final'
            else:
                status = status_text

            game_dict = {
                'game_id': game.get('gameId', ''),
                'home_team': home_full or home.get('teamName', ''),
                'away_team': away_full or away.get('teamName', ''),
                'home_abbrev': home.get('teamTricode', ''),
                'away_abbrev': away.get('teamTricode', ''),
                'home_team_id': home.get('teamId'),
                'away_team_id': away.get('teamId'),
                'home_city': home.get('teamCity', ''),
                'away_city': away.get('teamCity', ''),
                'game_time': status_text,
                'game_time_utc': game.get('gameTimeUTC', ''),
                'status': status,
                'home_score': home.get('score', 0),
                'away_score': away.get('score', 0),
                'period': game.get('period', 0),
                'game_clock': game.get('gameClock', ''),
                'arena': game.get('arenaName', ''),
                'city': game.get('arenaCity', ''),
            }
            games.append(game_dict)

        logger.info(f"Found {len(games)} games today")
        _set_cache(cache_key, games)
        return games

    except Exception as e:
        logger.error(f"Error fetching today's games: {e}", exc_info=True)
        # Try fallback method using scoreboard v2
        return _get_todays_games_fallback()


def _get_todays_games_fallback() -> list[dict]:
    """
    Fallback method to get today's games using the scoreboardv2 endpoint.
    Used if the live endpoint fails.
    """
    try:
        logger.info("Trying fallback scoreboard endpoint...")
        _delay()

        today_str = date.today().strftime('%Y-%m-%d')
        board = scoreboardv2.ScoreboardV2(game_date=today_str)
        game_header = board.game_header.get_dict()
        line_score = board.line_score.get_dict()

        games = []

        # game_header has one row per game
        headers = game_header.get('headers', [])
        rows = game_header.get('data', [])

        for row in rows:
            game = dict(zip(headers, row))
            game_id = game.get('GAME_ID', '')

            # Find scores from line_score
            home_score = 0
            away_score = 0

            games.append({
                'game_id': game_id,
                'home_team': game.get('HOME_TEAM_NAME', ''),
                'away_team': game.get('VISITOR_TEAM_NAME', ''),
                'home_abbrev': '',
                'away_abbrev': '',
                'home_team_id': game.get('HOME_TEAM_ID'),
                'away_team_id': game.get('VISITOR_TEAM_ID'),
                'game_time': game.get('GAME_STATUS_TEXT', ''),
                'game_time_utc': '',
                'status': 'Scheduled',
                'home_score': home_score,
                'away_score': away_score,
                'period': 0,
                'game_clock': '',
            })

        return games

    except Exception as e:
        logger.error(f"Fallback scoreboard also failed: {e}")
        return []


def _get_full_team_name(team_id: int) -> str | None:
    """Look up a team's full name by its NBA.com team ID."""
    all_teams = get_all_teams()
    for team in all_teams:
        if team['id'] == team_id:
            return team['full_name']
    return None


def get_team_roster(team_id: int) -> list[dict]:
    """
    Get the current roster for a team.
    Returns a list of player dicts with IDs, names, and positions.
    """
    cache_key = f"roster_{team_id}"
    cached = _get_cache(cache_key, ttl_seconds=3600)  # Rosters change infrequently
    if cached:
        return cached

    if not NBA_API_AVAILABLE:
        return []

    try:
        logger.info(f"Fetching roster for team {team_id}...")
        _delay()

        roster = commonteamroster.CommonTeamRoster(team_id=team_id)
        roster_data = roster.common_team_roster.get_dict()

        players = []
        headers = roster_data.get('headers', [])
        rows = roster_data.get('data', [])

        for row in rows:
            player = dict(zip(headers, row))
            players.append({
                'player_id': player.get('PLAYER_ID'),
                'name': player.get('PLAYER', ''),
                'position': player.get('POSITION', ''),
                'jersey': player.get('NUM', ''),
                'how_acquired': player.get('HOW_ACQUIRED', ''),
            })

        _set_cache(cache_key, players)
        return players

    except Exception as e:
        logger.error(f"Error fetching roster for team {team_id}: {e}")
        return []


def get_all_player_season_stats() -> dict:
    """
    Fetch season averages for ALL players in the league at once.
    This is more efficient than fetching per-player.

    Returns a dict: { player_id: {stats_dict} }
    """
    cache_key = f"all_player_stats_{date.today()}"
    cached = _get_cache(cache_key, ttl_seconds=3600)  # Cache for 1 hour
    if cached:
        return cached

    if not NBA_API_AVAILABLE:
        return {}

    try:
        logger.info("Fetching season stats for all players...")
        _delay()

        # Get per-game stats for all players this season
        stats = leaguedashplayerstats.LeagueDashPlayerStats(
            per_mode_simple='PerGame',
            season_type_all_star='Regular Season'
        )
        stats_data = stats.league_dash_player_stats.get_dict()

        player_stats = {}
        headers = stats_data.get('headers', [])
        rows = stats_data.get('data', [])

        for row in rows:
            p = dict(zip(headers, row))
            player_id = p.get('PLAYER_ID')
            if player_id:
                player_stats[player_id] = {
                    'player_id': player_id,
                    'name': p.get('PLAYER_NAME', ''),
                    'team_abbrev': p.get('TEAM_ABBREVIATION', ''),
                    'team_id': p.get('TEAM_ID'),
                    'games_played': p.get('GP', 0),
                    'minutes': round(float(p.get('MIN', 0) or 0), 1),
                    'points': round(float(p.get('PTS', 0) or 0), 1),
                    'rebounds': round(float(p.get('REB', 0) or 0), 1),
                    'assists': round(float(p.get('AST', 0) or 0), 1),
                    'steals': round(float(p.get('STL', 0) or 0), 1),
                    'blocks': round(float(p.get('BLK', 0) or 0), 1),
                    'turnovers': round(float(p.get('TOV', 0) or 0), 1),
                    'fg_pct': round(float(p.get('FG_PCT', 0) or 0) * 100, 1),
                    'fg3_pct': round(float(p.get('FG3_PCT', 0) or 0) * 100, 1),
                    'ft_pct': round(float(p.get('FT_PCT', 0) or 0) * 100, 1),
                    'plus_minus': round(float(p.get('PLUS_MINUS', 0) or 0), 1),
                }

        logger.info(f"Got stats for {len(player_stats)} players")
        _set_cache(cache_key, player_stats)
        return player_stats

    except Exception as e:
        logger.error(f"Error fetching all player stats: {e}", exc_info=True)
        return {}


def get_team_players_with_stats(team_id: int, all_player_stats: dict = None) -> list[dict]:
    """
    Get the top players on a team with their season averages.
    Combines roster data with season stats.

    Returns list of player dicts sorted by minutes played (starters first).
    """
    # Get roster
    roster = get_team_roster(team_id)

    # Get stats (use provided dict or fetch fresh)
    if all_player_stats is None:
        all_player_stats = get_all_player_season_stats()

    players_with_stats = []
    for player in roster:
        pid = player.get('player_id')
        if pid and pid in all_player_stats:
            stats = all_player_stats[pid]
            # Only include players who have actually played this season
            if stats.get('games_played', 0) > 0:
                merged = {**player, **stats}
                players_with_stats.append(merged)

    # Sort by minutes (highest first = starters)
    players_with_stats.sort(key=lambda p: p.get('minutes', 0), reverse=True)

    # Return top 13 (typical active roster)
    return players_with_stats[:13]


def get_team_home_away_record(team_id: int) -> dict:
    """
    Calculate a team's home and away record this season.
    Returns: {'home_wins': 20, 'home_losses': 10, 'away_wins': 15, 'away_losses': 15}
    """
    cache_key = f"home_away_record_{team_id}_{date.today()}"
    cached = _get_cache(cache_key, ttl_seconds=3600)
    if cached:
        return cached

    if not NBA_API_AVAILABLE:
        return {}

    try:
        logger.info(f"Fetching game logs for team {team_id}...")
        _delay()

        logs = teamgamelogs.TeamGameLogs(team_id_nullable=team_id)
        logs_data = logs.team_game_logs.get_dict()

        headers = logs_data.get('headers', [])
        rows = logs_data.get('data', [])

        home_wins = home_losses = away_wins = away_losses = 0

        for row in rows:
            game = dict(zip(headers, row))
            matchup = game.get('MATCHUP', '')
            wl = game.get('WL', '')

            # Matchup format: "BOS vs. MIA" (home) or "BOS @ MIA" (away)
            is_home = 'vs.' in matchup
            is_win = wl == 'W'

            if is_home:
                if is_win:
                    home_wins += 1
                else:
                    home_losses += 1
            else:
                if is_win:
                    away_wins += 1
                else:
                    away_losses += 1

        result = {
            'home_wins': home_wins,
            'home_losses': home_losses,
            'away_wins': away_wins,
            'away_losses': away_losses,
            'home_pct': round(home_wins / max(home_wins + home_losses, 1) * 100, 1),
            'away_pct': round(away_wins / max(away_wins + away_losses, 1) * 100, 1),
        }

        _set_cache(cache_key, result)
        return result

    except Exception as e:
        logger.error(f"Error fetching home/away record for team {team_id}: {e}")
        return {}


def check_back_to_back(team_id: int) -> dict:
    """
    Check if a team played yesterday (back-to-back situation).
    Also checks if they play tomorrow (part of a stretch).

    Returns: {'is_back_to_back': bool, 'played_yesterday': bool, 'plays_tomorrow': bool}
    """
    cache_key = f"b2b_{team_id}_{date.today()}"
    cached = _get_cache(cache_key, ttl_seconds=3600)
    if cached:
        return cached

    if not NBA_API_AVAILABLE:
        return {'is_back_to_back': False, 'played_yesterday': False, 'plays_tomorrow': False}

    try:
        _delay()

        # Get recent games
        today = date.today()
        yesterday = (today - timedelta(days=1)).strftime('%Y-%m-%d')
        tomorrow = (today + timedelta(days=1)).strftime('%Y-%m-%d')

        logs = teamgamelogs.TeamGameLogs(
            team_id_nullable=team_id,
            date_from_nullable=yesterday,
            date_to_nullable=tomorrow
        )
        logs_data = logs.team_game_logs.get_dict()

        headers = logs_data.get('headers', [])
        rows = logs_data.get('data', [])

        played_yesterday = False
        plays_tomorrow = False

        for row in rows:
            game = dict(zip(headers, row))
            game_date = game.get('GAME_DATE', '')
            if yesterday in game_date:
                played_yesterday = True
            if tomorrow in game_date:
                plays_tomorrow = True

        result = {
            'is_back_to_back': played_yesterday,
            'played_yesterday': played_yesterday,
            'plays_tomorrow': plays_tomorrow,
        }

        _set_cache(cache_key, result)
        return result

    except Exception as e:
        logger.error(f"Error checking back-to-back for team {team_id}: {e}")
        return {'is_back_to_back': False, 'played_yesterday': False, 'plays_tomorrow': False}


def get_team_pace_stats() -> dict:
    """
    Get pace stats (possessions per game) for all teams.
    High pace = more possessions = higher scoring totals.
    Returns dict: { team_id: {'pace': 100.5, 'off_rating': 115.0, ...} }
    """
    cache_key = f"team_pace_{date.today()}"
    cached = _get_cache(cache_key, ttl_seconds=3600)
    if cached:
        return cached

    if not NBA_API_AVAILABLE:
        return {}

    try:
        logger.info("Fetching team pace stats...")
        _delay()

        stats = leaguedashteamstats.LeagueDashTeamStats(
            per_mode_simple='PerGame',
            measure_type_detailed_defense='Advanced'
        )
        stats_data = stats.league_dash_team_stats.get_dict()

        pace_data = {}
        headers = stats_data.get('headers', [])
        rows = stats_data.get('data', [])

        for row in rows:
            team = dict(zip(headers, row))
            team_id = team.get('TEAM_ID')
            if team_id:
                pace_data[team_id] = {
                    'team_name': team.get('TEAM_NAME', ''),
                    'pace': round(float(team.get('PACE', 0) or 0), 1),
                    'off_rating': round(float(team.get('OFF_RATING', 0) or 0), 1),
                    'def_rating': round(float(team.get('DEF_RATING', 0) or 0), 1),
                    'net_rating': round(float(team.get('NET_RATING', 0) or 0), 1),
                }

        _set_cache(cache_key, pace_data)
        return pace_data

    except Exception as e:
        logger.error(f"Error fetching pace stats: {e}")
        return {}


def get_head_to_head(team1_id: int, team2_id: int, num_seasons: int = 2) -> dict:
    """
    Get head-to-head matchup history between two teams.
    Looks at games from the current and previous season.

    Returns:
    {
        'home_wins': 3,           # How many times team1 won at home vs team2
        'away_wins': 2,           # How many times team2 won
        'recent_games': [         # Most recent meetings
            {
                'date': '2024-01-10',
                'home_team': 'Boston Celtics',
                'away_team': 'Miami Heat',
                'home_score': 112,
                'away_score': 98,
                'home_won': True,
            },
            ...
        ]
    }
    """
    cache_key = f"h2h_{team1_id}_{team2_id}"
    cached = _get_cache(cache_key, ttl_seconds=3600)
    if cached:
        return cached

    if not NBA_API_AVAILABLE:
        return {}

    try:
        logger.info(f"Fetching H2H history for teams {team1_id} vs {team2_id}...")
        _delay()

        # Use LeagueGameFinder to get games between these two teams
        finder = leaguegamefinder.LeagueGameFinder(
            team_id_nullable=team1_id,
            vs_team_id_nullable=team2_id,
            season_type_nullable='Regular Season'
        )
        data = finder.league_game_finder_stats.get_dict()

        headers = data.get('headers', [])
        rows = data.get('data', [])

        team1_wins = 0
        team1_losses = 0
        recent_games = []

        for row in rows:
            game = dict(zip(headers, row))
            wl = game.get('WL', '')
            matchup = game.get('MATCHUP', '')
            game_date = game.get('GAME_DATE', '')
            pts = game.get('PTS', 0)
            plus_minus = game.get('PLUS_MINUS', 0)

            is_win = wl == 'W'
            is_home = 'vs.' in matchup

            if is_win:
                team1_wins += 1
            else:
                team1_losses += 1

            # Build a recent game entry
            # We need to reconstruct home/away and scores
            if plus_minus is not None and pts is not None:
                try:
                    home_score = int(pts) if is_home else int(pts) - int(plus_minus or 0)
                    away_score = int(pts) - int(plus_minus or 0) if is_home else int(pts)
                    home_team = _get_full_team_name(team1_id) if is_home else _get_full_team_name(team2_id)
                    away_team = _get_full_team_name(team2_id) if is_home else _get_full_team_name(team1_id)

                    recent_games.append({
                        'date': game_date,
                        'home_team': home_team,
                        'away_team': away_team,
                        'home_score': home_score,
                        'away_score': away_score,
                        'home_won': is_win if is_home else not is_win,
                    })
                except (TypeError, ValueError):
                    pass

        # Sort by date, most recent first
        recent_games.sort(key=lambda g: g.get('date', ''), reverse=True)

        result = {
            'home_wins': team1_wins,    # team1's wins in this matchup
            'away_wins': team1_losses,  # team2's wins (team1's losses)
            'recent_games': recent_games[:10],  # Last 10 meetings
            'total_games': team1_wins + team1_losses,
        }

        _set_cache(cache_key, result)
        return result

    except Exception as e:
        logger.error(f"Error fetching H2H history: {e}")
        return {}


# Quick test when run directly
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    print("Testing NBA API...")

    if not NBA_API_AVAILABLE:
        print("ERROR: nba_api not installed! Run: pip install nba_api")
        exit(1)

    games = get_todays_games()
    print(f"\nToday's games ({len(games)}):")
    for g in games:
        print(f"  {g['away_team']} @ {g['home_team']} — {g['game_time']}")
