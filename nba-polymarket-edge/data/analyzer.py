"""
analyzer.py — Value Finder & Edge Detector
This is the brain of the app — it combines Polymarket prices,
sportsbook odds, and injury projections to find value bets.

Key concept: "Edge" = when Polymarket's implied probability
differs significantly from what sportsbooks or our model says.

If Polymarket says a team has 60% chance to win, but sportsbooks
say 70%, that means Polymarket is UNDERVALUING the favorite.
You could potentially buy that team on Polymarket at a discount.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def calculate_edge(
    polymarket_prob: float,
    sportsbook_prob: float,
) -> dict:
    """
    Calculate the edge between Polymarket and sportsbooks.

    Args:
        polymarket_prob: Polymarket implied probability (0-100)
        sportsbook_prob: Sportsbook implied probability (0-100, already vig-removed)

    Returns:
    {
        'edge': 8.5,              # How much Polymarket differs (positive = poly undervalues)
        'direction': 'buy',       # 'buy' (poly under-priced) or 'sell' (poly over-priced)
        'signal': 'yellow',       # 'green', 'yellow', 'red', or 'none'
        'description': '...'      # Human-readable explanation
    }
    """
    if polymarket_prob is None or sportsbook_prob is None:
        return {
            'edge': None,
            'direction': None,
            'signal': 'none',
            'description': 'Insufficient data for edge calculation'
        }

    # Edge = how much sportsbook disagrees with Polymarket
    # Positive edge = sportsbooks think this team is more likely to win than Polymarket does
    # That means Polymarket might be UNDERPRICING this side (potential buy opportunity)
    edge = sportsbook_prob - polymarket_prob

    # Classify the signal
    abs_edge = abs(edge)

    if abs_edge >= 10:
        signal = 'green' if edge > 0 else 'red'
        direction = 'buy' if edge > 0 else 'sell'
        description = f"Strong edge: Polymarket {'underprices' if edge > 0 else 'overprices'} this team by {abs_edge:.1f}%"
    elif abs_edge >= 5:
        signal = 'yellow'
        direction = 'buy' if edge > 0 else 'sell'
        description = f"Moderate edge: {abs_edge:.1f}% gap between Polymarket and sportsbooks"
    else:
        signal = 'none'
        direction = 'neutral'
        description = f"No significant edge (only {abs_edge:.1f}% gap)"

    return {
        'edge': round(edge, 1),
        'abs_edge': round(abs_edge, 1),
        'direction': direction,
        'signal': signal,
        'description': description,
    }


def calculate_value_score(
    polymarket_prob: float,
    sportsbook_prob: float,
    projection_prob: float | None,
    has_key_injury: bool,
    is_back_to_back: bool
) -> dict:
    """
    Calculate an overall value score for a game side.
    Combines multiple signals into one actionable rating.

    Args:
        polymarket_prob: Polymarket price (0-100)
        sportsbook_prob: No-vig sportsbook probability (0-100)
        projection_prob: Model-projected probability based on stats (0-100, or None)
        has_key_injury: Whether there's a significant injury (OUT player)
        is_back_to_back: Whether the team is on a back-to-back

    Returns a value score and recommendation.
    """
    signals = []
    score = 0  # Positive = value buy, Negative = value sell

    # Signal 1: Polymarket vs Sportsbooks gap
    if polymarket_prob is not None and sportsbook_prob is not None:
        book_edge = sportsbook_prob - polymarket_prob
        if abs(book_edge) >= 10:
            score += book_edge * 1.5  # Strong weight for large gaps
            signals.append(f"Books/Poly gap: {book_edge:+.1f}%")
        elif abs(book_edge) >= 5:
            score += book_edge * 1.0
            signals.append(f"Books/Poly gap: {book_edge:+.1f}%")

    # Signal 2: Key injury not priced in
    if has_key_injury:
        # If Polymarket HASN'T moved the line down for an injured team,
        # the team with injuries is overpriced
        if polymarket_prob is not None and sportsbook_prob is not None:
            if polymarket_prob > sportsbook_prob + 3:
                # Poly still high despite injury — sell signal
                score -= 5
                signals.append("Injury not priced in by Polymarket (-5)")
            else:
                # Both agree injuries matter
                signals.append("Injury impact reflected in odds")

    # Signal 3: Back-to-back disadvantage
    if is_back_to_back:
        score -= 3
        signals.append("Back-to-back disadvantage (-3)")

    # Classify overall signal
    if score >= 10:
        signal = 'green'
        recommendation = 'Strong Buy'
    elif score >= 5:
        signal = 'yellow'
        recommendation = 'Lean Buy'
    elif score <= -10:
        signal = 'red'
        recommendation = 'Strong Sell / Fade'
    elif score <= -5:
        signal = 'yellow'
        recommendation = 'Lean Sell'
    else:
        signal = 'none'
        recommendation = 'No Clear Edge'

    return {
        'score': round(score, 1),
        'signal': signal,
        'recommendation': recommendation,
        'signals': signals,
    }


def analyze_game(
    game: dict,
    polymarket_data: dict | None,
    odds_data: dict | None,
    simulation: dict | None,
    home_b2b: bool = False,
    away_b2b: bool = False
) -> dict:
    """
    Full analysis of a single game combining all data sources.

    Args:
        game: Game dict from nba_stats (has home_team, away_team, etc.)
        polymarket_data: Matched Polymarket market dict (or None)
        odds_data: Matched sportsbook odds dict (or None)
        simulation: Output from simulator.run_game_simulation() (or None)
        home_b2b: Whether home team is on a back-to-back
        away_b2b: Whether away team is on a back-to-back

    Returns a complete analysis dict for display in the UI.
    """
    home_team = game.get('home_team', '')
    away_team = game.get('away_team', '')

    # Extract Polymarket probabilities
    poly_home_prob = None
    poly_away_prob = None
    if polymarket_data:
        # Figure out which poly team is home vs away
        poly_t1 = polymarket_data.get('team1', '')
        poly_t2 = polymarket_data.get('team2', '')
        t1_prob = polymarket_data.get('team1_prob')
        t2_prob = polymarket_data.get('team2_prob')

        if _teams_match(home_team, poly_t1):
            poly_home_prob = t1_prob
            poly_away_prob = t2_prob
        elif _teams_match(home_team, poly_t2):
            poly_home_prob = t2_prob
            poly_away_prob = t1_prob

    # Extract sportsbook probabilities (no-vig)
    book_home_prob = None
    book_away_prob = None
    if odds_data and odds_data.get('consensus'):
        consensus = odds_data['consensus']
        # The Odds API always has home_team = actual home team
        book_home_prob = consensus.get('home_prob_no_vig')
        book_away_prob = consensus.get('away_prob_no_vig')

    # Calculate edges
    home_edge = calculate_edge(poly_home_prob, book_home_prob)
    away_edge = calculate_edge(poly_away_prob, book_away_prob)

    # Determine injury situations
    home_has_key_injury = False
    away_has_key_injury = False
    if simulation:
        home_has_key_injury = simulation.get('game', {}).get('home_out_count', 0) > 0
        away_has_key_injury = simulation.get('game', {}).get('away_out_count', 0) > 0

    # Calculate value scores for each side
    home_value = calculate_value_score(
        poly_home_prob, book_home_prob, None,
        home_has_key_injury, home_b2b
    )
    away_value = calculate_value_score(
        poly_away_prob, book_away_prob, None,
        away_has_key_injury, away_b2b
    )

    # Overall game alert level
    max_abs_edge = max(
        abs(home_edge.get('edge', 0) or 0),
        abs(away_edge.get('edge', 0) or 0)
    )

    if max_abs_edge >= 10 or (home_has_key_injury or away_has_key_injury):
        game_alert = 'high'
    elif max_abs_edge >= 5:
        game_alert = 'medium'
    else:
        game_alert = 'low'

    return {
        'game': game,
        'polymarket': polymarket_data,
        'odds': odds_data,
        'simulation': simulation,
        'analysis': {
            'home': {
                'team': home_team,
                'poly_prob': poly_home_prob,
                'book_prob': book_home_prob,
                'edge': home_edge,
                'value': home_value,
                'is_b2b': home_b2b,
                'has_key_injury': home_has_key_injury,
            },
            'away': {
                'team': away_team,
                'poly_prob': poly_away_prob,
                'book_prob': book_away_prob,
                'edge': away_edge,
                'value': away_value,
                'is_b2b': away_b2b,
                'has_key_injury': away_has_key_injury,
            },
            'game_alert_level': game_alert,
            'has_polymarket_data': polymarket_data is not None,
            'has_odds_data': odds_data is not None,
        }
    }


def _teams_match(team1: str, team2: str) -> bool:
    """Check if two team name strings refer to the same team."""
    if not team1 or not team2:
        return False

    t1 = team1.lower()
    t2 = team2.lower()

    if t1 == t2:
        return True

    # Check if either is contained in the other
    if t1 in t2 or t2 in t1:
        return True

    # Check shared significant words
    stop_words = {'the', 'at', 'of', 'in', 'los', 'san', 'new', 'golden'}
    words1 = set(t1.split()) - stop_words
    words2 = set(t2.split()) - stop_words

    if words1 and words2 and bool(words1 & words2):
        return True

    return False


def sort_games_by_interest(analyzed_games: list[dict]) -> list[dict]:
    """
    Sort analyzed games by how interesting they are for betting.
    Games with larger edges and more injuries come first.
    """
    def interest_score(game_analysis: dict) -> float:
        analysis = game_analysis.get('analysis', {})
        home = analysis.get('home', {})
        away = analysis.get('away', {})

        # Base score from edge sizes
        home_edge = abs(home.get('edge', {}).get('edge', 0) or 0)
        away_edge = abs(away.get('edge', {}).get('edge', 0) or 0)
        max_edge = max(home_edge, away_edge)

        # Bonus for injuries (they create mispricing opportunities)
        injury_bonus = 5 if (home.get('has_key_injury') or away.get('has_key_injury')) else 0

        # Bonus for having Polymarket data
        poly_bonus = 3 if analysis.get('has_polymarket_data') else 0

        return max_edge + injury_bonus + poly_bonus

    return sorted(analyzed_games, key=interest_score, reverse=True)


def generate_value_alerts(analyzed_games: list[dict]) -> list[dict]:
    """
    Generate a list of value alerts for the dashboard.
    Only includes games with meaningful edges.

    Returns list of alert dicts sorted by strength.
    """
    alerts = []

    for game_data in analyzed_games:
        analysis = game_data.get('analysis', {})
        home = analysis.get('home', {})
        away = analysis.get('away', {})

        game = game_data.get('game', {})
        game_time = game.get('game_time', '')

        # Check home team edge
        home_edge = home.get('edge', {})
        if home_edge.get('abs_edge', 0) >= 5:
            alerts.append({
                'team': home.get('team', ''),
                'opponent': away.get('team', ''),
                'side': 'Home',
                'poly_prob': home.get('poly_prob'),
                'book_prob': home.get('book_prob'),
                'edge': home_edge.get('edge'),
                'signal': home_edge.get('signal', 'none'),
                'direction': home_edge.get('direction', ''),
                'description': home_edge.get('description', ''),
                'game_time': game_time,
                'has_injury': home.get('has_key_injury', False),
                'is_b2b': home.get('is_b2b', False),
            })

        # Check away team edge
        away_edge = away.get('edge', {})
        if away_edge.get('abs_edge', 0) >= 5:
            alerts.append({
                'team': away.get('team', ''),
                'opponent': home.get('team', ''),
                'side': 'Away',
                'poly_prob': away.get('poly_prob'),
                'book_prob': away.get('book_prob'),
                'edge': away_edge.get('edge'),
                'signal': away_edge.get('signal', 'none'),
                'direction': away_edge.get('direction', ''),
                'description': away_edge.get('description', ''),
                'game_time': game_time,
                'has_injury': away.get('has_key_injury', False),
                'is_b2b': away.get('is_b2b', False),
            })

    # Sort by edge size (biggest first)
    alerts.sort(key=lambda a: abs(a.get('edge', 0) or 0), reverse=True)
    return alerts
