import math
from decimal import ROUND_DOWN, Decimal
from typing import Any, Dict, List, Tuple, Union
from prettytable import PrettyTable


def parse_odds(odds_string: str) -> Union[float, None]:
    """
    Parse odds from fraction format to decimal format.

    Args:
        odds_string: Odds in "numerator/denominator" format

    Returns:
        Decimal odds value
    """
    if not odds_string:
        return 0.0
    numerator, denominator = odds_string.split("/")

    if denominator == "0":
        return 0.0

    return float(
        (Decimal(numerator) / Decimal(denominator) + Decimal(1)).quantize(
            Decimal("0.00"), rounding="ROUND_DOWN"
        )
    )


def format_datetime(timestamp: str) -> str:
    """
    Format timestamp string into readable date/time format.

    Args:
        timestamp: 14-character timestamp string (YYYYMMDDHHMMSS)

    Returns:
        Formatted datetime string (DD/MM/YYYY HH:MM:SS)
    """
    if not timestamp:
        return ""
    if len(timestamp) < 14:
        return timestamp

    year = timestamp[0:4]
    month = timestamp[4:6]
    day = timestamp[6:8]
    hour = timestamp[8:10]
    minutes = timestamp[10:12]
    seconds = timestamp[12:14]

    return f"{day}/{month}/{year} {hour}:{minutes}:{seconds}"


def split_list_by_delimiter(items: List[Any], delimiter: Any) -> List[List[Any]]:
    """
    Split a list into sublists based on a delimiter.

    Args:
        items: The list to split
        delimiter: The value to split on

    Returns:
        List of sublists split by the delimiter
    """
    results = []
    items_copy = items.copy()

    while delimiter in items_copy:
        delimiter_index = items_copy.index(delimiter)
        results.append(items_copy[:delimiter_index])
        items_copy = items_copy[delimiter_index + 1 :]

    if items_copy:  # Add remaining items
        results.append(items_copy)

    return results


def hook_function(on):
    def wrapper(fn):
        def wrapper2(*args, **kwargs):
            ret_value = fn(*args, **kwargs)
            on(*[args[0], ret_value], **kwargs)
            return ret_value

        return wrapper2

    return wrapper



def pretty_print_table(table: Dict[str, Any], zap) -> None:
    data = table["data"]
    if not data or not data[0]["values"]:
        return
    keys = [col["name"] for col in data]
    pt = PrettyTable(keys)
    for i in range(len(data[0]["values"])):
        row = [data[0]["values"][i].get_property("FD")]
        for j in range(1, len(data)):
            odd_node = data[j]["values"][i]
            odd_fractional = odd_node.get_property("OD")

            decimal_odd = zap.apply_price_variance(parse_odds(odd_fractional), odd_node) if zap else parse_odds(odd_fractional)
            row.append(f"{decimal_odd:0.2f} {odd_fractional}")
        pt.add_row(row)
    import os
    os.system("cls" if os.name == "nt" else "clear")
    print(pt)