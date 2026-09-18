"""全流程编排（universe → fetch → scan），供 CLI 与 API 共用。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from ..config import Params
from ..storage import db
from . import cache, cleaner, matcher, position, signal, universe

ROOT = Path(__file__).resolve().parents[2]

ProgressFn = Callable[[str, int, int], None]
CandidateFn = Callable[[dict], None]


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


def run_pipeline(conn, items: List[Tuple[str, str]], today: str, params: Params,
                 progress: Optional[ProgressFn] = None,
                 on_candidate: Optional[CandidateFn] = None):
    """核心流水线 ②→④：位置分类（硬过滤）→ 信号筛选 → 类型匹配。

    items: [(code, name), ...]；日线直接从库里读，不做网络请求。
    on_candidate: 每发现一只候选立即回调（供 UI 实时上屏）。
    """
    pv = db.record_param_version(conn, params)
    # 同日重跑先清掉旧结果，避免残留过期行
    conn.execute("DELETE FROM scan_result WHERE scan_date=?", (today,))
    conn.commit()
    counts: dict = {}
    candidates: list = []
    total = len(items)
    for i, (code, name) in enumerate(items, 1):
        kline = cleaner.clean(cache.load_kline(conn, code, limit=int(params["HISTORY_DAYS"])))
        if len(kline) < int(params["NEW_STOCK_MIN_DAYS"]):
            counts["insufficient"] = counts.get("insufficient", 0) + 1
        else:
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
                cand = {
                    "code": code, "name": name, "type": m["trade_type"],
                    "position": p, "halved": m.get("halved", False),
                    "signal": sr.get("level"), "signal_detail": sr.get("detail"),
                    "ref_platform_top": pr.get("platform_top"),
                    "ref_platform_bottom": pr.get("platform_bottom"),
                    "ref_ma20": pr.get("ma20"), "ref_prev_close": pr.get("prev_close"),
                    "add_plan": m.get("add_plan"),
                }
                candidates.append(cand)
                if on_candidate:
                    try:
                        on_candidate(cand)
                    except Exception:  # noqa: BLE001 - 回调失败不影响扫描
                        pass
        if progress and (i % 20 == 0 or i == total):
            progress("扫描", i, total)
        if i % 20 == 0:
            conn.commit()
    conn.commit()
    return pv, counts, candidates


def run_full(params: Params, progress: Optional[ProgressFn] = None,
             skip_fetch: bool = False,
             on_candidate: Optional[CandidateFn] = None) -> Dict:
    """完整流程：universe 重判 → 日线增量更新 → 扫描 → 候选清单落盘。

    skip_fetch=True 时只重算扫描（用本地已有日线，无网络请求，秒级完成）。
    """
    conn = db.connect()
    db.init_db(conn)
    today = datetime.today().strftime("%Y-%m-%d")
    try:
        items: List[Tuple[str, str]] = []
        if skip_fetch:
            # 仅重算：完全离线，用本地最近一次 universe + 已有日线
            rows = conn.execute(
                "SELECT code,name FROM universe_snapshot "
                "WHERE date=(SELECT MAX(date) FROM universe_snapshot) AND in_universe=1 "
                "ORDER BY code").fetchall()
            items = [(r["code"], r["name"]) for r in rows]
            if not items:
                raise ValueError("本地无 universe 数据，请先运行一次完整扫描")
        else:
            # --- ① universe（每次运行重判，U-2）---
            if progress:
                progress("构建universe", 0, 0)
            spot = universe.fetch_spot()
            uni = universe.build_universe(spot)
            lens = cache.kline_lengths(conn)
            if lens:
                uni = universe.mark_new_stocks(uni, lens, int(params["NEW_STOCK_MIN_DAYS"]))
            snap = [(today, r["code"], r["name"], int(r["in_universe"]), r["exclude_reason"])
                    for _, r in uni.iterrows()]
            conn.executemany(
                "INSERT OR REPLACE INTO universe_snapshot(date,code,name,in_universe,exclude_reason) "
                "VALUES (?,?,?,?,?)", snap)
            conn.commit()
            kept = uni[uni["in_universe"] == 1]
            items = list(zip(kept["code"].tolist(), kept["name"].tolist()))

        # --- ② 日线增量 ---
        fetch_stats: Dict = {"skipped": True}
        if not skip_fetch:
            def _fp(i, total, status):
                if progress:
                    progress("更新日线", i, total)

            fetch_stats = cache.fetch_all(conn, [c for c, _ in items], params, progress=_fp)
            if fetch_stats.get("failed_codes"):
                out = ROOT / "data" / "failed" / f"{today}.json"
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(json.dumps(fetch_stats["failed_codes"],
                                          ensure_ascii=False, indent=2), encoding="utf-8")

        # --- ③④ 扫描 ---
        pv, counts, candidates = run_pipeline(conn, items, today, params,
                                              progress=progress,
                                              on_candidate=on_candidate)
        out = _write_candidates(today, pv, counts, len(items), candidates)
        return {
            "scan_date": today,
            "universe": len(items),
            "fetch": {k: v for k, v in fetch_stats.items() if k != "failed_codes"},
            "failed_count": len(fetch_stats.get("failed_codes", [])),
            "counts": counts,
            "candidates": len(candidates),
            "output": str(out),
        }
    finally:
        conn.close()
