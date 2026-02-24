"""
polymarket.py — Polymarket API Client
Fetches NBA game markets from Polymarket's public API.
No authentication required for reading market data.

Polymarket prices work like this:
  - Each outcome (team) has a price from 0 to 1
  - Price 0.55 = 55% implied probability of winning
  - Both sides of a market should sum to ~1.00 (minus any spread)
"""

import requests
import logging
import time
from datetime import datetime, timezone

# Set up logging so we can see what's happening
logger = logging.getLogger(__name__)

# Base URL for Polymarket's Gamma API (free, no auth needed)
POLYMARKET_BASE_URL = "https://gamma-api.polymarket.com"

# Team name normalization map: maps various team name formats to a standard name
# This is needed because nba_api, Polymarket, and sportsbooks all use different names
TEAM_NAME_MAP = {
    # Full name -> Standard
    "Atlanta Hawks": "Atlanta Hawks",
    "Boston Celtics": "Boston Celtics",
    "Brooklyn Nets": "Brooklyn Nets",
    "Charlotte Hornets": "Charlotte Hornets",
    "Chicago Bulls": "Chicago Bulls",
    "Cleveland Cavaliers": "Cleveland Cavaliers",
    "Dallas Mavericks": "Dallas Mavericks",
    "Denver Nuggets": "Denver Nuggets",
    "Detroit Pistons": "Detroit Pistons",
    "Golden State Warriors": "Golden State Warriors",
    "Houston Rockets": "Houston Rockets",
    "Indiana Pacers": "Indiana Pacers",
    "LA Clippers": "LA Clippers",
    "Los Angeles Clippers": "LA Clippers",
    "LA Lakers": "Los Angeles Lakers",
    "Los Angeles Lakers": "Los Angeles Lakers",
    "LAL": "Los Angeles Lakers",
    "LAC": "LA Clippers",
    "Memphis Grizzlies": "Memphis Grizzlies",
    "Miami Heat": "Miami Heat",
    "Milwaukee Bucks": "Milwaukee Bucks",
    "Minnesota Timberwolves": "Minnesota Timberwolves",
    "New Orleans Pelicans": "New Orleans Pelicans",
    "New York Knicks": "New York Knicks",
    "Oklahoma City Thunder": "Oklahoma City Thunder",
    "Orlando Magic": "Orlando Magic",
    "Philadelphia 76ers": "Philadelphia 76ers",
    "Phoenix Suns": "Phoenix Suns",
    "Portland Trail Blazers": "Portland Trail Blazers",
    "Sacramento Kings": "Sacramento Kings",
    "San Antonio Spurs": "San Antonio Spurs",
    "Toronto Raptors": "Toronto Raptors",
    "Utah Jazz": "Utah Jazz",
    "Washington Wizards": "Washington Wizards",
    # Short names / abbreviations
    "Hawks": "Atlanta Hawks",
    "Celtics": "Boston Celtics",
    "Nets": "Brooklyn Nets",
    "Hornets": "Charlotte Hornets",
    "Bulls": "Chicago Bulls",
    "Cavaliers": "Cleveland Cavaliers",
    "Cavs": "Cleveland Cavaliers",
    "Mavericks": "Dallas Mavericks",
    "Mavs": "Dallas Mavericks",
    "Nuggets": "Denver Nuggets",
    "Pistons": "Detroit Pistons",
    "Warriors": "Golden State Warriors",
    "Rockets": "Houston Rockets",
    "Pacers": "Indiana Pacers",
    "Clippers": "LA Clippers",
    "Lakers": "Los Angeles Lakers",
    "Grizzlies": "Memphis Grizzlies",
    "Heat": "Miami Heat",
    "Bucks": "Milwaukee Bucks",
    "Timberwolves": "Minnesota Timberwolves",
    "Pelicans": "New Orleans Pelicans",
    "Knicks": "New York Knicks",
    "Thunder": "Oklahoma City Thunder",
    "Magic": "Orlando Magic",
    "76ers": "Philadelphia 76ers",
    "Sixers": "Philadelphia 76ers",
    "Suns": "Phoenix Suns",
    "Trail Blazers": "Portland Trail Blazers",
    "Blazers": "Portland Trail Blazers",
    "Kings": "Sacramento Kings",
    "Spurs": "San Antonio Spurs",
    "Raptors": "Toronto Raptors",
    "Jazz": "Utah Jazz",
    "Wizards": "Washington Wizards",
}

