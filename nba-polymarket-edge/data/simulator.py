"""
simulator.py — Projected Box Score & Injury Simulator
The core analysis engine. Takes player stats and injury reports,
then projects how a team will perform tonight.

The injury simulation logic:
1. Start with each player's season averages (pts/min, reb/min, ast/min)
2. Find players who are OUT
3. Calculate the freed-up minutes from OUT players
4. Redistribute those minutes:
   - 60% to the backup at the same position
   - 40% spread across remaining starters (2-3 minutes each)
5. Cap any single player at 40 minutes max
6. Recalculate projected stats from new minutes × per-minute rates
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Position groups for minute redistribution logic
# Positions from NBA.com: G, F, C, G-F, F-C, etc.
GUARD_POSITIONS = {'G', 'PG', 'SG', 'G-F'}
FORWARD_POSITIONS = {'F', 'SF', 'PF', 'F-C', 'F-G', 'G-F'}
CENTER_POSITIONS = {'C', 'F-C', 'C-F'}

MAX_MINUTES_PER_GAME = 40  # Cap to prevent unrealistic projections
TOTAL_TEAM_MINUTES = 240   # 5 players × 48 minutes


def get_position_group(position: str) -> str:
    """Categorize a position string into Guard, Forward, or Center."""
    pos = (position or '').upper().strip()
    if pos in CENTER_POSITIONS:
        return 'C'
    elif pos in FORWARD_POSITIONS:
        return 'F'
    else:
        return 'G'  # Default to guard if unknown


def calculate_per_minute_rates(player: dict) -> dict:
    """
    Calculate per-minute production rates from season averages.
    This lets us project stats for different minute totals.

    Example: 20 PPG in 32 minutes = 0.625 pts/min
    """
    minutes = player.get('minutes', 0) or 0
    if minutes <= 0:
        return {
            'pts_per_min': 0,
            'reb_per_min': 0,
            'ast_per_min': 0,
            'stl_per_min': 0,
            'blk_per_min': 0,
        }

    return {
        'pts_per_min': (player.get('points', 0) or 0) / minutes,
        'reb_per_min': (player.get('rebounds', 0) or 0) / minutes,
        'ast_per_min': (player.get('assists', 0) or 0) / minutes,
        'stl_per_min': (player.get('steals', 0) or 0) / minutes,
        'blk_per_min': (player.get('blocks', 0) or 0) / minutes,
    }


def project_stats_from_minutes(player: dict, projected_minutes: float) -> dict:
    """
    Project a player's stats for a given number of minutes.
    Uses their per-minute rates from season averages.
    """
    rates = calculate_per_minute_rates(player)
    mins = max(0, min(projected_minutes, MAX_MINUTES_PER_GAME))

    return {
        'player_id': player.get('player_id'),
        'name': player.get('name', ''),
        'position': player.get('position', ''),
        'season_minutes': round(player.get('minutes', 0) or 0, 1),
        'projected_minutes': round(mins, 1),
        'projected_points': round(rates['pts_per_min'] * mins, 1),
        'projected_rebounds': round(rates['reb_per_min'] * mins, 1),
        'projected_assists': round(rates['ast_per_min'] * mins, 1),
        'projected_steals': round(rates['stl_per_min'] * mins, 1),
        'projected_blocks': round(rates['blk_per_min'] * mins, 1),
        # Also include season averages for reference
        'season_points': player.get('points', 0),
        'season_rebounds': player.get('rebounds', 0),
        'season_assists': player.get('assists', 0),
        'fg_pct': player.get('fg_pct', 0),
        'fg3_pct': player.get('fg3_pct', 0),
        'ft_pct': player.get('ft_pct', 0),
        'plus_minus': player.get('plus_minus', 0),
    }


def build_full_strength_projection(players: list[dict]) -> dict:
    """
    Build a "Full Strength" projection — what happens if everyone is healthy.
    Just uses each player's normal season average minutes.

    Args:
        players: List of player dicts from nba_stats.get_team_players_with_stats()

    Returns:
    {
        'players': [...projected player stats...],
        'team_points': 115.3,
        'team_rebounds': 44.2,
        'team_assists': 25.1,
        'minutes_total': 240.0
    }
    """
    projected_players = []

    for player in players:
        # Use actual season average minutes
        projected = project_stats_from_minutes(player, player.get('minutes', 0) or 0)
        projected_players.append(projected)

    return _summarize_projection(projected_players, "Full Strength")


def build_injury_adjusted_projection(
    players: list[dict],
    out_players: list[str],
    questionable_players: list[str] = None
) -> dict:
    """
    Build an injury-adjusted projection.
    Removes OUT players and redistributes their minutes to teammates.

    Args:
        players: List of all players with stats (from nba_stats module)
        out_players: List of player names confirmed OUT
        questionable_players: List of questionable player names (we assume 50% chance)

    Returns same format as build_full_strength_projection() plus injury notes.
    """
    if questionable_players is None:
        questionable_players = []

    # Normalize names for comparison (lowercase for matching)
    out_names = {name.lower() for name in out_players}
    questionable_names = {name.lower() for name in questionable_players}

    # Separate available and unavailable players
    available = []
    unavailable = []

    for player in players:
        pname = player.get('name', '').lower()
        if pname in out_names:
            player_copy = {**player, 'injury_status': 'OUT', 'is_out': True}
            unavailable.append(player_copy)
        else:
            player_copy = {**player, 'injury_status': 'Active', 'is_out': False}
            if pname in questionable_names:
                player_copy['injury_status'] = 'QUESTIONABLE'
            available.append(player_copy)

    if not unavailable:
        # No injuries — same as full strength
        return build_full_strength_projection(players)

    # Calculate total minutes freed up by OUT players
    freed_minutes = sum(p.get('minutes', 0) or 0 for p in unavailable)
    logger.info(f"Freed minutes from injuries: {freed_minutes:.1f} from {len(unavailable)} players")

    if freed_minutes <= 0 or not available:
        return build_full_strength_projection(available)

    # Assign base minutes to available players (their normal averages)
    working_players = [{**p, 'working_minutes': p.get('minutes', 0) or 0} for p in available]

    # Redistribute freed minutes
    # Strategy: find the backup at each OUT player's position
    # Give 60% of their minutes to the direct backup, 40% spread across starters

    for out_player in unavailable:
        out_pos_group = get_position_group(out_player.get('position', 'G'))
        out_mins = out_player.get('minutes', 0) or 0

        if out_mins <= 0:
            continue

        primary_boost = out_mins * 0.60  # 60% to backup
        secondary_boost = out_mins * 0.40  # 40% spread to starters

        # Find the backup at the same position (player with fewer minutes than the OUT player)
        same_pos_players = [
            p for p in working_players
            if get_position_group(p.get('position', 'G')) == out_pos_group
            and p['working_minutes'] < out_mins  # Backup has fewer minutes = bench player
        ]

        if same_pos_players:
            # Give primary boost to the first backup (highest minutes among backups)
            backup = max(same_pos_players, key=lambda p: p['working_minutes'])
            backup['working_minutes'] = min(
                backup['working_minutes'] + primary_boost,
                MAX_MINUTES_PER_GAME
            )
        else:
            # No positional backup found — spread evenly
            secondary_boost = out_mins  # Give all to starters

        # Distribute secondary boost to starters (top 5 by minutes)
        starters = sorted(working_players, key=lambda p: p['working_minutes'], reverse=True)[:5]
        boost_per_starter = secondary_boost / len(starters)

        for starter in starters:
            starter['working_minutes'] = min(
                starter['working_minutes'] + boost_per_starter,
                MAX_MINUTES_PER_GAME
            )

    # Now project stats for each available player with their new minutes
    projected_players = []
    for player in working_players:
        projected = project_stats_from_minutes(player, player['working_minutes'])
        projected['injury_status'] = player.get('injury_status', 'Active')
        projected['minutes_change'] = round(
            player['working_minutes'] - (player.get('minutes', 0) or 0), 1
        )
        projected_players.append(projected)

    # Also include OUT players with 0 projected minutes
    for player in unavailable:
        projected = project_stats_from_minutes(player, 0)
        projected['injury_status'] = 'OUT'
        projected['is_out'] = True
        projected['minutes_change'] = -(player.get('minutes', 0) or 0)
        projected_players.append(projected)

    result = _summarize_projection(projected_players, "Injury Adjusted")
    result['freed_minutes'] = round(freed_minutes, 1)
    result['out_players'] = [p.get('name') for p in unavailable]
    result['notes'] = _generate_injury_notes(unavailable, working_players)

    return result


def _summarize_projection(projected_players: list[dict], label: str) -> dict:
    """
    Sum up projected stats across all players to get team totals.
    Only counts players who have projected minutes > 0.
    """
    active_players = [p for p in projected_players if not p.get('is_out', False)]

    team_points = sum(p.get('projected_points', 0) for p in active_players)
    team_rebounds = sum(p.get('projected_rebounds', 0) for p in active_players)
    team_assists = sum(p.get('projected_assists', 0) for p in active_players)
    team_steals = sum(p.get('projected_steals', 0) for p in active_players)
    team_blocks = sum(p.get('projected_blocks', 0) for p in active_players)
    total_minutes = sum(p.get('projected_minutes', 0) for p in active_players)

    return {
        'label': label,
        'players': projected_players,
        'team_points': round(team_points, 1),
        'team_rebounds': round(team_rebounds, 1),
        'team_assists': round(team_assists, 1),
        'team_steals': round(team_steals, 1),
        'team_blocks': round(team_blocks, 1),
        'minutes_total': round(total_minutes, 1),
    }


def _generate_injury_notes(out_players: list[dict], available: list[dict]) -> list[str]:
    """Generate human-readable notes about the injury impact."""
    notes = []

    for out_p in out_players:
        name = out_p.get('name', 'Unknown')
        mins = out_p.get('minutes', 0) or 0
        pts = out_p.get('points', 0) or 0
        notes.append(f"{name} (OUT): Losing {mins:.0f} min, {pts:.1f} PPG from lineup")

    return notes


def compare_projections(full_strength: dict, injury_adjusted: dict) -> dict:
    """
    Compare Full Strength vs Injury Adjusted projections.
    Shows the impact of injuries on team performance.

    Returns a summary dict with the differences.
    """
    pts_diff = injury_adjusted['team_points'] - full_strength['team_points']
    reb_diff = injury_adjusted['team_rebounds'] - full_strength['team_rebounds']
    ast_diff = injury_adjusted['team_assists'] - full_strength['team_assists']

    return {
        'points_impact': round(pts_diff, 1),
        'rebounds_impact': round(reb_diff, 1),
        'assists_impact': round(ast_diff, 1),
        'severity': _classify_injury_impact(pts_diff),
        'summary': _impact_summary_text(pts_diff),
    }


def _classify_injury_impact(points_diff: float) -> str:
    """Classify the injury impact severity based on projected point loss."""
    if points_diff <= -15:
        return 'severe'   # Star player(s) out, major impact
    elif points_diff <= -8:
        return 'high'     # Significant impact
    elif points_diff <= -3:
        return 'medium'   # Noticeable but manageable
    elif points_diff < 0:
        return 'low'      # Minor impact
    else:
        return 'none'


def _impact_summary_text(points_diff: float) -> str:
    """Generate a human-readable summary of the injury impact."""
    if points_diff <= -15:
        return f"Severe impact: projected {abs(points_diff):.1f} fewer points without key players"
    elif points_diff <= -8:
        return f"Significant impact: {abs(points_diff):.1f} fewer projected points"
    elif points_diff <= -3:
        return f"Moderate impact: {abs(points_diff):.1f} fewer projected points"
    elif points_diff < 0:
        return f"Minor impact: {abs(points_diff):.1f} fewer projected points"
    else:
        return "No significant injury impact detected"


def run_game_simulation(
    home_players: list[dict],
    away_players: list[dict],
    home_injuries: list[dict],
    away_injuries: list[dict]
) -> dict:
    """
    Run the full simulation for a game: both full strength and injury adjusted
    for both teams.

    Args:
        home_players: List of home team player dicts with stats
        away_players: List of away team player dicts with stats
        home_injuries: List of injury dicts for home team
        away_injuries: List of injury dicts for away team

    Returns a complete simulation result for display in the UI.
    """
    # Extract OUT player names
    home_out = [p['player_name'] for p in home_injuries if p.get('is_out')]
    away_out = [p['player_name'] for p in away_injuries if p.get('is_out')]

    home_questionable = [p['player_name'] for p in home_injuries if p.get('is_questionable')]
    away_questionable = [p['player_name'] for p in away_injuries if p.get('is_questionable')]

    # Build projections for home team
    home_full = build_full_strength_projection(home_players)
    home_adjusted = build_injury_adjusted_projection(home_players, home_out, home_questionable)
    home_impact = compare_projections(home_full, home_adjusted)

    # Build projections for away team
    away_full = build_full_strength_projection(away_players)
    away_adjusted = build_injury_adjusted_projection(away_players, away_out, away_questionable)
    away_impact = compare_projections(away_full, away_adjusted)

    # Project game total (over/under relevant number)
    game_total_full = home_full['team_points'] + away_full['team_points']
    game_total_adjusted = home_adjusted['team_points'] + away_adjusted['team_points']

    return {
        'home': {
            'full_strength': home_full,
            'injury_adjusted': home_adjusted,
            'impact': home_impact,
        },
        'away': {
            'full_strength': away_full,
            'injury_adjusted': away_adjusted,
            'impact': away_impact,
        },
        'game': {
            'projected_total_full': round(game_total_full, 1),
            'projected_total_adjusted': round(game_total_adjusted, 1),
            'total_impact': round(game_total_adjusted - game_total_full, 1),
            'home_out_count': len(home_out),
            'away_out_count': len(away_out),
        }
    }
