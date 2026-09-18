"""阶段⑥ 观察池：出场当天强制入池 + 预写再入场触发 + 20 日自动清除（W-*）。

实证依据：科士达 9/4 卖 37.02 → 9/14 收复 37.1 → 39.31（错过 +6.2%）；
双环 8/11 离场后 -8.9%（不管不亏）。无跟踪机制时两者事前无法区分。
"""

from __future__ import annotations

import sqlite3
from typing import Dict, List, Optional

import pandas as pd

from . import position as posmod
from . import signal as sigmod

# 出场类型 → 观察池分支
WRONG_KILL = ("STOP_LOSS", "TAKE_PROFIT")     # 错杀/止损型：可快速再入场
TREND_EXIT = ("TREND_EXIT", "TIME_STOP")       # 趋势确认型：休眠至位置复现


def build_trigger(exit_type: str, exit_day_high: Optional[float] = None) -> Dict:
    """按出场类型预写再入场触发条件。"""
    if exit_type in WRONG_KILL:
        return {
            "branch": "WRONG_KILL",
            "recover_price": round(float(exit_day_high), 4) if exit_day_high else None,
            "rule": "收盘价收复出场日最高价，或 位置重判可入 + 信号族复现",
        }
    return {
        "branch": "TREND_EXIT",
        "rule": "休眠，直到重新满足 P1-P4 / M1-M2 位置条件才唤醒",
    }


def add_from_exit(conn: sqlite3.Connection, code: str, exit_type: str,
                  exit_date: str, exit_day_high: Optional[float], params) -> int:
    from ..storage import repo

    trig = build_trigger(exit_type, exit_day_high)
    return repo.add_watch(conn, code, exit_type, trig, exit_date,
                          int(params["WATCH_POOL_DAYS"]))


def check_reentry(conn: sqlite3.Connection, item: sqlite3.Row,
                  kline: pd.DataFrame, params) -> Dict:
    """判定观察池标的是否触发再入场。"""
    from ..storage import repo

    trig = item["reentry_trigger"]
    try:
        import json

        trig = json.loads(trig) if isinstance(trig, str) else trig
    except Exception:  # noqa: BLE001
        trig = {"branch": "TREND_EXIT"}

    res = {"triggered": False, "reason": "", "branch": trig.get("branch")}
    if kline is None or len(kline) < int(params["NEW_STOCK_MIN_DAYS"]):
        res["reason"] = "数据不足"
        return res

    pr = posmod.classify(kline, params)
    res["position"] = pr["position"]
    pos_ok = pr["position"] in posmod.CANDIDATE_OK

    if trig.get("branch") == "WRONG_KILL":
        c_last = float(pd.to_numeric(kline["close"], errors="coerce").iloc[-1])
        rp = trig.get("recover_price")
        if rp and c_last >= float(rp):
            res.update({"triggered": True, "reason": f"收盘{c_last}收复出场日最高价{rp}"})
            return res
        if pos_ok:
            sr = sigmod.evaluate(kline, params)
            if sr.get("valid"):
                res.update({"triggered": True, "reason": "位置重判可入 + 信号族复现"})
                return res
        res["reason"] = "未满足收复价，位置/信号未复现"
        return res

    # TREND_EXIT：仅在位置条件重新满足时唤醒
    if pos_ok:
        res.update({"triggered": True, "reason": f"位置重新可入：{pr['position']}"})
    else:
        res["reason"] = f"位置仍为 {pr['position']}，继续休眠"
    return res


def sweep(conn: sqlite3.Connection, today: str, params) -> List[str]:
    """到期清理 + 触发检查。返回处理摘要。"""
    from ..storage import repo

    notes: List[str] = []
    for item in repo.list_watch(conn, "ACTIVE"):
        entered = item["entered_date"]
        days = int(params["WATCH_POOL_DAYS"])
        # 用简单日期差递减（交易日口径由后续 T11 统计校正）
        try:
            from datetime import date

            d0 = date.fromisoformat(str(entered)[:10])
            d1 = date.fromisoformat(today[:10])
            elapsed = (d1 - d0).days
        except Exception:  # noqa: BLE001
            elapsed = 0
        remain = days - elapsed
        conn.execute("UPDATE watch_pool SET days_remaining=? WHERE id=?",
                     (max(remain, 0), item["id"]))
        if remain <= 0:
            repo.clear_watch(conn, item["id"], today)
            notes.append(f"{item['code']} 入池 {elapsed} 天无触发，已清除")
    conn.commit()
    return notes
