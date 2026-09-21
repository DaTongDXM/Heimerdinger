"""阶段② 位置三分类（硬过滤）。

判定顺序（不可颠倒）：
    V 型例外 → 下跌中继(X1/X2) → 底部反转(P1-P4) → 多头回踩(M1-M2) → OTHER

所有判定基于 T-1 及以前的收盘数据（D-4）。
"""

from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd

from . import indicators as ind

BOTTOM = "BOTTOM_REVERSAL"
PULLBACK = "PULLBACK_UPTREND"
DOWNTREND = "DOWNTREND_CONTINUATION"
V_SHAPE = "V_SHAPE"
OTHER = "OTHER"

CANDIDATE_OK = (BOTTOM, PULLBACK, V_SHAPE)


def detect_platform(closes: pd.Series, d2: float = 0.08,
                    min_len: int = 10, max_len: int = 40,
                    d8: Optional[float] = None) -> Optional[Dict]:
    """Q1 已确认：以 T-1 为终点向前自适应扩展，振幅 ≤ d2 则继续延伸，取最长平台。

    D8 趋势约束（Q9）：平台的语义是"横盘"，仅凭振幅 ≤D2 会把单边上涨中的任意一段
    （例如日涨 1.29%、11 日累计 7.9%）误判为平台。故增加线性趋势约束：
        |slope| × length / mean_close ≤ D8
    超过则跳过该窗口（不 break，因为更长窗口的趋势可能更小）。

    返回 dict(start, end, length, amplitude, top, bottom, trend_rel)；无满足的平台返回 None。
    """
    arr = pd.to_numeric(closes, errors="coerce").dropna()
    if len(arr) < min_len:
        return None
    end = len(arr) - 1
    best = None
    for n in range(min_len, max_len + 1):
        start = end - n + 1
        if start < 0:
            break
        seg = arr.iloc[start:end + 1]
        lo, hi = float(seg.min()), float(seg.max())
        if lo <= 0:
            break
        amp = (hi - lo) / lo
        if amp > d2:
            break
        trend_rel = 0.0
        if d8 is not None:
            y = seg.to_numpy(dtype=float)
            slope = float(np.polyfit(np.arange(n), y, 1)[0])
            trend_rel = abs(slope) * n / float(seg.mean())
            if trend_rel > d8:
                continue
        best = {"start": start, "end": end, "length": n,
                "amplitude": amp, "top": hi, "bottom": lo,
                "trend_rel": trend_rel}
    return best


def _p4_ma60_slowing(ma60: pd.Series, days: int = 5) -> bool:
    """P4：|MA60(t)-MA60(t-1)| 连续 days 日递减。"""
    d = ma60.diff().abs().dropna()
    if len(d) < days + 1:
        return False
    tail = d.iloc[-(days + 1):].to_numpy()
    return bool(np.all(np.diff(tail) < -1e-12))


