"""阶段① D-2：数据清洗。

- 停牌日：按交易日历对齐，close 前向填充，vol 填 0（参与底量判定但不触发放量）
- close 为空的记录直接丢弃（无法前向填充的情形）
"""

from __future__ import annotations

from typing import Optional

import pandas as pd


def drop_invalid(df: pd.DataFrame) -> pd.DataFrame:
    """丢弃 close 为 NaN 的行，按日期去重并保持升序。"""
    if df is None or df.empty:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "vol"])
    out = df.dropna(subset=["close"]).copy()
    out = out.drop_duplicates(subset=["date"], keep="last")
    return out.sort_values("date").reset_index(drop=True)


def reindex_to_calendar(df: pd.DataFrame, calendar) -> pd.DataFrame:
    """按交易日历补齐停牌日。calendar 为升序日期序列（str 或 Timestamp）。

    补齐规则：close/high/low/open 前向填充；vol 填 0。
    """
    if df is None or df.empty:
        return df
    cal = pd.to_datetime(pd.Index(calendar)).strftime("%Y-%m-%d")
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    out = out.set_index("date").reindex(cal)
    out.index.name = "date"
    for c in ("open", "high", "low", "close"):
        out[c] = out[c].ffill()
    out["vol"] = out["vol"].fillna(0.0)
    return out.reset_index()


def fetch_trade_calendar(start: str, end: str) -> Optional[list]:
    """获取交易日历（akshare）。失败返回 None，调用方降级为不对齐。"""
    try:
        import akshare as ak

        s = ak.tool_trade_date_hist_sina()
        d = pd.to_datetime(s["trade_date"]).dt.strftime("%Y-%m-%d")
        return [x for x in d if start <= x <= end]
    except Exception:  # noqa: BLE001
        return None


def clean(df: pd.DataFrame, calendar=None) -> pd.DataFrame:
    """标准清洗入口：丢无效行 →（可选）按交易日历补齐。"""
    out = drop_invalid(df)
    if calendar:
        out = reindex_to_calendar(out, calendar)
    return out
