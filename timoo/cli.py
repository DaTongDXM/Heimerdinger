"""CLI 入口（阶段①~④）。

用法：
    python -m timoo.cli init                    # 初始化数据库
    python -m timoo.cli universe                # 构建并落盘 universe
    python -m timoo.cli fetch  [--limit N]      # 增量/全量更新日线
    python -m timoo.cli scan   [--limit N]      # 全流程：位置→信号→类型→候选
    python -m timoo.cli selftest                # 规则自检（SPEC §11）
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from .config import DEFAULT as P
from .pipeline import (cache, cleaner, entry_order, exit_engine, matcher,
                       position, signal, universe, watch_pool)
from .storage import db, repo

ROOT = Path(__file__).resolve().parents[1]


def _conn():
    conn = db.connect()
    db.init_db(conn)
    return conn


def cmd_init(args):
    conn = _conn()
    v = db.record_param_version(conn, P, note="初始参数")
    print(f"[init] db={db.get_db_path()} param_version={v}")
    conn.close()


def cmd_universe(args):
    conn = _conn()
    spot = universe.fetch_spot()
    uni = universe.build_universe(spot)
    lens = cache.kline_lengths(conn)
    if lens:
        uni = universe.mark_new_stocks(uni, lens, int(P["NEW_STOCK_MIN_DAYS"]))
    today = datetime.today().strftime("%Y-%m-%d")
    rows = [(today, r["code"], r["name"], int(r["in_universe"]), r["exclude_reason"])
            for _, r in uni.iterrows()]
    conn.executemany(
        "INSERT OR REPLACE INTO universe_snapshot(date,code,name,in_universe,exclude_reason) "
        "VALUES (?,?,?,?,?)", rows)
    conn.commit()
    kept = int(uni["in_universe"].sum())
    print(f"[universe] 全量 {len(uni)} 只，保留 {kept} 只，剔除 {len(uni)-kept} 只")
    conn.close()


def cmd_fetch(args):
    conn = _conn()
    rows = conn.execute(
        "SELECT code FROM universe_snapshot WHERE date=(SELECT MAX(date) FROM universe_snapshot) "
        "AND in_universe=1 ORDER BY code").fetchall()
    codes = [r["code"] for r in rows]
    if not codes:
        print("[fetch] universe 为空，请先运行 `python -m timoo.cli universe`")
        return
    if args.limit:
        codes = codes[: args.limit]

    def prog(i, total, status):
        print(f"  fetch {i}/{total} last={status}", flush=True)

    stats = cache.fetch_all(conn, codes, P, force_full=args.full, progress=prog)
    print(f"[fetch] full={stats['full']} incremental={stats['incremental']} "
          f"failed={stats['failed']} rows={stats['rows']}")
    if stats["failed_codes"]:
        out = ROOT / "data" / "failed" / f"{datetime.today():%Y-%m-%d}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(stats["failed_codes"], ensure_ascii=False, indent=2),
                       encoding="utf-8")
        print(f"[fetch] 失败清单 -> {out}")
    conn.close()


def _write_candidates(scan_date: str, pv: str, counts: dict, total: int,
                      candidates: list, suffix: str = "") -> Path:
    out_dir = ROOT / "data" / "candidates"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{scan_date}{suffix}.json"
    out.write_text(json.dumps({
        "scan_date": scan_date, "param_version": pv,
        "counts": counts, "total": total, "candidates": candidates,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def run_pipeline(conn, items, today: str, params):
    """核心流水线 ②→④：位置分类（硬过滤）→ 信号筛选 → 类型匹配。

    items: [(code, name), ...]；日线直接从库里读，不做网络请求。
    """
    pv = db.record_param_version(conn, params)
    counts: dict = {}
    candidates: list = []
    for i, (code, name) in enumerate(items, 1):
        kline = cleaner.clean(cache.load_kline(conn, code, limit=int(params["HISTORY_DAYS"])))
        if len(kline) < int(params["NEW_STOCK_MIN_DAYS"]):
            counts["insufficient"] = counts.get("insufficient", 0) + 1
            continue
        pr = position.classify(kline, params)
        p = pr["position"]
        counts[p] = counts.get(p, 0) + 1

        sr = {"level": "NONE", "valid": False, "detail": {}}
        m = {"trade_type": None, "reason": "位置过滤", "halved": False, "add_plan": None}
        if p in position.CANDIDATE_OK:
            plat = None
            if pr.get("platform_length"):
                n = len(kline)
                plat = {"start": max(0, n - pr["platform_length"]), "end": n - 1}
            sr = signal.evaluate(kline, params, platform=plat)
            m = matcher.match(pr, sr, params)

        is_cand = 1 if m.get("trade_type") else 0
        conn.execute(
            "INSERT OR REPLACE INTO scan_result(scan_date,code,name,position,position_detail,"
            "signal,signal_detail,trade_type,halved,is_candidate,ref_platform_top,"
            "ref_platform_bottom,ref_ma20,ref_prev_close,param_version) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (today, code, name, p, json.dumps(pr.get("detail"), ensure_ascii=False),
             sr.get("level"), json.dumps(sr.get("detail"), ensure_ascii=False),
             m.get("trade_type"), 1 if m.get("halved") else 0, is_cand,
             pr.get("platform_top"), pr.get("platform_bottom"),
             pr.get("ma20"), pr.get("prev_close"), pv))
        if is_cand:
            candidates.append({
                "code": code, "name": name, "type": m["trade_type"],
                "position": p, "halved": m.get("halved", False),
                "signal": sr.get("level"), "signal_detail": sr.get("detail"),
                "ref_platform_top": pr.get("platform_top"),
                "ref_platform_bottom": pr.get("platform_bottom"),
                "ref_ma20": pr.get("ma20"), "ref_prev_close": pr.get("prev_close"),
                "add_plan": m.get("add_plan"),
            })
        if i % 200 == 0:
            conn.commit()
            print(f"  scan {i}/{len(items)} 候选 {len(candidates)}", flush=True)
    conn.commit()
    return pv, counts, candidates


def cmd_scan(args):
    conn = _conn()
    rows = conn.execute(
        "SELECT code,name FROM universe_snapshot "
        "WHERE date=(SELECT MAX(date) FROM universe_snapshot) AND in_universe=1 "
        "ORDER BY code").fetchall()
    codes = [(r["code"], r["name"]) for r in rows]
    if not codes:
        print("[scan] universe 为空，请先运行 universe + fetch")
        return
    if args.limit:
        codes = codes[: args.limit]

    today = datetime.today().strftime("%Y-%m-%d")
    pv, counts, candidates = run_pipeline(conn, codes, today, P)
    out = _write_candidates(today, pv, counts, len(codes), candidates)
    print(f"[scan] 扫描 {len(codes)} 只 -> {counts}")
    print(f"[scan] 候选 {len(candidates)} 只 -> {out}")
    conn.close()


def cmd_simulate(args):
    """离线端到端：合成数据写入 DB 后跑完整 ①→④ 流水线（不需要网络）。"""
    import numpy as np
    import pandas as pd

    conn = _conn()
    today = datetime.today().strftime("%Y-%m-%d")
    rng = np.random.default_rng(20260918)
    n = 200
    shapes = ["bottom", "downtrend", "uptrend"]
    items = []

    for k in range(args.stocks):
        code = str(600000 + k)
        shape = shapes[k % 3]
        if shape == "bottom":
            base = [100 - 35 * i / 139 for i in range(140)] + [65.0] * 60
            vol = [5000.0] * 140 + [2000.0] * 30 + [800.0] + [2000.0] * 29
        elif shape == "downtrend":
            base = [100 - 0.3 * i for i in range(n)]
            vol = [3000.0] * n
        else:
            base = [50 + 0.2 * i for i in range(n)]
            vol = [3000.0] * n
        close = pd.Series(base, dtype=float) + rng.normal(0, 0.02, n)
        df = pd.DataFrame({
            "date": [f"2025-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(n)],
            "open": close, "high": close * 1.004, "low": close * 0.996,
            "close": close, "vol": pd.Series(vol, dtype=float),
        })
        cache.upsert_kline(conn, code, df)
        conn.execute(
            "INSERT OR REPLACE INTO universe_snapshot(date,code,name,in_universe,exclude_reason) "
            "VALUES (?,?,?,?,?)", (today, code, f"SIM-{shape}", 1, ""))
        items.append((code, f"SIM-{shape}"))
    conn.commit()

    pv, counts, candidates = run_pipeline(conn, items, today, P)
    out = _write_candidates(today, pv, counts, len(items), candidates, suffix="-sim")
    print(f"[simulate] 合成 {len(items)} 只 -> {counts}")
    print(f"[simulate] 候选 {len(candidates)} 只 -> {out}")
    conn.close()


def cmd_order(args):
    """阶段⑤：从扫描结果生成入场单并提交（8 项强制校验）。"""
    conn = _conn()
    try:
        order = entry_order.build_from_scan(
            conn, args.code, args.type, P,
            entry_price=args.entry_price,
            structure_position=args.position)
    except ValueError as e:
        print(f"[order] {e}")
        conn.close()
        return
    order["stop_loss_price"] = args.stop
    order["first_target_price"] = args.target
    if args.facts:
        order["observed_facts"] = args.facts
    ok, oid, errors = entry_order.submit(conn, order, P)
    if ok:
        print(f"[order] 已保存 #{oid} {order['code']} {order['name']} "
              f"类型{order['trade_type']} 止损{order['stop_loss_price']} "
              f"目标{order['first_target_price']} 时间止损{order['time_stop_days']}日")
    else:
        print("[order] 被拒绝：")
        for e in errors:
            print("   -", e)
    conn.close()


def cmd_monitor(args):
    """阶段⑥：按入场时锁定的规则判定出场，输出次日动作。"""
    conn = _conn()
    today = datetime.today().strftime("%Y-%m-%d")
    orders = repo.get_open_orders(conn)
    if not orders:
        print("[monitor] 无持仓")
        conn.close()
        return
    for o in orders:
        kline = cleaner.clean(cache.load_kline(conn, o["code"], limit=int(P["HISTORY_DAYS"])))
        act = exit_engine.evaluate(conn, o, kline, P)
        tag = {"HOLD": "持有", "EXIT": "离场", "REDUCE_HALF": "减半",
               "CONVERT_TO_B": "转B类管理"}.get(act["action"], act["action"])
        print(f"  #{o['id']} {o['code']} {o['name']} 类型{o['trade_type']} -> "
              f"{tag} {act['hit_rule'] or ''} {act['detail']}")
        if not args.confirm:
            continue
        if act["action"] == "EXIT":
            exit_day_high = float(pd.to_numeric(kline["high"]).iloc[-1]) if len(kline) else None
            repo.save_exit(conn, o["id"], today,
                           float(pd.to_numeric(kline["close"]).iloc[-1]),
                           act["detail"].get("hold_days", 0),
                           act["exit_type"], act["hit_rule"])
            watch_pool.add_from_exit(conn, o["code"], act["exit_type"], today,
                                     exit_day_high, P)
            print(f"    -> 已离场并入观察池")
        elif act["action"] == "REDUCE_HALF":
            repo.save_partial_exit(conn, o["id"], today,
                                   float(pd.to_numeric(kline["close"]).iloc[-1]),
                                   act["detail"].get("hold_days", 0), act["hit_rule"])
            print("    -> 已减半，剩余仓位按保护线管理")
    conn.close()


def cmd_watch(args):
    """阶段⑥：观察池再入场触发检查。"""
    conn = _conn()
    today = datetime.today().strftime("%Y-%m-%d")
    if args.sweep:
        for note in watch_pool.sweep(conn, today, P):
            print("  [sweep]", note)
    items = repo.list_watch(conn, "ACTIVE")
    if not items:
        print("[watch] 观察池为空")
        conn.close()
        return
    for it in items:
        kline = cleaner.clean(cache.load_kline(conn, it["code"], limit=int(P["HISTORY_DAYS"])))
        r = watch_pool.check_reentry(conn, it, kline, P)
        mark = "★触发" if r["triggered"] else "休眠"
        print(f"  {it['code']} 入池{it['entered_date']} 剩余{it['days_remaining']}日 "
              f"{mark} 位置={r.get('position')} 原因={r['reason']}")
        if r["triggered"]:
            repo.trigger_watch(conn, it["id"])
    conn.close()


def cmd_selftest(args):
    """SPEC §11 规则自检（不依赖网络）。"""
    from . import guard
    import numpy as np
    import pandas as pd

    ok = fail = 0

    def check(name, cond, extra=""):
        nonlocal ok, fail
        if cond:
            ok += 1
            print(f"  PASS  {name}")
        else:
            fail += 1
            print(f"  FAIL  {name} {extra}")

    print("[selftest] N1-N8 禁止事项")
    check("N2 无资金流触发路径", guard.has_moneyflow_path() is False)
    passed, hits = guard.check_predictive_text("MACD绿柱缩短，即将金叉")
    check("N3 拦截'即将金叉'", not passed and bool(hits))
    passed, _ = guard.check_predictive_text("MACD绿柱连续2日缩短，KDJ已金叉")
    check("N3 放行纯观察表述", passed)
    from datetime import timedelta
    now = datetime.now()
    allowed, remain = guard.check_cooldown(now - timedelta(minutes=12), now, 30)
    check("N6 盈利后12分钟禁止开仓", not allowed and remain is not None)
    allowed, _ = guard.check_cooldown(now - timedelta(minutes=45), now, 30)
    check("N6 超过30分钟放行", allowed)
    check("N7 C类禁用KDJ触发", guard.check_c_exit_trigger("kdj") is False)
    check("N7 C类允许失效价触发", guard.check_c_exit_trigger("invalidate_price") is True)
    check("N5 类型锁定", guard.check_type_lock("A", "B") is False)

    print("[selftest] 入场单8项校验")
    bad = {"trade_type": "A", "structure_position": "底部反转",
           "observed_facts": "MACD绿柱缩短，即将转正",
           "stop_loss_price": 10.0, "first_target_price": 11.0,
           "remainder_protection": "跌破当日开盘价", "time_stop_days": 3,
           "self_check_pass": True}
    okflag, errs = guard.validate_entry_order(bad, P)
    check("含预测性表述被拒", not okflag and any("N3" in e for e in errs), errs)
    good = dict(bad, observed_facts="MACD绿柱连续2日缩短，KDJ低位金叉")
    okflag, errs = guard.validate_entry_order(good, P)
    check("完整8项通过", okflag, errs)
    okflag, errs = guard.validate_entry_order({**good, "first_target_price": None}, P)
    check("缺项被拒", not okflag and any("缺字段" in e for e in errs))

    print("[selftest] 指标与位置（确定性合成数据）")
    n = 200

    def _mk(c, v, base_vol=2000.0):
        c = pd.Series(c, dtype=float)
        return pd.DataFrame({
            "date": [f"D{i:04d}" for i in range(len(c))],
            "open": c, "high": c * 1.004, "low": c * 0.996,
            "close": c, "vol": pd.Series(v, dtype=float),
        })

    # TC-A 底部反转：前 140 日 100→65 深跌，后 60 日严格横盘 65，平台内含底量日
    c_a = [100 - 35 * i / 139 for i in range(140)] + [65.0] * 60
    v_a = [5000.0] * 140 + [2000.0] * 30 + [800.0] + [2000.0] * 29
    k_a = _mk(c_a, v_a)
    pr_a = position.classify(k_a, P)
    check("TC-A 深跌+横盘+底量 → 底部反转",
          pr_a["position"] == position.BOTTOM, pr_a["detail"])
    m_a = matcher.match(pr_a, signal.evaluate(
        k_a, P, platform={"start": len(c_a) - 40, "end": len(c_a) - 1}), P)
    check("TC-A 底部反转产生候选(A或C)", m_a.get("trade_type") in ("A", "C"), m_a)

    # TC-B 下跌中继：持续下跌无平台，close 远低于 MA60
    c_b = [100 - 0.3 * i for i in range(n)]
    k_b = _mk(c_b, [3000.0] * n)
    pr_b = position.classify(k_b, P)
    check("TC-B 持续下跌无平台 → 下跌中继",
          pr_b["position"] == position.DOWNTREND, pr_b["detail"])
    m_b = matcher.match(pr_b, signal.evaluate(k_b, P), P)
    check("TC-B 下跌中继不产生候选(N4)", m_b.get("trade_type") is None, m_b)

    # TC-C 平台振幅/趋势超限时不识别为平台
    c_c = [70 + 0.9 * i for i in range(60)]  # 单边上涨约 1.29%/日
    plat_c = position.detect_platform(pd.Series(c_c), 0.08, 10, 40, 0.04)
    check("TC-C 单边上涨不识别为平台(D8)", plat_c is None, plat_c)
    c_c2 = [65.0] * 60  # 严格横盘
    plat_c2 = position.detect_platform(pd.Series(c_c2), 0.08, 10, 40, 0.04)
    check("TC-C2 严格横盘识别为平台", plat_c2 is not None and plat_c2["length"] == 40, plat_c2)

    # TC-D C 类加仓计划（Q4：按失效价空间等分）
    plan = matcher._c_add_steps(50.0, 48.50, P)
    check("TC-D 失效价 = 平台下沿×0.98", abs(plan["invalidate_price"] - 47.53) < 0.01, plan)
    check("TC-D 加仓档位落在建仓价与失效价之间",
          all(47.53 < p < 50.0 for p in plan["add_prices"]), plan["add_prices"])
    check("TC-D 层数封顶 D7", plan["max_layers"] == int(P["D7"]))

    # TC-E 随机序列：位置必须是合法枚举，且下跌中继绝不产生候选
    rng = np.random.default_rng(7)
    trend = np.concatenate([np.linspace(100, 60, 140), np.linspace(60, 61, 60)])
    close = pd.Series(trend + rng.normal(0, 0.15, n))
    k_e = pd.DataFrame({"date": [f"E{i:04d}" for i in range(n)],
                        "open": close, "high": close + 0.4, "low": close - 0.4,
                        "close": close, "vol": pd.Series(rng.integers(1000, 5000, n).astype(float))})
    pr_e = position.classify(k_e, P)
    check("TC-E 位置为合法枚举",
          pr_e["position"] in (position.BOTTOM, position.PULLBACK,
                               position.DOWNTREND, position.V_SHAPE, position.OTHER),
          pr_e["position"])
    sr_e = signal.evaluate(k_e, P, platform=None)
    check("TC-E 信号评估可运行", isinstance(sr_e.get("level"), str))
    m_e = matcher.match(pr_e, sr_e, P)
    check("TC-E 下跌中继不产生候选",
          pr_e["position"] != position.DOWNTREND or m_e.get("trade_type") is None)

    # --- T07/T08：入场单落库、出场引擎、观察池 ---
    import sqlite3

    from .storage import db as _db
    from .storage import repo as _repo

    mc = sqlite3.connect(":memory:")
    mc.row_factory = sqlite3.Row
    _db.init_db(mc)

    def _kline(closes, start_date="X0000"):
        s = pd.Series(closes, dtype=float)
        return pd.DataFrame({
            "date": [f"X{i:04d}" for i in range(len(s))],
            "open": s * 0.999, "high": s * 1.004, "low": s * 0.996,
            "close": s, "vol": pd.Series([3000.0] * len(s)),
        })

    print("[selftest] 入场单落库（T07）")
    full = {"code": "600000", "name": "T", "trade_type": "A",
            "structure_position": "底部反转",
            "observed_facts": "MACD绿柱连续2日缩短，KDJ低位金叉",
            "stop_loss_price": 65.0, "first_target_price": 75.0,
            "remainder_protection": "跌破当日开盘价", "time_stop_days": 3,
            "self_check_pass": True, "entry_price": 70.0}
    okf, oid, errs = _repo.save_entry_order(mc, {**full, "first_target_price": None}, P)
    check("落库：缺项被拒", not okf and any("缺字段" in e for e in errs), errs)
    okf, oid, errs = _repo.save_entry_order(mc, full, P)
    check("落库：完整8项通过", okf and oid is not None, errs)
    _repo.save_exit(mc, oid, datetime.now().isoformat(timespec="seconds"), 80.0,
                    1, "TAKE_PROFIT", "E-A-2")
    okf2, _, errs2 = _repo.save_entry_order(mc, {**full, "code": "600001"}, P,
                                            datetime.now())
    check("落库：盈利平仓后立即开仓被拒(N6)",
          not okf2 and any("N6" in e for e in errs2), errs2)

    print("[selftest] 出场引擎（T08）")
    k_drop = _kline([70.0] * 199 + [60.0])
    oa = {"id": 1, "trade_type": "A", "stop_loss_price": 65.0,
          "first_target_price": 75.0, "created_at": "X0190 10:00:00",
          "entry_price": 70.0}
    r = exit_engine.evaluate(mc, oa, k_drop, P)
    check("A类跌破锁定止损 → E-A-1",
          r["action"] == "EXIT" and r["hit_rule"] == "E-A-1", r)

    k_flat = _kline([50.0] * 200)
    oc = {"id": 2, "trade_type": "C", "stop_loss_price": 47.53,
          "first_target_price": 60.0, "created_at": "X0190 10:00:00",
          "entry_price": 50.0}
    r = exit_engine.evaluate(mc, oc, k_flat, P)
    check("C类未破失效价 → 持有（N7：不因KDJ/5日线触发）",
          r["action"] == "HOLD", r)
    r = exit_engine.evaluate(mc, oc, _kline([50.0] * 199 + [47.0]), P)
    check("C类跌破失效价 → E-C-1",
          r["action"] == "EXIT" and r["hit_rule"] == "E-C-1", r)

    b_tail = [70.0] * 190 + [68, 66, 64, 62, 60, 58, 57, 56, 55, 54]
    ob = {"id": 3, "trade_type": "B", "stop_loss_price": 60.0,
          "first_target_price": 90.0, "created_at": "X0190 10:00:00",
          "entry_price": 70.0}
    r = exit_engine.evaluate(mc, ob, _kline(b_tail), P)
    check("B类连续2日收盘破MA5 → E-B-1",
          r["action"] == "EXIT" and r["hit_rule"] == "E-B-1", r)

    print("[selftest] 观察池（W-*）")
    t1 = watch_pool.build_trigger("STOP_LOSS", 37.1)
    check("止损型预写收复价", t1["branch"] == "WRONG_KILL" and t1["recover_price"] == 37.1, t1)
    t2 = watch_pool.build_trigger("TREND_EXIT")
    check("趋势型休眠至位置复现", t2["branch"] == "TREND_EXIT", t2)

    print(f"\n[selftest] PASS={ok} FAIL={fail}")
    sys.exit(0 if fail == 0 else 1)


def main(argv=None):
    import os

    from .pipeline import data_source

    # 默认直连行情接口，避免被环境代理拦截（TIMOO_USE_PROXY=1 可恢复走代理）
    data_source.configure_network(os.environ.get("TIMOO_USE_PROXY", "") != "1")

    ap = argparse.ArgumentParser(prog="timoo", description="个人短线交易纪律执行系统")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="初始化数据库与参数版本").set_defaults(func=cmd_init)
    sub.add_parser("universe", help="构建 universe").set_defaults(func=cmd_universe)

    f = sub.add_parser("fetch", help="更新日线")
    f.add_argument("--limit", type=int, default=0)
    f.add_argument("--full", action="store_true", help="强制全量重拉")
    f.set_defaults(func=cmd_fetch)

    s = sub.add_parser("scan", help="全流程扫描")
    s.add_argument("--limit", type=int, default=0)
    s.set_defaults(func=cmd_scan)

    sub.add_parser("selftest", help="规则自检").set_defaults(func=cmd_selftest)

    sim = sub.add_parser("simulate", help="离线端到端（合成数据，无需网络）")
    sim.add_argument("--stocks", type=int, default=30)
    sim.set_defaults(func=cmd_simulate)

    o = sub.add_parser("order", help="创建入场单（8 项强制校验）")
    o.add_argument("--code", required=True)
    o.add_argument("--type", required=True, choices=["A", "B", "C"])
    o.add_argument("--stop", type=float, required=True, help="固定止损价（写死的数字）")
    o.add_argument("--target", type=float, required=True, help="第一目标价")
    o.add_argument("--facts", default="", help="观察到的事实（禁写预测）")
    o.add_argument("--entry-price", type=float, default=None)
    o.add_argument("--position", default=None, help="结构位置（默认取扫描结果）")
    o.set_defaults(func=cmd_order)

    m = sub.add_parser("monitor", help="持仓出场判定")
    m.add_argument("--confirm", action="store_true", help="执行出场并写入观察池")
    m.set_defaults(func=cmd_monitor)

    w = sub.add_parser("watch", help="观察池检查")
    w.add_argument("--sweep", action="store_true", help="执行到期清理")
    w.set_defaults(func=cmd_watch)

    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
