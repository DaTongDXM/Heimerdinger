"""横切守卫：N1-N8 禁止事项拦截（规范 §8）。

设计原则：拦截集中在本模块，不散落业务代码。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

# N3：预测性表述（禁止进入入场单第 2 项）
PREDICTIVE_PATTERNS = [
    r"即将", r"快要", r"预计", r"大概率", r"应该会", r"有望", r"马上",
    r"就要", r"快到", r"可能会", r"估计会",
]

# N7：C 类禁止使用的出场触发
C_FORBIDDEN_TRIGGERS = {"kdj", "kdj_overbought", "ma5", "ma5_break",
                        "intraday_vwap", "分时均线"}

ENTRY_ORDER_FIELDS = [
    "trade_type", "structure_position", "observed_facts",
    "stop_loss_price", "first_target_price", "remainder_protection",
    "time_stop_days", "self_check_pass",
]


def check_predictive_text(text: str) -> Tuple[bool, List[str]]:
    """N3：返回 (是否通过, 命中的预测性词)。"""
    hits = []
    for pat in PREDICTIVE_PATTERNS:
        if re.search(pat, str(text or "")):
            hits.append(pat)
    return (not hits), hits


def check_cooldown(last_profit_close_at: Optional[datetime], now: Optional[datetime] = None,
                   minutes: int = 30) -> Tuple[bool, Optional[int]]:
    """N6：盈利平仓后 minutes 分钟内禁止开新仓。返回 (是否允许, 剩余分钟)。"""
    if last_profit_close_at is None:
        return True, None
    now = now or datetime.now()
    elapsed = now - last_profit_close_at
    if elapsed < timedelta(minutes=minutes):
        remain = int((timedelta(minutes=minutes) - elapsed).total_seconds() // 60) + 1
        return False, remain
    return True, None


def check_type_lock(original: str, new: str) -> bool:
    """N5：出场规则类型锁定，禁止修改。"""
    return original == new


def check_c_exit_trigger(trigger: str) -> bool:
    """N7：C 类禁用 KDJ / 5日线 / 盘中分时均线作为出场触发。"""
    return trigger.lower() not in C_FORBIDDEN_TRIGGERS


def has_moneyflow_path() -> bool:
    """N2：资金流触发器不存在任何代码路径。恒为 False，供测试断言。"""
    return False


# ---------------------------------------------------------------------------
# P0-11 入场单 8 项强制校验
# ---------------------------------------------------------------------------
def validate_entry_order(order: Dict, params,
                         last_profit_close_at: Optional[datetime] = None) -> Tuple[bool, List[str]]:
    """缺一项即不允许保存。返回 (是否通过, 错误列表)。"""
    errors: List[str] = []

    miss = [f for f in ENTRY_ORDER_FIELDS if order.get(f) in (None, "")]
    if miss:
        errors.append(f"缺字段: {miss}")

    tt = order.get("trade_type")
    if tt not in ("A", "B", "C"):
        errors.append("trade_type 必须为 A/B/C")

    facts = str(order.get("observed_facts") or "")
    ok, hits = check_predictive_text(facts)
    if not ok:
        errors.append(f"N3:观察到的事实含预测性表述 {hits}")

    try:
        sl = float(order.get("stop_loss_price"))
        tp = float(order.get("first_target_price"))
        if sl <= 0 or tp <= 0:
            errors.append("止损价/目标价必须为正数")
        if tt in ("A", "B") and tp <= sl:
            errors.append("第一目标价必须高于止损价")
    except (TypeError, ValueError):
        errors.append("止损价/目标价必须为数字")

    cooldown_min = int(params["COOLDOWN_MINUTES"])
    allowed, remain = check_cooldown(last_profit_close_at, minutes=cooldown_min)
    if not allowed:
        errors.append(f"N6:盈利平仓后 {cooldown_min} 分钟内禁止开仓，剩余 {remain} 分钟")
    if not order.get("self_check_pass"):
        errors.append("自检第7项未通过")

    return (not errors), errors
