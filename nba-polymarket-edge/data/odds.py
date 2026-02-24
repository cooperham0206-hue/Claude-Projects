"""
odds.py — The Odds API Client
Fetches moneyline odds from major sportsbooks (DraftKings, FanDuel, BetMGM, etc.)

IMPORTANT: The free tier only has 500 requests/month!
We cache responses for 15 minutes to stay well within the limit.
Don't call this on every page refresh.

American odds format:
  +150 means bet $100 to win $150 (underdog)
  -200 means bet $200 to win $100 (favorite)
"""

import os
import time
import logging
import requests
from datetime import date, datetime

logger = logging.getLogger(__name__)

# The Odds API configuration
ODDS_API_BASE_URL = "https://api.the-odds-api.com/v4"
NBA_SPORT_KEY = "basketball_nba"

# --- In-memory cache (shared with other modules) ---
_cache = {}

def _get_cache(key: str, ttl_seconds: int = 900):  # Default 15-minute cache
    if key in _cache:
        data, timestamp = _cache[key]
        if time.time() - timestamp < ttl_seconds:
            logger.debug(f"Cache hit: {key}")
            return data
    return None

def _set_cache(key: str, data):
    _cache[key] = (data, time.time())

def _get_api_key() -> str | None:
    """Get the API key from environment variable."""
    key = os.environ.get('ODDS_API_KEY', '')
    if not key:
        logger.warning("ODDS_API_KEY not set in environment!")
    return key or None


def american_odds_to_probability(odds: int) -> float:
    """
    Convert American odds to implied probability (0-1 scale).

    Examples:
      +150 → 0.40 (40% implied probability)
      -200 → 0.667 (66.7% implied probability)
      -110 → 0.524 (52.4% — typical juice/vig)
    """
    if odds is None:
        return None

    try:
        odds = int(odds)
        if odds > 0:
            # Underdog: +150 → 100 / (150 + 100) = 0.40
            return 100 / (odds + 100)
        else:
            # Favorite: -200 → 200 / (200 + 100) = 0.667
            return abs(odds) / (abs(odds) + 100)
    except (ValueError, ZeroDivisionError):
        return None


def probability_to_american_odds(prob: float) -> int:
    """
    Convert probability (0-1) to American odds format.

    Examples:
      0.60 → -150
      0.40 → +150
    """
    if prob is None or prob <= 0 or prob >= 1:
        return None

    try:
        if prob >= 0.5:
            # Favorite (negative odds): -prob/(1-prob) × 100
            return round(-(prob / (1 - prob)) * 100)
        else:
            # Underdog (positive odds): (1-prob)/prob × 100
            return round(((1 - prob) / prob) * 100)
    except ZeroDivisionError:
        return None


def get_nba_odds() -> list[dict]:
    """
    Fetch moneyline odds for all upcoming NBA games.

    Returns a list of game odds dicts:
    [
        {
            'game_id': 'abc123',
            'home_team': 'Boston Celtics',
            'away_team': 'Miami Heat',
            'game_time': '2024-01-15T00:30:00Z',
            'bookmakers': {
                'draftkings': {'home_odds': -180, 'away_odds': +155},
                'fanduel': {'home_odds': -175, 'away_odds': +150},
                ...
            },
            'consensus': {
                'home_odds': -177,           # Average across books
                'away_odds': +152,
                'home_prob': 0.639,          # Implied probability
                'away_prob': 0.397,
                'home_prob_no_vig': 0.617,  # Adjusted for vig
                'away_prob_no_vig': 0.383,
            }
        },
        ...
    ]
    """
    # Cache for 15 minutes to preserve API quota
    cache_key = f"nba_odds_{date.today()}"
    cached = _get_cache(cache_key, ttl_seconds=900)
    if cached:
        return cached

    api_key = _get_api_key()
    if not api_key:
        logger.warning("No ODDS_API_KEY — returning empty odds data")
        return []

    try:
        logger.info("Fetching NBA odds from The Odds API...")

        url = f"{ODDS_API_BASE_URL}/sports/{NBA_SPORT_KEY}/odds"
        params = {
            'apiKey': api_key,
            'regions': 'us',              # US sportsbooks
            'markets': 'h2h',             # Head-to-head (moneyline)
            'oddsFormat': 'american',     # American odds format
            'dateFormat': 'iso',
        }

        response = requests.get(url, params=params, timeout=15)

        # Check remaining API calls from response headers
        remaining = response.headers.get('x-requests-remaining', 'unknown')
        used = response.headers.get('x-requests-used', 'unknown')
        logger.info(f"Odds API: {remaining} requests remaining (used: {used})")

        response.raise_for_status()
        raw_games = response.json()

        games = []
        for game in raw_games:
            parsed = _parse_odds_game(game)
            if parsed:
                games.append(parsed)

        logger.info(f"Got odds for {len(games)} NBA games")
        _set_cache(cache_key, games)
        return games

    except requests.exceptions.RequestException as e:
        logger.error(f"Network error fetching odds: {e}")
        return []
    except Exception as e:
        logger.error(f"Error fetching odds: {e}", exc_info=True)
        return []


