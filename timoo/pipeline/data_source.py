"""阶段① 数据源：AKShare 主源 + 腾讯财经备用源。

规范 §1.1 / D-1 / D-2：
- 统一前复权 qfq
- 主源失败重试 MAX_RETRY 次，再切腾讯源；仍失败记入失败清单，不阻塞
- 腾讯源 symbol 需带 sh/sz 前缀
"""

from __future__ import annotations

import time
from typing import Optional, Tuple

import pandas as pd

_STD_COLS = ["date", "open", "high", "low", "close", "vol"]

_AK_MAP = {
    "日期": "date", "开盘": "open", "最高": "high",
    "最低": "low", "收盘": "close", "成交量": "vol",
}
_TX_MAP = {
    "date": "date", "open": "open", "high": "high",
    "low": "low", "close": "close", "volume": "vol",
}


def configure_network(disable_proxy: bool = True) -> None:
    """网络环境配置。

    某些环境下存在 HTTP(S)_PROXY 环境变量，requests 会走代理，而代理可能拒绝
    行情域名（表现为 ProxyError / RemoteDisconnected）。本项目仅访问东财与腾讯
    公开行情接口，默认直连。需要代理时设置环境变量 TIMOO_USE_PROXY=1。
    """
    import os

    if not disable_proxy:
        return
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"
    try:
        import requests

        if getattr(requests.Session, "_timoo_patched", False):
            return
        _orig_init = requests.Session.__init__

        def _init(self, *args, **kwargs):  # noqa: ANN001
            _orig_init(self, *args, **kwargs)
            self.trust_env = False

        requests.Session.__init__ = _init
        requests.Session._timoo_patched = True
    except Exception:  # noqa: BLE001 - requests 不可用时跳过
        pass


def _to_tencent_symbol(code: str) -> str:
    """6 开头 → sh；0/3 开头 → sz。"""
    if code.startswith("6"):
        return f"sh{code}"
    return f"sz{code}"


def _normalize(df: pd.DataFrame, mapping: dict) -> pd.DataFrame:
    df = df.rename(columns=mapping)
    missing = [c for c in _STD_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"K线缺列: {missing}, 实际: {list(df.columns)}")
    out = df[_STD_COLS].copy()
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    for c in ("open", "high", "low", "close", "vol"):
        out[c] = pd.to_numeric(out[c], errors="coerce")
    return out.sort_values("date").reset_index(drop=True)


def fetch_akshare(code: str, start: str, end: str, adjust: str = "qfq") -> pd.DataFrame:
    """主源：ak.stock_zh_a_hist。start/end 格式 YYYYMMDD。"""
    import akshare as ak

    df = ak.stock_zh_a_hist(symbol=code, period="daily",
                            start_date=start, end_date=end, adjust=adjust)
    return _normalize(df, _AK_MAP)


def fetch_tencent(code: str, start: str, end: str, adjust: str = "qfq") -> pd.DataFrame:
    """备用源：ak.stock_zh_a_hist_tx。"""
    import akshare as ak

    df = ak.stock_zh_a_hist_tx(symbol=_to_tencent_symbol(code),
                               start_date=start, end_date=end, adjust=adjust)
    return _normalize(df, _TX_MAP)


def fetch_with_fallback(code: str, start: str, end: str,
                        max_retry: int = 2, sleep: float = 0.5,
                        adjust: str = "qfq") -> Tuple[Optional[pd.DataFrame], str, Optional[str]]:
    """返回 (df, source, error)。df 为 None 表示两源均失败。"""
    last_err = None
    for i in range(max_retry):
        try:
            return fetch_akshare(code, start, end, adjust), "akshare", None
        except Exception as e:  # noqa: BLE001 - 数据源异常需吞掉并切源
            last_err = f"akshare#{i + 1}: {type(e).__name__}: {e}"
            time.sleep(sleep)
    try:
        return fetch_tencent(code, start, end, adjust), "tencent", None
    except Exception as e:  # noqa: BLE001
        last_err = f"{last_err} | tencent: {type(e).__name__}: {e}"
        return None, "failed", last_err


def throttle(params) -> None:
    """限速：sleep 0.3~0.5s（规范 §1.4）。"""
    import random

    time.sleep(random.uniform(params["SLEEP_MIN"], params["SLEEP_MAX"]))