# NBA abbreviation to standard name
NBA_ABBREV_TO_NAME = {
    "ATL": "Atlanta Hawks",
    "BOS": "Boston Celtics",
    "BKN": "Brooklyn Nets",
    "CHA": "Charlotte Hornets",
    "CHI": "Chicago Bulls",
    "CLE": "Cleveland Cavaliers",
    "DAL": "Dallas Mavericks",
    "DEN": "Denver Nuggets",
    "DET": "Detroit Pistons",
    "GSW": "Golden State Warriors",
    "HOU": "Houston Rockets",
    "IND": "Indiana Pacers",
    "LAC": "LA Clippers",
    "LAL": "Los Angeles Lakers",
    "MEM": "Memphis Grizzlies",
    "MIA": "Miami Heat",
    "MIL": "Milwaukee Bucks",
    "MIN": "Minnesota Timberwolves",
    "NOP": "New Orleans Pelicans",
    "NYK": "New York Knicks",
    "OKC": "Oklahoma City Thunder",
    "ORL": "Orlando Magic",
    "PHI": "Philadelphia 76ers",
    "PHX": "Phoenix Suns",
    "POR": "Portland Trail Blazers",
    "SAC": "Sacramento Kings",
    "SAS": "San Antonio Spurs",
    "TOR": "Toronto Raptors",
    "UTA": "Utah Jazz",
    "WAS": "Washington Wizards",
}


def normalize_team_name(name: str) -> str:
    """
    Convert any team name variant to the standard full name.
    Example: 'LAL' -> 'Los Angeles Lakers', 'Lakers' -> 'Los Angeles Lakers'
    """
    if not name:
        return name

    # Try direct lookup first
    if name in TEAM_NAME_MAP:
        return TEAM_NAME_MAP[name]

    # Try abbreviation lookup
    upper_name = name.upper()
    if upper_name in NBA_ABBREV_TO_NAME:
        return NBA_ABBREV_TO_NAME[upper_name]

    # Try case-insensitive match in TEAM_NAME_MAP
    for key, value in TEAM_NAME_MAP.items():
        if key.lower() == name.lower():
            return value

    # Try to find a team name that contains this string
    for key, value in TEAM_NAME_MAP.items():
        if name.lower() in key.lower() or key.lower() in name.lower():
            return value

    # Return original if no match found
    logger.warning(f"Could not normalize team name: {name}")
    return name


def get_nba_series_id() -> str | None:
    """
    Fetch the NBA series/league ID from Polymarket's sports endpoint.
    This ID is needed to then fetch individual game markets.
    Returns the series ID string or None if not found.
    """
    try:
        logger.info("Fetching sports list from Polymarket...")
        url = f"{POLYMARKET_BASE_URL}/sports"

        response = requests.get(url, timeout=10)
        response.raise_for_status()

        sports = response.json()
        logger.info(f"Got {len(sports)} sports from Polymarket")

        # Look for NBA in the sports list
        for sport in sports:
            # The sport object should have a 'name' and 'id' or 'series_id' field
            name = sport.get('name', '') or sport.get('league', '') or ''
            if 'NBA' in name.upper() or 'basketball' in name.lower():
                series_id = sport.get('id') or sport.get('series_id')
                logger.info(f"Found NBA series: {sport}")
                return str(series_id)

        logger.warning("NBA not found in Polymarket sports list")
        logger.debug(f"Available sports: {sports[:5]}")
        return None

    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching Polymarket sports: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error in get_nba_series_id: {e}")
        return None


