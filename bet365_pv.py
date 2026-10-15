"""
Bet365 France Price Variance (PV) Regulatory Deduction Engine
============================================================
Implements the exact Price Variance calculation used by Bet365 France (bet365.fr)
under ANJ / ARJEL regulatory rate ceilings (Taux de Retour aux Joueurs - TRJ).

Matches window.PriceVarianceLib / lib.pvOdds.getAdjustmentValue()
from Bet365's live client-side JavaScript engine.
"""

import json
import os
from typing import Any, Dict, List, Optional, Union

CHARTS_FILE = os.path.join(os.path.dirname(__file__), "bet365_pv_charts.json")

# Embedded fallback for PV_CHARTS~9 (Default standard chart on bet365.fr)
_EMBEDDED_CHART_9 = [
    {
        "UR": 1.001,
        "LR": 1,
        "PV": 0
    },
    {
        "UR": 1.002,
        "LR": 1.001,
        "PV": 0
    },
    {
        "UR": 1.003,
        "LR": 1.002,
        "PV": 0.001
    },
    {
        "UR": 1.004,
        "LR": 1.003,
        "PV": 0.0015
    },
    {
        "UR": 1.006,
        "LR": 1.004,
        "PV": 0.003
    },
    {
        "UR": 1.008,
        "LR": 1.006,
        "PV": 0.004
    },
    {
        "UR": 1.01,
        "LR": 1.008,
        "PV": 0.006
    },
    {
        "UR": 1.015,
        "LR": 1.01,
        "PV": 0.008
    },
    {
        "UR": 1.02,
        "LR": 1.015,
        "PV": 0.012
    },
    {
        "UR": 1.025,
        "LR": 1.02,
        "PV": 0.015
    },
    {
        "UR": 1.03,
        "LR": 1.025,
        "PV": 0.017
    },
    {
        "UR": 1.04,
        "LR": 1.03,
        "PV": 0.02
    },
    {
        "UR": 1.05,
        "LR": 1.04,
        "PV": 0.025
    },
    {
        "UR": 1.06,
        "LR": 1.05,
        "PV": 0.03
    },
    {
        "UR": 1.08,
        "LR": 1.06,
        "PV": 0.04
    },
    {
        "UR": 1.1,
        "LR": 1.08,
        "PV": 0.05
    },
    {
        "UR": 1.12,
        "LR": 1.1,
        "PV": 0.06
    },
    {
        "UR": 1.15,
        "LR": 1.12,
        "PV": 0.07
    },
    {
        "UR": 1.2,
        "LR": 1.15,
        "PV": 0.08
    },
    {
        "UR": 1.25,
        "LR": 1.2,
        "PV": 0.09
    },
    {
        "UR": 1.3,
        "LR": 1.25,
        "PV": 0.09
    },
    {
        "UR": 1.35,
        "LR": 1.3,
        "PV": 0.09
    },
    {
        "UR": 1.4,
        "LR": 1.35,
        "PV": 0.09
    },
    {
        "UR": 1.45,
        "LR": 1.4,
        "PV": 0.09
    },
    {
        "UR": 1.5,
        "LR": 1.45,
        "PV": 0.09
    },
    {
        "UR": 1.55,
        "LR": 1.5,
        "PV": 0.1
    },
    {
        "UR": 1.6,
        "LR": 1.55,
        "PV": 0.1
    },
    {
        "UR": 1.7,
        "LR": 1.6,
        "PV": 0.1
    },
    {
        "UR": 1.8,
        "LR": 1.7,
        "PV": 0.1
    },
    {
        "UR": 1.9,
        "LR": 1.8,
        "PV": 0.1
    },
    {
        "UR": 2,
        "LR": 1.9,
        "PV": 0.1
    },
    {
        "UR": 2.1,
        "LR": 2,
        "PV": 0.1
    },
    {
        "UR": 2.2,
        "LR": 2.1,
        "PV": 0.12
    },
    {
        "UR": 2.3,
        "LR": 2.2,
        "PV": 0.12
    },
    {
        "UR": 2.4,
        "LR": 2.3,
        "PV": 0.15
    },
    {
        "UR": 2.5,
        "LR": 2.4,
        "PV": 0.15
    },
    {
        "UR": 2.6,
        "LR": 2.5,
        "PV": 0.15
    },
    {
        "UR": 2.7,
        "LR": 2.6,
        "PV": 0.15
    },
    {
        "UR": 2.8,
        "LR": 2.7,
        "PV": 0.15
    },
    {
        "UR": 2.9,
        "LR": 2.8,
        "PV": 0.18
    },
    {
        "UR": 3,
        "LR": 2.9,
        "PV": 0.18
    },
    {
        "UR": 3.2,
        "LR": 3,
        "PV": 0.18
    },
    {
        "UR": 3.4,
        "LR": 3.2,
        "PV": 0.2
    },
    {
        "UR": 3.6,
        "LR": 3.4,
        "PV": 0.2
    },
    {
        "UR": 3.8,
        "LR": 3.6,
        "PV": 0.25
    },
    {
        "UR": 4,
        "LR": 3.8,
        "PV": 0.25
    },
    {
        "UR": 4.5,
        "LR": 4,
        "PV": 0.28
    },
    {
        "UR": 5,
        "LR": 4.5,
        "PV": 0.28
    },
    {
        "UR": 5.5,
        "LR": 5,
        "PV": 0.3
    },
    {
        "UR": 6,
        "LR": 5.5,
        "PV": 0.4
    },
    {
        "UR": 6.5,
        "LR": 6,
        "PV": 0.5
    },
    {
        "UR": 7,
        "LR": 6.5,
        "PV": 0.6
    },
    {
        "UR": 8,
        "LR": 7,
        "PV": 0.8
    },
    {
        "UR": 9,
        "LR": 8,
        "PV": 1
    },
    {
        "UR": 11,
        "LR": 9,
        "PV": 1.5
    },
    {
        "UR": 13,
        "LR": 11,
        "PV": 2
    },
    {
        "UR": 15,
        "LR": 13,
        "PV": 2.5
    },
    {
        "UR": 17,
        "LR": 15,
        "PV": 3
    },
    {
        "UR": 19,
        "LR": 17,
        "PV": 3.5
    },
    {
        "UR": 21,
        "LR": 19,
        "PV": 4
    },
    {
        "UR": 26,
        "LR": 21,
        "PV": 4.5
    },
    {
        "UR": 31,
        "LR": 26,
        "PV": 5
    },
    {
        "UR": 41,
        "LR": 31,
        "PV": 6.5
    },
    {
        "UR": 51,
        "LR": 41,
        "PV": 7
    },
    {
        "UR": 61,
        "LR": 51,
        "PV": 8
    },
    {
        "UR": 71,
        "LR": 61,
        "PV": 9
    },
    {
        "UR": 81,
        "LR": 71,
        "PV": 10
    },
    {
        "UR": 91,
        "LR": 81,
        "PV": 15
    },
    {
        "UR": 101,
        "LR": 91,
        "PV": 20
    },
    {
        "UR": 121,
        "LR": 101,
        "PV": 25
    },
    {
        "UR": 151,
        "LR": 121,
        "PV": 30
    },
    {
        "UR": 201,
        "LR": 151,
        "PV": 35
    },
    {
        "UR": 351,
        "LR": 201,
        "PV": 40
    },
    {
        "UR": 501,
        "LR": 351,
        "PV": 50
    },
    {
        "UR": 751,
        "LR": 501,
        "PV": 60
    },
    {
        "UR": 1001,
        "LR": 751,
        "PV": 75
    },
    {
        "UR": 10001,
        "LR": 1001,
        "PV": 100
    }
]

