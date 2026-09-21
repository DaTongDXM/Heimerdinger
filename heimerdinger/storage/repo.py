"""存储层读写封装。

关键约束：
- entry_order 为 append-only：本模块不提供任何 UPDATE 入口（N5 类型锁定）。
- 出场后强制写 exit_record 并进入观察池。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from .. import guard
from ..config import Params


# ---------------------------------------------------------------------------
# 入场单
# ---------------------------------------------------------------------------
def save_entry_order(conn: sqlite3.Connection, order: Dict, params: Params,
                     last_profit_close_at: Optional[datetime] = None
                     ) -> Tuple[bool, Optional[int], List[str]]:
    """校验 8 项后写入。返回 (是否成功, 订单ID, 错误列表)。"""
    ok, errors = guard.validate_entry_order(order, params, last_profit_close_at)
    if not ok:
        return False, None, errors

    cur = conn.execute(
        "INSERT INTO entry_order(code,name,scan_date,trade_type,structure_position,"
        "observed_facts,stop_loss_price,first_target_price,remainder_protection,"
        "time_stop_days,self_check_pass,entry_price,layers,status,created_at,param_version) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (order["code"], order.get("name"), order.get("scan_date"),
         order["trade_type"], order["structure_position"], order["observed_facts"],
         float(order["stop_loss_price"]), float(order["first_target_price"]),
         order["remainder_protection"], int(order["time_stop_days"]),
         1 if order.get("self_check_pass") else 0,
         order.get("entry_price"), int(order.get("layers", 1)), "OPEN",
         datetime.now().isoformat(timespec="seconds"), params.version),
    )
    conn.commit()
    return True, cur.lastrowid, []


def get_open_orders(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM entry_order WHERE status='OPEN' ORDER BY id").fetchall()


def get_order(conn: sqlite3.Connection, order_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM entry_order WHERE id=?", (order_id,)).fetchone()


def update_order_status(conn: sqlite3.Connection, order_id: int, status: str) -> None:
    """仅允许改状态字段（OPEN/CLOSED），业务字段一律不改。"""
    conn.execute("UPDATE entry_order SET status=? WHERE id=?", (status, order_id))
    conn.commit()


def last_profit_close_time(conn: sqlite3.Connection) -> Optional[datetime]:
    """最近一次盈利平仓时间（用于 N6 冷却）。"""
    row = conn.execute(
        "SELECT exit_date FROM exit_record WHERE exit_type='TAKE_PROFIT' "
        "ORDER BY id DESC LIMIT 1").fetchone()
    if not row:
        return None
    try:
        return datetime.fromisoformat(row["exit_date"])
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# 出场
# ---------------------------------------------------------------------------
def save_exit(conn: sqlite3.Connection, order_id: int, exit_date: str,
              exit_price: float, hold_days: int, exit_type: str,
              hit_rule: str, is_planned: int = 1) -> int:
    order = get_order(conn, order_id)
    entry_price = order["entry_price"] if order and order["entry_price"] else None
    pnl = None
    if entry_price:
        pnl = (float(exit_price) - float(entry_price)) / float(entry_price)
    cur = conn.execute(
        "INSERT INTO exit_record(entry_order_id,exit_date,exit_price,hold_days,"
        "exit_type,hit_rule,is_planned,pnl_pct) VALUES (?,?,?,?,?,?,?,?)",
        (order_id, exit_date, float(exit_price), hold_days, exit_type,
         hit_rule, is_planned, pnl))
    update_order_status(conn, order_id, "CLOSED")
    conn.commit()
    return cur.lastrowid


# ---------------------------------------------------------------------------
# 观察池
# ---------------------------------------------------------------------------
def save_partial_exit(conn: sqlite3.Connection, order_id: int, exit_date: str,
                      exit_price: float, hold_days: int, hit_rule: str) -> int:
    """A 类"到位减半"：记录部分出场但**不关单**，剩余仓位继续按规则管理。"""
    order = get_order(conn, order_id)
    entry_price = order["entry_price"] if order and order["entry_price"] else None
    pnl = None
    if entry_price:
        pnl = (float(exit_price) - float(entry_price)) / float(entry_price)
    cur = conn.execute(
        "INSERT INTO exit_record(entry_order_id,exit_date,exit_price,hold_days,"
        "exit_type,hit_rule,is_planned,pnl_pct) VALUES (?,?,?,?,?,?,?,?)",
        (order_id, exit_date, float(exit_price), hold_days, "TAKE_PROFIT",
         hit_rule, 1, pnl))
    conn.commit()
    return cur.lastrowid


def add_watch(conn: sqlite3.Connection, code: str, source_exit_type: str,
              reentry_trigger: Dict, entered_date: str, days: int) -> int:
    cur = conn.execute(
        "INSERT INTO watch_pool(code,source_exit_type,reentry_trigger,status,"
        "entered_date,days_remaining) VALUES (?,?,?,?,?,?)",
        (code, source_exit_type, json.dumps(reentry_trigger, ensure_ascii=False),
         "ACTIVE", entered_date, days))
    conn.commit()
    return cur.lastrowid


def list_watch(conn: sqlite3.Connection, status: str = "ACTIVE") -> List[sqlite3.Row]:
    return conn.execute("SELECT * FROM watch_pool WHERE status=? ORDER BY id",
                        (status,)).fetchall()


def clear_watch(conn: sqlite3.Connection, watch_id: int, cleared_date: str) -> None:
    conn.execute("UPDATE watch_pool SET status='CLEARED', cleared_date=?, days_remaining=0 "
                 "WHERE id=?", (cleared_date, watch_id))
    conn.commit()


def trigger_watch(conn: sqlite3.Connection, watch_id: int) -> None:
    conn.execute("UPDATE watch_pool SET status='TRIGGERED', days_remaining=0 WHERE id=?",
                 (watch_id,))
    conn.commit()


def log_violation(conn: sqlite3.Connection, rule_id: str, code: Optional[str],
                  detail: str) -> None:
    conn.execute(
        "INSERT INTO violation_log(date,rule_id,code,detail) VALUES (?,?,?,?)",
        (datetime.today().strftime("%Y-%m-%d"), rule_id, code, detail))
    conn.commit()
