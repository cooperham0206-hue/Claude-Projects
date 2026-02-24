"""
injuries.py — NBA Injury Report Module
Uses the nbainjuries package to pull official NBA injury reports from NBA.com.
Also provides fallback logic if the package has issues.

Injury statuses in priority order (most severe first):
  OUT → DOUBTFUL → QUESTIONABLE → PROBABLE → (active)
"""

import logging
import time
from datetime import date

logger = logging.getLogger(__name__)

# Try to import nbainjuries package (requires Java/JVM to be installed)
try:
    import nbainjuries
    INJURIES_AVAILABLE = True
    logger.info("nbainjuries loaded successfully")
except Exception:
    INJURIES_AVAILABLE = False
    logger.warning("nbainjuries not available (requires Java — injury data will be skipped)")

# --- Simple in-memory cache ---
_cache = {}

def _get_cache(key: str, ttl_seconds: int = 300):
    if key in _cache:
        data, timestamp = _cache[key]
        if time.time() - timestamp < ttl_seconds:
            return data
    return None

def _set_cache(key: str, data):
    _cache[key] = (data, time.time())


# Status severity mapping (higher number = more severe / affects team more)
STATUS_SEVERITY = {
    'OUT': 4,
    'DOUBTFUL': 3,
    'QUESTIONABLE': 2,
    'PROBABLE': 1,
    'GTD': 2,  # Game-Time Decision (same as Questionable)
    'DAY-TO-DAY': 1,
}

# CSS color classes for the frontend
STATUS_COLOR = {
    'OUT': 'status-out',
    'DOUBTFUL': 'status-doubtful',
    'QUESTIONABLE': 'status-questionable',
    'PROBABLE': 'status-probable',
    'GTD': 'status-questionable',
    'DAY-TO-DAY': 'status-probable',
}


def get_all_injuries() -> dict:
    """
    Fetch the current NBA injury report for all teams.

    Returns a dict organized by team name:
    {
        'Boston Celtics': [
            {
                'player_name': 'Jaylen Brown',
                'status': 'OUT',
                'reason': 'Right Ankle Sprain',
                'return_date': 'Unknown',
                'severity': 4,
                'color_class': 'status-out'
            },
            ...
        ],
        ...
    }
    """
    cache_key = f"injuries_{date.today()}"
    cached = _get_cache(cache_key, ttl_seconds=600)  # Cache for 10 minutes
    if cached:
        logger.debug("Returning cached injury data")
        return cached

    if not INJURIES_AVAILABLE:
        logger.warning("nbainjuries package not available")
        return {}

    try:
        logger.info("Fetching NBA injury report...")

        # nbainjuries fetches from NBA.com's official injury report
        injury_data = nbainjuries.injuries()

        # The package returns a pandas DataFrame or dict — handle both
        injuries_by_team = {}

        if hasattr(injury_data, 'to_dict'):
            # It's a DataFrame — convert to list of dicts
            records = injury_data.to_dict('records')
        elif isinstance(injury_data, list):
            records = injury_data
        elif isinstance(injury_data, dict):
            # Might already be organized by team
            records = []
            for team, players in injury_data.items():
                if isinstance(players, list):
                    for p in players:
                        records.append({**p, 'team': team})
        else:
            logger.warning(f"Unexpected injury data format: {type(injury_data)}")
            records = []

        for record in records:
            # Normalize field names (the package may use different column names)
            player_name = (
                record.get('Player') or
                record.get('player') or
                record.get('player_name') or
                record.get('PLAYER') or
                'Unknown'
            )

            team_name = (
                record.get('Team') or
                record.get('team') or
                record.get('team_name') or
                record.get('TEAM') or
                'Unknown'
            )

            status = (
                record.get('Status') or
                record.get('status') or
                record.get('CURRENT_STATUS') or
                record.get('Reason') or
                'Unknown'
            ).upper().strip()

            reason = (
                record.get('Reason') or
                record.get('reason') or
                record.get('Injury') or
                record.get('injury') or
                record.get('Comment') or
                ''
            )

            # Normalize status to standard values
            if 'OUT' in status and 'DOUBTFUL' not in status:
                normalized_status = 'OUT'
            elif 'DOUBTFUL' in status:
                normalized_status = 'DOUBTFUL'
            elif 'QUESTIONABLE' in status or 'GTD' in status or 'GAME TIME' in status:
                normalized_status = 'QUESTIONABLE'
            elif 'PROBABLE' in status or 'DAY' in status:
                normalized_status = 'PROBABLE'
            else:
                normalized_status = status[:20]  # Truncate unknown statuses

            injury_entry = {
                'player_name': player_name,
                'status': normalized_status,
                'reason': reason,
                'severity': STATUS_SEVERITY.get(normalized_status, 0),
                'color_class': STATUS_COLOR.get(normalized_status, 'status-unknown'),
                'is_out': normalized_status == 'OUT',
                'is_doubtful': normalized_status == 'DOUBTFUL',
                'is_questionable': normalized_status == 'QUESTIONABLE',
            }

            if team_name not in injuries_by_team:
                injuries_by_team[team_name] = []
            injuries_by_team[team_name].append(injury_entry)

        # Sort each team's injuries by severity (OUT first)
        for team in injuries_by_team:
            injuries_by_team[team].sort(key=lambda p: p['severity'], reverse=True)

        logger.info(f"Injury report: {len(injuries_by_team)} teams with injuries")
        _set_cache(cache_key, injuries_by_team)
        return injuries_by_team

    except Exception as e:
        logger.error(f"Error fetching injury report: {e}", exc_info=True)
        return {}