_CHARTS_CACHE: Dict[str, List[Dict[str, float]]] = {}


def load_charts() -> Dict[str, List[Dict[str, float]]]:
    global _CHARTS_CACHE
    if _CHARTS_CACHE:
        return _CHARTS_CACHE

    if os.path.exists(CHARTS_FILE):
        try:
            with open(CHARTS_FILE, "r", encoding="utf-8") as f:
                _CHARTS_CACHE = json.load(f)
                return _CHARTS_CACHE
        except Exception:
            pass

    _CHARTS_CACHE = {"PV_CHARTS~9": _EMBEDDED_CHART_9}
    return _CHARTS_CACHE


def get_pv_adjustment(raw_decimal: float, chart_id: str = "6") -> float:
    """
    Returns the exact ANJ Price Variance adjustment value (deduction amount)
    for a given raw decimal odd, matching lib.pvOdds.getAdjustmentValue().
    """
    charts = load_charts()
    chart_key = f"PV_CHARTS~{chart_id}"
    chart = charts.get(chart_key) or charts.get("PV_CHARTS~6") or charts.get("PV_CHARTS~9") or _EMBEDDED_CHART_9

    for row in chart:
        lr = row.get("LR", 0.0)
        ur = row.get("UR", 0.0)
        if lr <= raw_decimal <= ur:
            return float(row.get("PV", 0.0))

    return 0.0


def apply_bet365_pv(val: Any, chart_id: str = "6") -> float:
    """
    Applies the Bet365 France Price Variance deduction to convert raw CDP odds
    into the exact on-screen odds displayed to French users on bet365.fr.
    
    Default chart is Chart 6 (the active French regulatory TRJ standard for Soccer).
    Example with Chart 6:
        raw 2.90 -> PV deduction 0.08 -> 2.82
        raw 3.50 -> PV deduction 0.10 -> 3.40
        raw 2.35 -> PV deduction 0.06 -> 2.29
    """
    try:
        raw_dec = float(str(val).replace(",", ".").strip())
    except (ValueError, TypeError):
        return 1.0

    if raw_dec <= 1.01:
        return 1.01

    pv_adj = get_pv_adjustment(raw_dec, chart_id=chart_id)
    adjusted = raw_dec - pv_adj

    # Bet365 rules: minimum on-screen odd is 1.01
    adjusted = max(1.01, adjusted)

    # Bet365 precision rules: 3 decimal places if odd < 1.10, otherwise 2 decimal places
    if adjusted < 1.10:
        return round(adjusted, 3)
    return round(adjusted, 2)


def format_french_odd(val: Any, chart_id: str = "6") -> str:
    """
    Converts and formats a raw odd directly into the French on-screen string representation.
    """
    adj = apply_bet365_pv(val, chart_id=chart_id)
    return f"{adj:.2f}"
