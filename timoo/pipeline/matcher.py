"""阶段④ 类型匹配（A 短线动量 / B 波段跟随 / C 左侧分批建仓）。

匹配规则（规范 §4.1）：
    底部反转 + 信号        → A
    多头回踩 + 信号        → A/B（MACD 金叉 + 回踩确认 → B）
    底部反转 + 平台底量(无信号) → C
    V型 + 信号            → A（仓位减半）
    下跌中继              → 不进入本模块（阶段②已硬过滤）
"""

from __future__ import annotations

from typing import Dict, Optional

from . import position as posmod
from . import signal as sigmod

TYPE_A = "A"
TYPE_B = "B"
TYPE_C = "C"


def _c_add_steps(entry_price: float, platform_bottom: float, params) -> Dict:
    """Q4 已确认：按失效价空间等分。

    step = (建仓价 − 平台下沿×0.98) / 建仓价 ÷ D6_SEGMENTS
    """
    invalidate = platform_bottom * float(params["C_INVALIDATE_K"])
    space = (entry_price - invalidate) / entry_price
    seg = int(params["D6_SEGMENTS"])
    step = space / seg
    adds = [round(entry_price * (1 - step * (i + 1)), 4) for i in range(seg - 1)]
    return {
        "invalidate_price": round(invalidate, 4),
        "space_pct": round(space, 6),
        "step_pct": round(step, 6),
        "add_prices": adds,
        "max_layers": int(params["D7"]),
    }


def match(position_result: Dict, signal_result: Dict, params,
          entry_price: Optional[float] = None) -> Dict:
    """返回 {trade_type, halved, reason, add_plan}。无匹配时 trade_type=None。"""
    p = position_result.get("position")
    out = {"trade_type": None, "halved": bool(position_result.get("halved")),
           "reason": "", "add_plan": None}

    if p == posmod.DOWNTREND:
        # N4：理论上不会走到这里，防御性拦截
        out["reason"] = "N4:下跌中继禁止入池"
        return out

    lvl = signal_result.get("level")
    valid = bool(signal_result.get("valid"))

    if p == posmod.V_SHAPE:
        if valid:
            out.update({"trade_type": TYPE_A, "halved": True, "reason": "V型+信号，仓位减半"})
        else:
            out["reason"] = "V型但无有效信号"
        return out

    if p == posmod.BOTTOM:
        if valid:
            out.update({"trade_type": TYPE_A, "reason": "底部反转+有效信号"})
            return out
        # C 类：不等信号，平台 + 底量即分批
        if position_result.get("platform_bottom") is not None:
            price = entry_price if entry_price else position_result.get("prev_close")
            if price:
                out.update({
                    "trade_type": TYPE_C,
                    "reason": "底部平台+底量，左侧分批",
                    "add_plan": _c_add_steps(float(price),
                                             float(position_result["platform_bottom"]), params),
                })
                return out
        out["reason"] = "底部反转但无信号且无平台数据"
        return out

    if p == posmod.PULLBACK:
        if signal_result.get("macd_golden") and valid:
            out.update({"trade_type": TYPE_B, "reason": "多头回踩+MACD金叉"})
            return out
        if valid:
            out.update({"trade_type": TYPE_A, "reason": "多头回踩+有效信号"})
            return out
        out["reason"] = "多头回踩但无有效信号"
        return out

    out["reason"] = f"未知位置:{p}"
    return out
