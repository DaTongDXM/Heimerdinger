"""阶段⑥ 出场引擎：按入场时锁定的类型分派规则，盘中禁止换规则（N5）。

判定一律基于收盘数据；输出"次日动作"，不在盘中触发。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Dict, Optional

import pandas as pd

from . import indicators as ind
from . import position as posmod
from . import signal as sigmod

HOLD = "HOLD"
EXIT = "EXIT"
REDUCE_HALF = "REDUCE_HALF"
CONVERT_B = "CONVERT_TO_B"


def _hold_days(kline: pd.DataFrame, since: str) -> int:
    if kline is None or kline.empty:
        return 0
    d = kline["date"].astype(str)
    return int((d > since).sum())


def _already_reduced(conn: sqlite3.Connection, order_id: int) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM exit_record WHERE entry_order_id=? "
        "AND exit_type='TAKE_PROFIT'", (order_id,)).fetchone()
    return bool(row and row["n"] > 0)


def evaluate(conn: sqlite3.Connection, order: sqlite3.Row,
             kline: pd.DataFrame, params) -> Dict:
    """返回 {action, hit_rule, exit_type, detail}。"""
    t = order["trade_type"]
    out = {"action": HOLD, "hit_rule": None, "exit_type": None, "detail": {}}

    if kline is None or len(kline) < 20:
        out["detail"]["reason"] = "数据不足"
        return out

    df = kline.reset_index(drop=True)
    close = pd.to_numeric(df["close"], errors="coerce")
    open_ = pd.to_numeric(df["open"], errors="coerce")
    c_last = float(close.iloc[-1])
    o_last = float(open_.iloc[-1]) if pd.notna(open_.iloc[-1]) else c_last

    created = str(order["created_at"])[:10]
    hold = _hold_days(df, created)
    out["detail"]["hold_days"] = hold
    out["detail"]["close"] = round(c_last, 4)

    if t == "A":
        sl = float(order["stop_loss_price"])
        tp = float(order["first_target_price"])
        if c_last < sl:
            return {"action": EXIT, "hit_rule": "E-A-1", "exit_type": "STOP_LOSS",
                    "detail": {**out["detail"], "stop_loss": sl,
                               "next": "次日开盘清仓"}}
        if c_last >= tp and not _already_reduced(conn, order["id"]):
            return {"action": REDUCE_HALF, "hit_rule": "E-A-2",
                    "exit_type": "TAKE_PROFIT",
                    "detail": {**out["detail"], "target": tp, "next": "到位减半"}}
        if _already_reduced(conn, order["id"]) and c_last < o_last:
            return {"action": EXIT, "hit_rule": "E-A-3", "exit_type": "STOP_LOSS",
                    "detail": {**out["detail"], "open": round(o_last, 4),
                               "next": "剩余仓位跌破当日开盘价，清仓"}}
        if hold >= int(params["TIME_STOP_A"]):
            return {"action": EXIT, "hit_rule": "E-A-4", "exit_type": "TIME_STOP",
                    "detail": {**out["detail"], "next": "3个交易日信号未兑现，无条件离场"}}
        return out

    if t == "B":
        ma5 = ind.ma(close, 5)
        last2 = close.iloc[-2:].to_numpy()
        ma52 = ma5.iloc[-2:].to_numpy()
        if len(last2) == 2 and bool((last2 < ma52).all()):
            return {"action": EXIT, "hit_rule": "E-B-1", "exit_type": "TREND_EXIT",
                    "detail": {**out["detail"], "next": "连续2日收盘破MA5，离场"}}
        entry_px = order["entry_price"]
        if entry_px:
            since = df[df["date"].astype(str) > created]["close"]
            peak = float(pd.to_numeric(since, errors="coerce").max()) if len(since) else float(entry_px)
            if peak > float(entry_px) and c_last <= peak * (1 - float(params["B1"])):
                return {"action": EXIT, "hit_rule": "E-B-2", "exit_type": "TAKE_PROFIT",
                        "detail": {**out["detail"], "peak": round(peak, 4),
                                   "next": f"自最高收盘回撤 {params['B1']}，移动止盈离场"}}
        if hold >= int(params["TIME_STOP_B"]):
            return {"action": EXIT, "hit_rule": "E-B-3", "exit_type": "TIME_STOP",
                    "detail": {**out["detail"], "next": "20个交易日时间止损"}}
        return out

    if t == "C":
        # N7：C 类不使用 KDJ / 5日线 / 盘中分时均线作为触发，仅用固定失效价与时间
        sl = float(order["stop_loss_price"])  # 平台下沿 × 0.98
        if c_last < sl:
            return {"action": EXIT, "hit_rule": "E-C-1", "exit_type": "STOP_LOSS",
                    "detail": {**out["detail"], "invalidate_price": sl,
                               "next": "跌破固定失效价，离场"}}
        if hold >= int(params["TIME_STOP_C"]):
            return {"action": EXIT, "hit_rule": "E-C-2", "exit_type": "TIME_STOP",
                    "detail": {**out["detail"], "next": "20个交易日未突破平台上沿，离场"}}
        return out

    out["detail"]["reason"] = f"未知类型 {t}"
    return out
