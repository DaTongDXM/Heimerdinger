"""阶段⑤ 入场单生成（P0-11：缺一项不开仓）。

第 0-7 项中，只有"目标价/止损价定价"需要人工判断（规范 §0），
其余由系统从扫描结果自动填充并强制校验。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from ..config import Params
from ..storage import repo

# 各类型的固定字段（按规范 §4.2，入场时锁定，盘中不可改）
TYPE_DEFAULTS = {
    "A": {"remainder_protection": "跌破当日开盘价", "time_stop_days": "TIME_STOP_A",
          "layers": 1},
    "B": {"remainder_protection": "连续2日收盘破MA5", "time_stop_days": "TIME_STOP_B",
          "layers": 1},
    "C": {"remainder_protection": "跌破固定失效价", "time_stop_days": "TIME_STOP_C",
          "layers": 2},
}


def build_from_scan(conn: sqlite3.Connection, code: str, trade_type: str,
                    params: Params, scan_date: Optional[str] = None,
                    entry_price: Optional[float] = None,
                    stop_loss_price: Optional[float] = None,
                    first_target_price: Optional[float] = None,
                    observed_facts: str = "",
                    structure_position: Optional[str] = None) -> Dict:
    """从当日扫描结果生成入场单骨架（止损/目标由人工填，其余自动带出）。"""
    row = conn.execute(
        "SELECT * FROM scan_result WHERE code=? ORDER BY scan_date DESC LIMIT 1",
        (code,)).fetchone()
    if not row:
        raise ValueError(f"{code} 无扫描结果，请先运行 scan")

    t = trade_type.upper()
    d = TYPE_DEFAULTS[t]
    pos_map = {"BOTTOM_REVERSAL": "底部反转", "PULLBACK_UPTREND": "多头回踩",
               "V_SHAPE": "V型减半", "DOWNTREND_CONTINUATION": "下跌中继(禁入)"}
    if row["position"] == "DOWNTREND_CONTINUATION":
        raise ValueError("N4: 下跌中继禁止生成入场单")

    return {
        "code": code,
        "name": row["name"],
        "scan_date": row["scan_date"],
        "trade_type": t,
        "structure_position": structure_position or pos_map.get(row["position"], row["position"]),
        "observed_facts": observed_facts,
        "stop_loss_price": stop_loss_price,
        "first_target_price": first_target_price,
        "remainder_protection": d["remainder_protection"],
        "time_stop_days": int(params[d["time_stop_days"]]),
        "self_check_pass": True,  # 提交时由冷却检查覆写
        "entry_price": entry_price,
        "layers": d["layers"],
        "_ref": {"platform_top": row["ref_platform_top"],
                 "platform_bottom": row["ref_platform_bottom"],
                 "ma20": row["ref_ma20"],
                 "prev_close": row["ref_prev_close"]},
    }


def submit(conn: sqlite3.Connection, order: Dict, params: Params
           ) -> Tuple[bool, Optional[int], List[str]]:
    """提交入场单：先做 N6 冷却自检，再走 8 项强制校验并落库。"""
    last_close = repo.last_profit_close_time(conn)
    allowed, remain = None, None
    from .. import guard

    allowed, remain = guard.check_cooldown(last_close, datetime.now(),
                                           int(params["COOLDOWN_MINUTES"]))
    order = dict(order)
    order["self_check_pass"] = bool(allowed)
    ok, oid, errors = repo.save_entry_order(conn, order, params, last_close)
    if not ok and any("N6" in e for e in errors):
        repo.log_violation(conn, "N6", order.get("code"),
                           f"盈利平仓后 {remain} 分钟内尝试开仓，已拦截")
    return ok, oid, errors