def _parse_odds_game(game: dict) -> dict | None:
    """Parse a raw game from The Odds API into our standard format."""
    try:
        home_team = game.get('home_team', '')
        away_team = game.get('away_team', '')
        game_time = game.get('commence_time', '')

        bookmakers_data = {}
        all_home_odds = []
        all_away_odds = []

        for bookmaker in game.get('bookmakers', []):
            book_name = bookmaker.get('key', '').lower()
            # Only include major US books
            if book_name not in ['draftkings', 'fanduel', 'betmgm', 'caesars', 'pointsbet', 'bovada', 'williamhill_us']:
                continue

            for market in bookmaker.get('markets', []):
                if market.get('key') != 'h2h':
                    continue

                home_odds = None
                away_odds = None

                for outcome in market.get('outcomes', []):
                    outcome_name = outcome.get('name', '')
                    outcome_price = outcome.get('price')

                    if outcome_name == home_team:
                        home_odds = outcome_price
                    elif outcome_name == away_team:
                        away_odds = outcome_price

                if home_odds is not None and away_odds is not None:
                    bookmakers_data[book_name] = {
                        'home_odds': home_odds,
                        'away_odds': away_odds,
                        'home_prob': round(american_odds_to_probability(home_odds) * 100, 1),
                        'away_prob': round(american_odds_to_probability(away_odds) * 100, 1),
                    }
                    all_home_odds.append(home_odds)
                    all_away_odds.append(away_odds)

        # Calculate consensus (average across all books)
        consensus = {}
        if all_home_odds and all_away_odds:
            avg_home = round(sum(all_home_odds) / len(all_home_odds))
            avg_away = round(sum(all_away_odds) / len(all_away_odds))

            home_prob = american_odds_to_probability(avg_home)
            away_prob = american_odds_to_probability(avg_away)

            # Remove vig (juice) to get true probability
            # The sum of implied probs is usually > 1.00 due to vig
            total_prob = home_prob + away_prob
            home_prob_no_vig = home_prob / total_prob if total_prob > 0 else home_prob
            away_prob_no_vig = away_prob / total_prob if total_prob > 0 else away_prob

            consensus = {
                'home_odds': avg_home,
                'away_odds': avg_away,
                'home_prob': round(home_prob * 100, 1),
                'away_prob': round(away_prob * 100, 1),
                'home_prob_no_vig': round(home_prob_no_vig * 100, 1),
                'away_prob_no_vig': round(away_prob_no_vig * 100, 1),
                'vig': round((total_prob - 1) * 100, 2),  # Amount of juice
                'books_count': len(all_home_odds),
            }

        return {
            'game_id': game.get('id', ''),
            'home_team': home_team,
            'away_team': away_team,
            'game_time': game_time,
            'bookmakers': bookmakers_data,
            'consensus': consensus,
        }

    except Exception as e:
        logger.error(f"Error parsing odds game: {e}")
        return None


def find_matching_odds(home_team: str, away_team: str, all_odds: list[dict]) -> dict | None:
    """
    Find sportsbook odds matching a specific game.
    Handles team name variations (The Odds API may use different names).

    Returns the game odds dict or None if not found.
    """
    home_lower = home_team.lower()
    away_lower = away_team.lower()

    for game in all_odds:
        g_home = game.get('home_team', '').lower()
        g_away = game.get('away_team', '').lower()

        # Try exact match
        if g_home == home_lower and g_away == away_lower:
            return game

        # Try partial word matching (handle "LA Clippers" vs "Los Angeles Clippers")
        home_words = set(home_lower.split())
        away_words = set(away_lower.split())
        g_home_words = set(g_home.split())
        g_away_words = set(g_away.split())

        # Remove common words that don't help with matching
        common_words = {'the', 'of', 'at', 'in', 'los', 'san', 'new', 'golden'}
        home_words -= common_words
        away_words -= common_words
        g_home_words -= common_words
        g_away_words -= common_words

        home_match = bool(home_words & g_home_words)
        away_match = bool(away_words & g_away_words)

        if home_match and away_match:
            return game

    return None


def format_american_odds(odds: int) -> str:
    """Format American odds for display: -180 -> '-180', +155 -> '+155'"""
    if odds is None:
        return 'N/A'
    if odds > 0:
        return f'+{odds}'
    return str(odds)


def get_api_quota_status() -> dict:
    """
    Check how many Odds API requests are remaining.
    Makes a lightweight call to check quota without fetching full data.
    """
    api_key = _get_api_key()
    if not api_key:
        return {'available': False, 'remaining': 0, 'used': 0}

    try:
        # Make a tiny request to check quota
        url = f"{ODDS_API_BASE_URL}/sports"
        params = {'apiKey': api_key}
        response = requests.get(url, params=params, timeout=10)

        remaining = int(response.headers.get('x-requests-remaining', 0))
        used = int(response.headers.get('x-requests-used', 0))

        return {
            'available': True,
            'remaining': remaining,
            'used': used,
            'low_quota_warning': remaining < 50,
        }
    except Exception as e:
        logger.error(f"Error checking API quota: {e}")
        return {'available': False, 'remaining': 0, 'used': 0}


# Quick test when run directly
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    print("Testing The Odds API...")

    # Load .env file if it exists
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    odds = get_nba_odds()
    print(f"\nGot odds for {len(odds)} games:")
    for game in odds[:3]:
        c = game['consensus']
        if c:
            print(f"  {game['away_team']} @ {game['home_team']}")
            print(f"    Home: {format_american_odds(c['home_odds'])} ({c['home_prob']}%)")
            print(f"    Away: {format_american_odds(c['away_odds'])} ({c['away_prob']}%)")