def get_nba_markets() -> list[dict]:
    """
    Fetch all active, unclosed NBA game markets from Polymarket.
    Returns a list of market dicts with parsed team names and prices.

    Each market dict looks like:
    {
        'market_id': '...',
        'question': 'Will the Lakers beat the Celtics?',
        'team1': 'Los Angeles Lakers',
        'team2': 'Boston Celtics',
        'team1_price': 0.45,   # implied probability (0-1)
        'team2_price': 0.55,
        'volume': 125000,
        'game_time': '2024-01-15T20:00:00Z',
        'raw': {...}  # full original data for debugging
    }
    """
    markets = []

    try:
        # First, try to get markets using a direct NBA search
        # Polymarket uses "series" to group related markets
        logger.info("Fetching NBA markets from Polymarket...")

        # Try multiple approaches to find NBA markets
        # Approach 1: Search events with NBA keyword
        url = f"{POLYMARKET_BASE_URL}/events"
        params = {
            'active': 'true',
            'closed': 'false',
            'tag_id': 'nba',  # may not exist, just trying
            'limit': 100
        }

        try:
            response = requests.get(url, params=params, timeout=15)
            response.raise_for_status()
            events_data = response.json()
            logger.info(f"Fetched {len(events_data) if isinstance(events_data, list) else 'unknown'} events")
        except Exception as e:
            logger.warning(f"Events fetch with tag failed: {e}, trying without tag")
            events_data = []

        # Approach 2: Get sports first, then use series_id
        if not events_data:
            series_id = get_nba_series_id()
            if series_id:
                url = f"{POLYMARKET_BASE_URL}/events"
                params = {
                    'series_id': series_id,
                    'active': 'true',
                    'closed': 'false',
                    'limit': 100
                }
                response = requests.get(url, params=params, timeout=15)
                response.raise_for_status()
                events_data = response.json()
                logger.info(f"Got {len(events_data)} events via series_id")

        # Parse the events into our standard format
        if isinstance(events_data, list):
            raw_events = events_data
        elif isinstance(events_data, dict):
            raw_events = events_data.get('events', events_data.get('data', []))
        else:
            raw_events = []

        for event in raw_events:
            parsed = _parse_polymarket_event(event)
            if parsed:
                markets.append(parsed)

        logger.info(f"Parsed {len(markets)} NBA markets from Polymarket")

    except requests.exceptions.RequestException as e:
        logger.error(f"Network error fetching Polymarket markets: {e}")
    except Exception as e:
        logger.error(f"Error fetching Polymarket markets: {e}", exc_info=True)

    return markets


