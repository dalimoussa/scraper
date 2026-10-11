"""
Odds History Tracker & Time-Series Engine (SQLite)
==================================================
Tracks live odds fluctuations across scraping cycles and records chronological price movements
in a lightweight local SQLite database (odds_history.db).
"""

import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


DB_PATH_DEFAULT = "odds_history.db"


def get_db_connection(db_path: str = DB_PATH_DEFAULT) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_history_db(db_path: str = DB_PATH_DEFAULT) -> None:
    """Initializes the historical odds table and indices if they do not exist."""
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS odds_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                match_id TEXT NOT NULL,
                sport TEXT NOT NULL,
                competition TEXT NOT NULL,
                home TEXT NOT NULL,
                away TEXT NOT NULL,
                market TEXT NOT NULL,
                selection TEXT NOT NULL,
                line TEXT,
                odds TEXT NOT NULL
            );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_match_mkt ON odds_history (match_id, market, selection);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_time ON odds_history (timestamp);")
        conn.commit()
    finally:
        conn.close()


def record_odds_snapshot(dataset: List[Dict[str, Any]], db_path: str = DB_PATH_DEFAULT) -> int:
    """
    Scans the scraped dataset and records any new or changed odds into SQLite.
    Returns the total number of newly recorded price updates.
    """
    init_history_db(db_path)
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    updates_count = 0

    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()

        # Fetch latest recorded odds map to avoid duplicate rows for unchanged prices
        cursor.execute("""
            SELECT match_id, market, selection, odds
            FROM odds_history
            WHERE id IN (
                SELECT MAX(id)
                FROM odds_history
                GROUP BY match_id, market, selection
            )
        """)
        latest_cache: Dict[Tuple[str, str, str], str] = {
            (row["match_id"], row["market"], row["selection"]): row["odds"]
            for row in cursor.fetchall()
        }

        insert_batch = []
        for sport_group in dataset:
            sport = sport_group.get("sport", "")
            matches = sport_group.get("matches", [])
            for m in matches:
                m_id = m.get("id", "")
                comp = m.get("competition", "")
                home = m.get("home", "")
                away = m.get("away", "")
                markets = m.get("markets", {})

                for mkt_name, mkt_data in markets.items():
                    if not isinstance(mkt_data, dict):
                        continue
                    for sel_name, val in mkt_data.items():
                        line_val = None
                        if isinstance(val, dict):
                            odd_val = str(val.get("odds", "")).strip()
                            line_val = str(val.get("line", "")).strip() if "line" in val else None
                        else:
                            odd_val = str(val).strip()

                        if not odd_val:
                            continue

                        cache_key = (m_id, mkt_name, sel_name)
                        prev_odd = latest_cache.get(cache_key)

                        # Only insert if price changed or first observation
                        if prev_odd != odd_val:
                            insert_batch.append((
                                now_utc, m_id, sport, comp, home, away,
                                mkt_name, sel_name, line_val, odd_val
                            ))
                            latest_cache[cache_key] = odd_val
                            updates_count += 1

        if insert_batch:
            cursor.executemany("""
                INSERT INTO odds_history (
                    timestamp, match_id, sport, competition, home, away,
                    market, selection, line, odds
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, insert_batch)
            conn.commit()
    finally:
        conn.close()

    return updates_count


def get_odds_movement(match_id: str, market: Optional[str] = None, db_path: str = DB_PATH_DEFAULT) -> List[Dict[str, Any]]:
    """Retrieves chronological price movements for a given match and market."""
    if not os.path.exists(db_path):
        return []
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        if market:
            cursor.execute("""
                SELECT timestamp, market, selection, line, odds
                FROM odds_history
                WHERE match_id = ? AND market = ?
                ORDER BY id ASC
            """, (match_id, market))
        else:
            cursor.execute("""
                SELECT timestamp, market, selection, line, odds
                FROM odds_history
                WHERE match_id = ?
                ORDER BY id ASC
            """, (match_id,))
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()
