"""阶段① D-3：日线增量缓存（SQLite）。

有缓存 → 只拉最近 INCREMENTAL_DAYS + 当日；无缓存 → 全量拉 HISTORY_DAYS。
前复权为滚动复权口径：绝对价仅用于当次运行，禁止跨日缓存后比较（D-1）。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

import pandas as pd

from . import data_source


def get_latest_date(conn: sqlite3.Connection, code: str) -> Optional[str]:
    row = conn.execute(
        "SELECT MAX(date) AS d FROM daily_kline WHERE code=?", (code,)
    ).fetchone()
    return row["d"] if row and row["d"] else None


def kline_lengths(conn: sqlite3.Connection) -> Dict[str, int]:
    rows = conn.execute("SELECT code, COUNT(*) AS n FROM daily_kline GROUP BY code").fetchall()
    return {r["code"]: r["n"] for r in rows}


def upsert_kline(conn: sqlite3.Connection, code: str, df: pd.DataFrame, adjust: str = "qfq") -> int:
    """写入日线（主键冲突则覆盖，保证复权口径刷新）。返回写入行数。"""
    if df is None or df.empty:
        return 0
    payload = [
        (code, r["date"], r["open"], r["high"], r["low"], r["close"], r["vol"], adjust)
        for _, r in df.iterrows()
    ]
    conn.executemany(
        "INSERT INTO daily_kline(code,date,open,high,low,close,vol,adjust) "
        "VALUES (?,?,?,?,?,?,?,?) "
        "ON CONFLICT(code,date) DO UPDATE SET open=excluded.open, high=excluded.high, "
        "low=excluded.low, close=excluded.close, vol=excluded.vol, adjust=excluded.adjust",
        payload,
    )
    conn.commit()
    return len(payload)


def load_kline(conn: sqlite3.Connection, code: str, limit: Optional[int] = None) -> pd.DataFrame:
    """读取日线，按日期升序返回。

    注意：limit 指"最近 N 条"，不能写成 `ORDER BY date LIMIT N`（那会取最早的 N 条）。
    """
    if limit:
        sql = ("SELECT date,open,high,low,close,vol FROM ("
               "SELECT date,open,high,low,close,vol FROM daily_kline "
               "WHERE code=? ORDER BY date DESC LIMIT ?) ORDER BY date")
        df = pd.read_sql_query(sql, conn, params=(code, int(limit)))
    else:
        sql = ("SELECT date,open,high,low,close,vol FROM daily_kline "
               "WHERE code=? ORDER BY date")
        df = pd.read_sql_query(sql, conn, params=(code,))
    if not df.empty:
        for c in ("open", "high", "low", "close", "vol"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def _fmt(d: datetime) -> str:
    return d.strftime("%Y%m%d")


def update_symbol(conn: sqlite3.Connection, code: str, params,
                  end: Optional[datetime] = None,
                  force_full: bool = False) -> Tuple[str, int, str]:
    """增量或全量更新单只股票。

    返回 (status, rows, source)；status ∈ {full, incremental, failed, uptodate}
    """
    end = end or datetime.today()
    latest = get_latest_date(conn, code)
    if not force_full and latest:
        start_dt = datetime.strptime(latest, "%Y-%m-%d") - timedelta(days=1)
        mode = "incremental"
    else:
        start_dt = end - timedelta(days=int(params["HISTORY_DAYS"] * 1.6))  # 自然日≈交易日×1.6
        mode = "full"

    df, source, err = data_source.fetch_with_fallback(
        code, _fmt(start_dt), _fmt(end),
        max_retry=int(params["MAX_RETRY"]),
        adjust="qfq",
    )
    if df is None:
        return "failed", 0, err or "unknown"
    rows = upsert_kline(conn, code, df)
    return mode, rows, source


def fetch_all(conn: sqlite3.Connection, codes, params, end=None,
              force_full: bool = False, progress=None, on_fail=None):
    """批量更新。返回统计 dict。"""
    from . import data_source as ds

    stats = {"full": 0, "incremental": 0, "failed": 0, "rows": 0, "failed_codes": []}
    total = len(codes)
    for i, code in enumerate(codes, 1):
        status, rows, source = update_symbol(conn, code, params, end=end, force_full=force_full)
        stats[status] = stats.get(status, 0) + 1
        stats["rows"] += rows
        if status == "failed":
            stats["failed_codes"].append({"code": code, "error": source})
            if on_fail:
                on_fail(code, source)
        if progress and (i % 50 == 0 or i == total):
            progress(i, total, status)
        ds.throttle(params)
    return stats
