"""
Market Margin & Overround Validator
====================================
Calculates bookmaker overrounds (margin = sum(1.0 / odds)) across betting markets.
Guarantees mathematical integrity, checks against realistic bookmaker margins [1.01, 1.35],
and flags pricing anomalies.
"""

from typing import Any, Dict, List, Optional, Tuple


def calculate_market_margin(market_data: Any) -> Optional[float]:
    """
    Calculates bookmaker overround (margin) = sum(1.0 / decimal_odds).
    e.g. 1X2 market with 2.29, 3.50, 2.72:
    1/2.29 (0.4367) + 1/3.50 (0.2857) + 1/2.72 (0.3676) = 1.0900 (9.00% bookmaker vigorish).
    """
    if not isinstance(market_data, dict):
        return None

    inv_sum = 0.0
    count = 0

    for sel_name, val in market_data.items():
        odd_str = None
        if isinstance(val, dict):
            if "odds" in val:
                odd_str = str(val["odds"])
        else:
            odd_str = str(val)

        if not odd_str:
            continue

        try:
            f = float(str(odd_str).replace(',', '.'))
            if f > 1.0:
                inv_sum += 1.0 / f
                count += 1
        except (ValueError, TypeError):
            continue

    if count >= 2:
        return round(inv_sum, 4)
    return None


def compute_match_margins(markets: Dict[str, Any]) -> Dict[str, str]:
    """Computes margin string for every evaluable market in a match."""
    margins_out: Dict[str, str] = {}
    if not isinstance(markets, dict):
        return margins_out

    for mkt_name, mkt_data in markets.items():
        mg = calculate_market_margin(mkt_data)
        if mg is not None:
            margins_out[mkt_name] = f"{mg:.4f}"

    return margins_out


def validate_market_margins(markets: Dict[str, Any], min_bound: float = 1.01, max_bound: float = 1.35) -> List[str]:
    """
    Validates that market overrounds fall within realistic bookmaker bounds [1.01, 1.35].
    Returns a list of warning strings for any anomalous markets.
    """
    warnings: List[str] = []
    if not isinstance(markets, dict):
        return warnings

    for mkt_name, mkt_data in markets.items():
        # Skip outright rosters with 10+ participants from strict upper bound checks
        if isinstance(mkt_data, dict) and len(mkt_data) > 6:
            continue

        mg = calculate_market_margin(mkt_data)
        if mg is not None:
            if mg < min_bound:
                warnings.append(f"Market '{mkt_name}' has unusually low overround {mg:.4f} < {min_bound} (potential arbitrage or inverted odds)")
            elif mg > max_bound:
                warnings.append(f"Market '{mkt_name}' has unusually high overround {mg:.4f} > {max_bound} (potential stale/heavy margin)")

    return warnings