def _parse_polymarket_event(event: dict) -> dict | None:
    """
    Parse a raw Polymarket event into our standard market format.
    Handles different API response structures.
    """
    try:
        # Extract basic info
        event_id = event.get('id', '')
        title = event.get('title', '') or event.get('question', '') or ''

        # Only process NBA game markets (moneyline-style "Who wins?" markets)
        # Filter by title keywords
        title_lower = title.lower()
        is_nba = any(keyword in title_lower for keyword in [
            'nba', 'will the', 'win the game', 'beat', 'vs', ' v '
        ])

        # Check if this looks like a game market (not a season-long bet)
        is_game_market = any(keyword in title_lower for keyword in [
            'will the', 'beat', 'win tonight', 'win the game'
        ])

        # Get markets/tokens within this event
        markets = event.get('markets', [])

        # Parse team names from the title
        # Common Polymarket format: "Will the [Team1] beat the [Team2]?"
        # or "[Team1] vs [Team2]"
        team1_name = None
        team2_name = None
        team1_price = None
        team2_price = None

        # Try to extract from markets' outcomes
        for market in markets:
            outcomes = market.get('outcomes', '[]')
            if isinstance(outcomes, str):
                import json
                try:
                    outcomes = json.loads(outcomes)
                except:
                    outcomes = []

            out_prices = market.get('outcomePrices', '[]')
            if isinstance(out_prices, str):
                import json
                try:
                    out_prices = json.loads(out_prices)
                except:
                    out_prices = []

            if len(outcomes) >= 2:
                team1_name = normalize_team_name(outcomes[0]) if outcomes[0] != 'Yes' else None
                team2_name = normalize_team_name(outcomes[1]) if outcomes[1] != 'No' else None

                if len(out_prices) >= 2:
                    try:
                        team1_price = float(out_prices[0])
                        team2_price = float(out_prices[1])
                    except (ValueError, TypeError):
                        pass

        # If we couldn't get teams from outcomes, skip
        if not team1_name or not team2_name:
            return None

        # Skip if prices look wrong (should be between 0 and 1)
        if team1_price is not None and team2_price is not None:
            if not (0 < team1_price < 1 and 0 < team2_price < 1):
                # Prices might be in cents (0-100), convert to 0-1
                if team1_price > 1:
                    team1_price = team1_price / 100
                if team2_price > 1:
                    team2_price = team2_price / 100

        # Extract volume
        volume = 0
        for market in markets:
            vol = market.get('volume', 0) or market.get('volumeNum', 0)
            try:
                volume += float(vol)
            except (ValueError, TypeError):
                pass

        # Extract game time
        game_time = event.get('startDate', '') or event.get('endDate', '') or ''

        return {
            'market_id': event_id,
            'question': title,
            'team1': team1_name,
            'team2': team2_name,
            'team1_price': team1_price,
            'team2_price': team2_price,
            'team1_prob': round(team1_price * 100, 1) if team1_price else None,
            'team2_prob': round(team2_price * 100, 1) if team2_price else None,
            'volume': round(volume, 2),
            'game_time': game_time,
            'raw': event  # keep original for debugging
        }

    except Exception as e:
        logger.error(f"Error parsing Polymarket event: {e}")
        return None


def find_matching_market(home_team: str, away_team: str, markets: list[dict]) -> dict | None:
    """
    Find the Polymarket market that matches a given game.
    Handles team name variations using normalization.

    Args:
        home_team: Normalized home team name (e.g., "Boston Celtics")
        away_team: Normalized away team name
        markets: List of parsed Polymarket markets

    Returns the matching market dict or None
    """
    home_norm = normalize_team_name(home_team)
    away_norm = normalize_team_name(away_team)

    for market in markets:
        m_team1 = normalize_team_name(market.get('team1', ''))
        m_team2 = normalize_team_name(market.get('team2', ''))

        # Check both orderings (home/away may be swapped)
        match1 = (m_team1 == home_norm and m_team2 == away_norm)
        match2 = (m_team1 == away_norm and m_team2 == home_norm)

        if match1 or match2:
            # If teams are swapped, flip the prices so home team is always team1
            if match2:
                return {
                    **market,
                    'team1': market['team2'],
                    'team2': market['team1'],
                    'team1_price': market['team2_price'],
                    'team2_price': market['team1_price'],
                    'team1_prob': market['team2_prob'],
                    'team2_prob': market['team1_prob'],
                }
            return market

    # If no exact match, try fuzzy matching
    for market in markets:
        m_team1 = market.get('team1', '').lower()
        m_team2 = market.get('team2', '').lower()
        h = home_norm.lower()
        a = away_norm.lower()

        # Check if any word in home team appears in market team name
        home_words = set(h.split())
        away_words = set(a.split())

        team1_words = set(m_team1.split())
        team2_words = set(m_team2.split())

        home_match = bool(home_words & team1_words)
        away_match = bool(away_words & team2_words)

        if home_match and away_match:
            logger.info(f"Fuzzy matched: {home_norm} vs {away_norm} -> {market['team1']} vs {market['team2']}")
            return market

    logger.debug(f"No Polymarket market found for: {home_norm} vs {away_norm}")
    return None


# Quick test function for debugging
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    print("Testing Polymarket API...")

    markets = get_nba_markets()
    print(f"\nFound {len(markets)} NBA markets:")
    for m in markets[:5]:  # Show first 5
        print(f"  {m['team1']} ({m['team1_prob']}%) vs {m['team2']} ({m['team2_prob']}%) | Vol: ${m['volume']:,.0f}")