def classify(kline: pd.DataFrame, params) -> Dict:
    """输入日线（升序，最后一根为 T-1），输出位置判定结果。"""
    res = {
        "position": OTHER, "detail": {}, "halved": False,
        "platform_top": None, "platform_bottom": None,
        "ma20": None, "ma60": None, "prev_close": None,
        "amplitude": None, "platform_length": None,
    }
    if kline is None or len(kline) < int(params["NEW_STOCK_MIN_DAYS"]):
        res["detail"]["reason"] = "数据不足"
        return res

    df = kline.reset_index(drop=True)
    close = pd.to_numeric(df["close"], errors="coerce")
    high = pd.to_numeric(df["high"], errors="coerce")
    low = pd.to_numeric(df["low"], errors="coerce")
    vol = pd.to_numeric(df["vol"], errors="coerce")

    ma20 = ind.ma(close, 20)
    ma60 = ind.ma(close, 60)
    c_last = float(close.iloc[-1])
    ma20_last = float(ma20.iloc[-1]) if pd.notna(ma20.iloc[-1]) else None
    ma60_last = float(ma60.iloc[-1]) if pd.notna(ma60.iloc[-1]) else None

    res.update({"ma20": ma20_last, "ma60": ma60_last, "prev_close": c_last})

    # --- 平台（P2 基础）---
    plat = detect_platform(close, float(params["D2"]),
                           int(params["D3"]), int(params["PLATFORM_MAX_LEN"]),
                           float(params["D8"]))
    has_platform = plat is not None
    if has_platform:
        res.update({"platform_top": plat["top"], "platform_bottom": plat["bottom"],
                    "platform_length": plat["length"], "amplitude": plat["amplitude"]})

    # --- V 型例外（优先判定）---
    v_days = int(params["V_SHAPE_DAYS"])
    if ma60_last and c_last < ma60_last and len(close) > v_days:
        base = float(close.iloc[-(v_days + 1)])
        gain = (c_last - base) / base if base > 0 else 0.0
        vma5 = ind.vol_ma(vol, 5).iloc[-1]
        vol_ok = bool(pd.notna(vma5) and float(vol.iloc[-1]) >= float(vma5) * float(params["V4"]))
        if gain >= float(params["V_SHAPE_GAIN"]) and vol_ok:
            res["position"] = V_SHAPE
            res["halved"] = True  # 仓位强制减半
            res["detail"] = {"gain_5d": round(gain, 4), "vol_ratio": round(
                float(vol.iloc[-1]) / float(vma5), 3) if vma5 else None}
            return res

    # --- X1 / X2 下跌中继 ---
    x1_gap = None
    if ma60_last and c_last < ma60_last:
        x1_gap = (ma60_last - c_last) / ma60_last
        if x1_gap >= float(params["X1"]) and not has_platform:
            res["position"] = DOWNTREND
            res["detail"] = {"rule": "X1", "gap_to_ma60": round(x1_gap, 4)}
            return res
    if not has_platform and len(close) >= int(params["D3"]):
        # 有区间但不满足振幅约束 → 视为无有效平台
        pass
    if x1_gap is not None and x1_gap >= float(params["X1"]) and has_platform:
        res["position"] = DOWNTREND
        res["detail"] = {"rule": "X1", "gap_to_ma60": round(x1_gap, 4)}
        return res
    if plat is not None and plat["length"] < int(params["D3"]):
        res["position"] = DOWNTREND
        res["detail"] = {"rule": "X2", "platform_length": plat["length"]}
        return res

    # --- P1-P4 底部反转 ---
    if has_platform and ma60_last:
        w120 = close.iloc[-120:] if len(close) >= 120 else close
        w60 = close.iloc[-60:] if len(close) >= 60 else close
        p1 = (float(w120.max()) - float(w60.max())) / float(w120.max())
        seg = close.iloc[plat["start"]:plat["end"] + 1]
        vseg = vol.iloc[plat["start"]:plat["end"] + 1]
        vmean = float(vseg.mean()) if len(vseg) else 0.0
        p3 = bool(vmean > 0 and float(vseg.min()) <= vmean * float(params["D4"]))
        p4 = _p4_ma60_slowing(ma60, int(params["D5"]))
        ok = {
            "P1": bool(p1 >= float(params["D1"])),
            "P2": True,
            "P3": p3,
            "P4": p4,
        }
        res["detail"] = {"P1_drop": round(p1, 4), **ok,
                         "platform_length": plat["length"],
                         "amplitude": round(plat["amplitude"], 4)}
        if all(ok.values()):
            res["position"] = BOTTOM
            return res

    # --- M1 / M2 多头回踩 ---
    if ma20_last and ma60_last and len(ma20) > 6:
        m1 = bool(float(ma20.iloc[-1]) > float(ma20.iloc[-6])
                  and c_last > ma20_last > ma60_last)
        recent = df.iloc[-3:]
        m_low = pd.to_numeric(recent["low"], errors="coerce").to_numpy()
        m_close = pd.to_numeric(recent["close"], errors="coerce").to_numpy()
        ma20_tail = ma20.iloc[-3:].to_numpy()
        touched = bool(np.any((m_low >= ma20_tail * 0.98) & (m_low <= ma20_tail * 1.02)))
        all_above = bool(np.all(m_close > ma20_tail))
        m2 = touched and all_above
        res["detail"] = {"M1": m1, "M2": m2, "touched_ma20": touched, "close_above_ma20": all_above}
        if m1 and m2:
            res["position"] = PULLBACK
            return res

    res["detail"] = res.get("detail") or {"reason": "未匹配任何位置定义"}
    return res
