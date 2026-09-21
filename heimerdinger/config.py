"""参数集中管理 + 参数版本化。

规范 v1.3 要求：任何参数修改必须有版本记录，保证历史扫描结果可复现。
样本 <20 笔时禁止调优（由 METRICS.md 的门禁约束，本模块只负责记录与校验）。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict

# ----------------------------------------------------------------------------
# 参数默认值（规范 v1.3 §7 + 本轮新增）
# ----------------------------------------------------------------------------
DEFAULT_PARAMS: Dict[str, Any] = {
    # --- 位置分类：底部反转 ---
    "D1": 0.15,            # 前期跌幅门槛 (max_close_120 - max_close_60)/max_close_120
    "D2": 0.08,            # 平台振幅上限
    "D3": 10,              # 平台最少交易日
    "D4": 0.60,            # 底量 / 平台期日均量 比
    "D5": 5,               # MA60 降速放缓窗口（一阶差分绝对值连续递减天数）
    "D8": 0.04,            # Q9：平台"横盘"趋势约束，|slope|×length/mean ≤ D8
    "PLATFORM_MAX_LEN": 40,  # Q1：平台自适应向前延伸上限
    # --- 位置分类：V 型 ---
    "V_SHAPE_GAIN": 0.12,  # V型：5 日内涨幅门槛
    "V_SHAPE_DAYS": 5,     # V型：涨幅统计窗口
    "V4": 1.80,            # V型放量阈值（规范未定义，建议值）
    # --- 位置分类：下跌中继 ---
    "X1": 0.10,            # 距 MA60 跌幅禁入线
    # --- 信号族 ---
    "KDJ_N": 9, "KDJ_M1": 3, "KDJ_M2": 3,
    "KDJ_LOW_ZONE": 50,    # 低位金叉：D < 50
    "MACD_FAST": 12, "MACD_SLOW": 26, "MACD_SIGNAL": 9,
    "MACD_SHRINK_DAYS": 2,  # 绿柱缩短最少连续天数
    "V1": 1.80,            # 底量后放量倍数
    "V2_LO": 1.20, "V2_HI": 2.50, "V2_DAYS": 3,   # 温和放量区间（相对 MA5(vol)）
    "V3_PREV": 0.80, "V3_CUR": 1.30,              # 缩量转放量
    "J_OVERBOUGHT": 100, "K_OVERBOUGHT": 85,      # 超买警告阈值（仅提示）
    # --- 交易类型 ---
    "B1": 0.08,            # B 类移动止盈回撤
    "D6_SEGMENTS": 3,      # Q4：C 类加仓，建仓价→失效价 空间等分段数
    "D7": 4,               # C 类总层数封顶
    "C_INVALIDATE_K": 0.98,  # C 类失效价 = 平台下沿 × 0.98
    # --- 数据层 ---
    "HISTORY_DAYS": 180,      # 拉取交易日深度（规范 130 为下限，留余量）
    "NEW_STOCK_MIN_DAYS": 130,  # 次新股剔除线
    "SLEEP_MIN": 0.30,        # 限速下限（秒）
    "SLEEP_MAX": 0.50,        # 限速上限（秒）
    "MAX_RETRY": 2,           # 主源重试次数（之后切备用源）
    "INCREMENTAL_DAYS": 5,    # 增量更新时向前回看的交易日数
    # --- 纪律 ---
    "COOLDOWN_MINUTES": 30,   # N6：盈利平仓后禁止开仓时长
    "WATCH_POOL_DAYS": 20,    # 观察池自动清除天数
    "TIME_STOP_A": 3, "TIME_STOP_B": 20, "TIME_STOP_C": 20,
}

# ----------------------------------------------------------------------------
# Universe 规则（规范 §1.0）
# ----------------------------------------------------------------------------
KEEP_PREFIXES = ("600", "601", "603", "605", "000", "001", "002", "003", "300", "301")
EXCLUDE_PREFIXES = ("688", "689", "43", "83", "87", "92", "8")  # 科创板/北交所
ST_KEYWORDS = ("ST", "*ST", "退")


class Params:
    """参数容器：单一来源，禁止散落硬编码。"""

    def __init__(self, overrides: Dict[str, Any] | None = None):
        unknown = set(overrides or {}) - set(DEFAULT_PARAMS)
        if unknown:
            raise KeyError(f"未知参数: {sorted(unknown)}")
        self._d = {**DEFAULT_PARAMS, **(overrides or {})}

    def __getitem__(self, key: str) -> Any:
        return self._d[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._d.get(key, default)

    def as_dict(self) -> Dict[str, Any]:
        return dict(self._d)

    @property
    def version(self) -> str:
        """参数版本指纹：内容相同 → 版本相同，用于结果可复现。"""
        blob = json.dumps(self._d, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return hashlib.sha1(blob).hexdigest()[:12]


DEFAULT = Params()
