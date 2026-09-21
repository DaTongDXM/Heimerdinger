"""阶段③ S-1~S-3：技术指标。全部向量化，只接受收盘日线序列。

口径强制（D-4）：本模块不接受盘中价参数，禁止用于盘中动态计算。
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def ma(series: pd.Series, n: int) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").rolling(n, min_periods=n).mean()


def ema(series: pd.Series, n: int) -> pd.Series:
    """A 股口径 EMA（递推式，等价 adjust=False）。"""
    return pd.to_numeric(series, errors="coerce").ewm(span=n, adjust=False).mean()


# ---------------------------------------------------------------------------
# S-1 KDJ(9,3,3)
# ---------------------------------------------------------------------------
def kdj(high: pd.Series, low: pd.Series, close: pd.Series,
        n: int = 9, m1: int = 3, m2: int = 3) -> pd.DataFrame:
    """RSV=(C-LLV(L,n))/(HHV(H,n)-LLV(L,n))*100; K=(m1-1)/m1*K_prev+1/m1*RSV;
    D=(m2-1)/m2*D_prev+1/m2*K; J=3K-2D。初值 K=D=50。"""
    h = pd.to_numeric(high, errors="coerce")
    l = pd.to_numeric(low, errors="coerce")
    c = pd.to_numeric(close, errors="coerce")
    llv = l.rolling(n, min_periods=n).min()
    hhv = h.rolling(n, min_periods=n).max()
    span = (hhv - llv)
    rsv = pd.Series(np.where(span == 0, 50.0, (c - llv) / span.replace(0, np.nan) * 100.0),
                    index=c.index)
    rsv = rsv.fillna(50.0)

    k_vals, d_vals = [], []
    k_prev = d_prev = 50.0
    for r in rsv.to_numpy():
        k_prev = (m1 - 1) / m1 * k_prev + (1 / m1) * r
        d_prev = (m2 - 1) / m2 * d_prev + (1 / m2) * k_prev
        k_vals.append(k_prev)
        d_vals.append(d_prev)
    k = pd.Series(k_vals, index=c.index)
    d = pd.Series(d_vals, index=c.index)
    return pd.DataFrame({"K": k, "D": d, "J": 3 * k - 2 * d})


def kdj_golden_cross(kdj_df: pd.DataFrame, low_zone: float = 50.0) -> pd.Series:
    """金叉：K(t-1)<=D(t-1) 且 K(t)>D(t)，且发生在 D<50 区域（低位金叉才有效）。

    只认"当日已发生"，不存在"即将金叉"分支（N3）。
    """
    k, d = kdj_df["K"], kdj_df["D"]
    prev_le = k.shift(1) <= d.shift(1)
    now_gt = k > d
    return (prev_le & now_gt & (d < low_zone)).fillna(False)


# ---------------------------------------------------------------------------
# S-2 MACD(12,26,9)
# ---------------------------------------------------------------------------
def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    c = pd.to_numeric(close, errors="coerce")
    dif = ema(c, fast) - ema(c, slow)
    dea = ema(dif, signal)
    return pd.DataFrame({"dif": dif, "dea": dea, "hist": dif - dea})


def macd_bar_shrinking(hist: pd.Series, days: int = 2) -> pd.Series:
    """绿柱缩短：hist(t)<0 且 |hist| 连续 >= days 日递减。

    days=2 表示：|hist(t)| < |hist(t-1)| 且 |hist(t-1)| < |hist(t-2)|，
    即至少 2 次递减（覆盖 3 根柱子）。
    """
    a = hist.abs()
    cur = hist < 0
    dec = pd.Series(True, index=hist.index)
    for lag in range(1, days + 1):
        dec &= (a < a.shift(lag))
    return (cur & dec).fillna(False)


def macd_golden_cross(hist: pd.Series) -> pd.Series:
    """金叉：hist 上穿 0。"""
    return ((hist.shift(1) <= 0) & (hist > 0)).fillna(False)


def macd_death_cross(hist: pd.Series) -> pd.Series:
    return ((hist.shift(1) >= 0) & (hist < 0)).fillna(False)


# ---------------------------------------------------------------------------
# 量能
# ---------------------------------------------------------------------------
def vol_ma(vol: pd.Series, n: int = 5) -> pd.Series:
    return ma(vol, n)


def overbought(kdj_df: pd.DataFrame, j_th: float = 100.0, k_th: float = 85.0) -> pd.Series:
    """超买警告：J>100 或 K>85。仅提示，不作出场触发器（N7）。"""
    return ((kdj_df["J"] > j_th) | (kdj_df["K"] > k_th)).fillna(False)
