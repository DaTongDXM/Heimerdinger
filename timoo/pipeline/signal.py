"""阶段③ S-4：信号族判定与有效组合校验。

硬性约束：
- N1：仅 KDJ 金叉 = 无效，禁止单独触发买入
- N2：资金流相关逻辑在本模块不存在任何代码路径
- N3：不存在"即将金叉/即将转正"分支，只认当日已发生
"""

from __future__ import annotations

from typing import Dict, Optional

import pandas as pd

from . import indicators as ind

NONE = "NONE"
STANDARD = "STANDARD"
STRONG = "STRONG"


def evaluate(kline: pd.DataFrame, params,
             platform: Optional[Dict] = None) -> Dict:
    """计算信号族并给出信号等级。"""
    out = {"level": NONE, "detail": {}, "valid": False,
           "kdj_golden": False, "kdj_low_zone": False,
           "macd_shrinking": False, "macd_golden": False,
           "volume": None, "overbought": False}
    if kline is None or len(kline) < 60:
        out["detail"]["reason"] = "数据不足"
        return out

    df = kline.reset_index(drop=True)
    close = pd.to_numeric(df["close"], errors="coerce")
    high = pd.to_numeric(df["high"], errors="coerce")
    low = pd.to_numeric(df["low"], errors="coerce")
    vol = pd.to_numeric(df["vol"], errors="coerce")

    kd = ind.kdj(high, low, close, int(params["KDJ_N"]))
    mc = ind.macd(close, int(params["MACD_FAST"]), int(params["MACD_SLOW"]), int(params["MACD_SIGNAL"]))
    vma5 = ind.vol_ma(vol, 5)

    golden = ind.kdj_golden_cross(kd, float(params["KDJ_LOW_ZONE"]))
    shrinking = ind.macd_bar_shrinking(mc["hist"], int(params["MACD_SHRINK_DAYS"]))
    mgolden = ind.macd_golden_cross(mc["hist"])

    g = bool(golden.iloc[-1])
    s = bool(shrinking.iloc[-1])
    mg = bool(mgolden.iloc[-1])
    d_last = float(kd["D"].iloc[-1])

    vol_pat = _volume_pattern(vol, vma5, params, platform)

    out.update({
        "kdj_golden": g, "kdj_low_zone": bool(d_last < float(params["KDJ_LOW_ZONE"])),
        "macd_shrinking": s, "macd_golden": mg,
        "volume": vol_pat, "overbought": bool(ind.overbought(
            kd, float(params["J_OVERBOUGHT"]), float(params["K_OVERBOUGHT"])).iloc[-1]),
        "detail": {
            "K": round(float(kd["K"].iloc[-1]), 3),
            "D": round(d_last, 3),
            "J": round(float(kd["J"].iloc[-1]), 3),
            "hist": round(float(mc["hist"].iloc[-1]), 5),
            "vol_ma5": round(float(vma5.iloc[-1]), 3) if pd.notna(vma5.iloc[-1]) else None,
        },
    })

    # --- S-4 有效组合 ---
    if mg and g and vol_pat:
        out["level"] = STRONG
        out["valid"] = True
        out["detail"]["combo"] = "MACD金叉+KDJ金叉+放量"
    elif g and s and vol_pat:
        out["level"] = STANDARD
        out["valid"] = True
        out["detail"]["combo"] = "KDJ低位金叉+MACD绿柱缩短+量能"
    else:
        # N1：仅 KDJ 金叉无效
        if g:
            out["detail"]["reject"] = "N1:仅KDJ金叉无效"
        else:
            out["detail"]["reject"] = "无有效组合"
    return out


def _volume_pattern(vol: pd.Series, vma5: pd.Series, params,
                    platform: Optional[Dict]) -> Optional[str]:
    """量能三选一：V1 底量后放量 / V2 温和放量 / V3 缩量转放量。"""
    if platform:
        seg = vol.iloc[platform["start"]:platform["end"] + 1]
        if len(seg):
            base = float(seg.min())
            if base > 0 and float(vol.iloc[-1]) >= base * float(params["V1"]):
                return "V1"
    cur = float(vol.iloc[-1])
    prev = float(vol.iloc[-2]) if len(vol) > 1 else 0.0
    m5 = float(vma5.iloc[-1]) if pd.notna(vma5.iloc[-1]) else None
    if m5:
        # V2 连续 3 日落在区间内
        n = int(params["V2_DAYS"])
        if len(vol) >= n:
            seg = vol.iloc[-n:]
            ma_seg = vma5.iloc[-n:]
            if bool(((seg >= ma_seg * float(params["V2_LO"])) &
                     (seg <= ma_seg * float(params["V2_HI"]))).all()):
                return "V2"
        # V3 缩量转放量
        if prev < m5 * float(params["V3_PREV"]) and cur > m5 * float(params["V3_CUR"]):
            return "V3"
    return None