def get_team_injuries(team_name: str, all_injuries: dict = None) -> list[dict]:
    """
    Get injuries for a specific team.
    Handles team name variations (e.g., 'Celtics' vs 'Boston Celtics').

    Args:
        team_name: The team name to look up
        all_injuries: Pre-fetched injury dict (optional, avoids re-fetching)

    Returns list of injury dicts for that team.
    """
    if all_injuries is None:
        all_injuries = get_all_injuries()

    # Try exact match first
    if team_name in all_injuries:
        return all_injuries[team_name]

    # Try case-insensitive match
    team_lower = team_name.lower()
    for key in all_injuries:
        if key.lower() == team_lower:
            return all_injuries[key]

    # Try partial match (e.g., 'Celtics' matches 'Boston Celtics')
    for key in all_injuries:
        if team_name.lower() in key.lower() or key.lower() in team_name.lower():
            return all_injuries[key]

    return []


def get_out_players(team_name: str, all_injuries: dict = None) -> list[str]:
    """
    Get just the names of players who are confirmed OUT.
    Used by the injury simulator to know who to remove from projections.
    """
    team_injuries = get_team_injuries(team_name, all_injuries)
    return [p['player_name'] for p in team_injuries if p['is_out']]


def get_doubtful_players(team_name: str, all_injuries: dict = None) -> list[str]:
    """Get players listed as DOUBTFUL (unlikely to play)."""
    team_injuries = get_team_injuries(team_name, all_injuries)
    return [p['player_name'] for p in team_injuries if p['is_doubtful']]


def get_questionable_players(team_name: str, all_injuries: dict = None) -> list[str]:
    """Get players listed as QUESTIONABLE (50/50)."""
    team_injuries = get_team_injuries(team_name, all_injuries)
    return [p['player_name'] for p in team_injuries if p['is_questionable']]


def get_injury_impact_summary(team_name: str, all_injuries: dict = None) -> dict:
    """
    Summarize the injury situation for a team with key metrics.

    Returns:
    {
        'has_injuries': True,
        'out_count': 2,
        'questionable_count': 1,
        'key_injuries': ['Jaylen Brown (OUT)', 'Kristaps Porzingis (Q)'],
        'severity_level': 'high',  # 'none', 'low', 'medium', 'high'
        'all_injuries': [...]
    }
    """
    team_injuries = get_team_injuries(team_name, all_injuries)

    out_count = sum(1 for p in team_injuries if p['is_out'])
    doubtful_count = sum(1 for p in team_injuries if p['is_doubtful'])
    questionable_count = sum(1 for p in team_injuries if p['is_questionable'])

    # Determine overall severity
    if out_count >= 2 or (out_count == 1 and doubtful_count >= 1):
        severity = 'high'
    elif out_count == 1 or doubtful_count >= 1:
        severity = 'medium'
    elif questionable_count >= 1:
        severity = 'low'
    else:
        severity = 'none'

    # Build key injuries list (top 3 most severe)
    key_injuries = []
    for injury in team_injuries[:3]:
        key_injuries.append(f"{injury['player_name']} ({injury['status']})")

    return {
        'has_injuries': len(team_injuries) > 0,
        'out_count': out_count,
        'doubtful_count': doubtful_count,
        'questionable_count': questionable_count,
        'key_injuries': key_injuries,
        'severity_level': severity,
        'all_injuries': team_injuries,
    }


# Quick test when run directly
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    print("Testing injury module...")

    if not INJURIES_AVAILABLE:
        print("ERROR: nbainjuries not installed!")
        exit(1)

    injuries = get_all_injuries()
    print(f"\nTeams with injuries: {len(injuries)}")
    for team, players in list(injuries.items())[:3]:
        print(f"\n  {team}:")
        for p in players:
            print(f"    {p['player_name']}: {p['status']} ({p['reason']})")
