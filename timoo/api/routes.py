"""API 路由：只读为主 + 入场单写入。

统一响应：{"code": 200, "message": "success", "data": ...}
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
from fastapi import APIRouter

from ..config import DEFAULT as P
from ..pipeline import cleaner, entry_order, exit_engine, watch_pool
from ..storage import db, repo
from ..pipeline import cache as kcache

ROOT = Path(__file__).resolve().parents[2]
router = APIRouter(prefix="/api")


def _conn():
    conn = db.connect()
    db.init_db(conn)
    return conn


def ok(data=None, message: str = "success"):
    return {"code": 200, "message": message, "data": data}


def err(message: str, code: int = 400):
    return {"code": code, "message": message, "data": None}


# ---------------------------------------------------------------------------
# 扫描与候选
# ---------------------------------------------------------------------------
@router.get("/scan/result")
def scan_result(date: Optional[str] = None, candidates_only: bool = False):
    conn = _conn()
    try:
        if not date:
            row = conn.execute("SELECT MAX(scan_date) AS d FROM scan_result").fetchone()
            date = row["d"] if row else None
        if not date:
            return ok({"scan_date": None, "rows": []})
        sql = ("SELECT * FROM scan_result WHERE scan_date=?"
               + (" AND is_candidate=1" if candidates_only else "")
               + " ORDER BY is_candidate DESC, code")
        rows = [dict(r) for r in conn.execute(sql, (date,)).fetchall()]
        counts = {}
        for r in rows:
            counts[r["position"]] = counts.get(r["position"], 0) + 1
        return ok({"scan_date": date, "counts": counts, "rows": rows})
    finally:
        conn.close()


@router.get("/candidates")
def candidates(date: Optional[str] = None):
    if not date:
        date = datetime.today().strftime("%Y-%m-%d")
    for f in (ROOT / "data" / "candidates").glob(f"{date}*.json"):
        return ok(json.loads(f.read_text(encoding="utf-8")))
    return err(f"{date} 无候选清单，请先运行 scan", code=404)


@router.get("/stock/{code}/diagnose")
def diagnose(code: str):
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT * FROM scan_result WHERE code=? ORDER BY scan_date DESC LIMIT 1",
            (code,)).fetchone()
        uni = conn.execute(
            "SELECT * FROM universe_snapshot WHERE code=? "
            "ORDER BY date DESC LIMIT 1", (code,)).fetchone()
        n = conn.execute("SELECT COUNT(*) AS n FROM daily_kline WHERE code=?",
                         (code,)).fetchone()
        return ok({
            "code": code,
            "in_universe": bool(uni and uni["in_universe"]),
            "exclude_reason": uni["exclude_reason"] if uni else None,
            "kline_days": n["n"] if n else 0,
            "last_scan": dict(row) if row else None,
        })
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 入场单
# ---------------------------------------------------------------------------
@router.get("/entry-orders")
def list_orders(status: str = "OPEN"):
    conn = _conn()
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM entry_order WHERE status=? ORDER BY id DESC", (status,)).fetchall()]
        return ok(rows)
    finally:
        conn.close()


@router.post("/entry-order")
def create_order(body: dict):
    required = ["code", "trade_type", "stop_loss_price", "first_target_price"]
    missing = [k for k in required if body.get(k) in (None, "")]
    if missing:
        return err(f"缺少必填字段: {missing}")
    conn = _conn()
    try:
        try:
            order = entry_order.build_from_scan(
                conn, str(body["code"]), str(body["trade_type"]).upper(), P,
                entry_price=body.get("entry_price"),
                stop_loss_price=float(body["stop_loss_price"]),
                first_target_price=float(body["first_target_price"]),
                observed_facts=str(body.get("observed_facts", "")))
        except ValueError as e:
            return err(str(e))
        ok_flag, oid, errors = entry_order.submit(conn, order, P)
        if not ok_flag:
            return err("；".join(errors))
        return ok({"id": oid, "order": {k: v for k, v in order.items() if not k.startswith("_")}})
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 持仓与出场
# ---------------------------------------------------------------------------
@router.get("/holdings")
def holdings():
    conn = _conn()
    try:
        out = []
        for o in repo.get_open_orders(conn):
            kline = cleaner.clean(
                kcache.load_kline(conn, o["code"], limit=int(P["HISTORY_DAYS"])))
            act = exit_engine.evaluate(conn, o, kline, P)
            out.append({"order": dict(o), "action": act})
        return ok(out)
    finally:
        conn.close()


@router.post("/holdings/{order_id}/exit")
def confirm_exit(order_id: int, body: dict):
    conn = _conn()
    try:
        o = repo.get_order(conn, order_id)
        if not o or o["status"] != "OPEN":
            return err(f"订单 #{order_id} 不存在或已关闭")
        kline = cleaner.clean(
            kcache.load_kline(conn, o["code"], limit=int(P["HISTORY_DAYS"])))
        act = exit_engine.evaluate(conn, o, kline, P)
        today = datetime.today().strftime("%Y-%m-%d")
        close = float(pd.to_numeric(kline["close"]).iloc[-1]) if len(kline) else 0.0
        high = float(pd.to_numeric(kline["high"]).iloc[-1]) if len(kline) else None
        exit_price = body.get("exit_price") or close
        if act["action"] == "EXIT":
            repo.save_exit(conn, order_id, today, float(exit_price),
                           act["detail"].get("hold_days", 0),
                           act["exit_type"], act["hit_rule"])
            watch_pool.add_from_exit(conn, o["code"], act["exit_type"], today, high, P)
            return ok({"exited": True, "hit_rule": act["hit_rule"]})
        if act["action"] == "REDUCE_HALF":
            repo.save_partial_exit(conn, order_id, today, float(exit_price),
                                   act["detail"].get("hold_days", 0), act["hit_rule"])
            return ok({"exited": False, "reduced": True, "hit_rule": act["hit_rule"]})
        return err(f"当前动作非离场/减半（{act['action']}），如确认人工离场请传 force=true")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 观察池
# ---------------------------------------------------------------------------
@router.get("/watch-pool")
def watch_list(status: str = "ACTIVE"):
    conn = _conn()
    try:
        out = []
        for it in repo.list_watch(conn, status):
            item = dict(it)
            try:
                item["reentry_trigger"] = json.loads(item["reentry_trigger"])
            except Exception:  # noqa: BLE001
                pass
            out.append(item)
        return ok(out)
    finally:
        conn.close()


@router.get("/violations")
def violations(limit: int = 100):
    conn = _conn()
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM violation_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]
        return ok(rows)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 月度统计（简版 T11：分类型胜率/盈亏/样本门禁）
# ---------------------------------------------------------------------------
@router.get("/stats/monthly")
def stats_monthly(month: Optional[str] = None):
    conn = _conn()
    try:
        if not month:
            month = datetime.today().strftime("%Y-%m")
        rows = conn.execute(
            "SELECT e.trade_type AS t, x.pnl_pct AS pnl, x.is_planned, "
            "x.exit_type FROM exit_record x JOIN entry_order e "
            "ON x.entry_order_id=e.id WHERE x.exit_date LIKE ?",
            (f"{month}%",)).fetchall()
        by_type = {}
        for r in rows:
            d = by_type.setdefault(r["t"], {"trades": 0, "wins": 0, "pnl_sum": 0.0})
            d["trades"] += 1
            if r["pnl"] is not None:
                d["pnl_sum"] += r["pnl"]
                if r["pnl"] > 0:
                    d["wins"] += 1
        for t, d in by_type.items():
            d["win_rate"] = round(d["wins"] / d["trades"], 4) if d["trades"] else None
            d["avg_pnl"] = round(d["pnl_sum"] / d["trades"], 4) if d["trades"] else None
        total = sum(d["trades"] for d in by_type.values())
        planned = sum(1 for r in rows if r["is_planned"])
        return ok({
            "month": month,
            "by_type": by_type,
            "total_exits": total,
            "par": round(planned / total, 4) if total else None,  # 计划执行率
            "sample_gate": {"current": total, "required": 20,
                            "unlocked": total >= 20},
        })
    finally:
        conn.close()
