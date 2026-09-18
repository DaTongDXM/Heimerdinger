"""阶段① 数据源：腾讯财经（AKShare 封装主源 + 腾讯直连兜底）。

规范 §1.1 / D-1 / D-2（2026-09-18 修订：东财接口全部移除，按用户要求
只使用「腾讯财经实时接口 + AKShare 封装」）：
- 统一前复权 qfq；成交量统一为「手」
- 主源：ak.stock_zh_a_hist_tx（AKShare 的腾讯封装）
- 兜底：腾讯 ifzq.gtimg.cn fqkline 直连（不经 akshare，防封装失效）
- 主源失败重试 MAX_RETRY 次，再切直连；仍失败记入失败清单，不阻塞
- 腾讯源 symbol 需带 sh/sz 前缀
"""

from __future__ import annotations

import time
from typing import Optional, Tuple

import pandas as pd

_STD_COLS = ["date", "open", "high", "low", "close", "vol"]

_TX_MAP = {
    "date": "date", "open": "open", "high": "high",
    "low": "low", "close": "close", "volume": "vol",
}

_TX_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"


def configure_network(disable_proxy: bool = True) -> None:
    """网络环境配置。

    某些环境下存在 HTTP(S)_PROXY 环境变量，requests 会走代理，而代理可能拒绝
    行情域名（表现为 ProxyError / RemoteDisconnected）。本项目仅访问腾讯与
    AKShare 封装的公开行情接口，默认直连。需要代理时设置环境变量 TIMOO_USE_PROXY=1。
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


def fetch_tencent(code: str, start: str, end: str, adjust: str = "qfq") -> pd.DataFrame:
    """主源：ak.stock_zh_a_hist_tx（AKShare 腾讯封装）。

    注意：该封装 volume 单位为「股」，统一除以 100 转为「手」。
    start/end 格式 YYYYMMDD。
    """
    import akshare as ak

    df = ak.stock_zh_a_hist_tx(symbol=_to_tencent_symbol(code),
                               start_date=start, end_date=end, adjust=adjust)
    out = _normalize(df, _TX_MAP)
    out["vol"] = out["vol"] / 100.0  # 股 → 手
    return out


def fetch_tencent_direct(code: str, start: str, end: str,
                         adjust: str = "qfq") -> pd.DataFrame:
    """兜底：腾讯 ifzq.gtimg.cn fqkline 直连。

    返回数组字段序为 [date, open, close, high, low, vol]（close 在前！），
    volume 单位已是「手」。
    """
    import requests
    from datetime import datetime, timedelta

    sym = _to_tencent_symbol(code)
    # 腾讯直连的 end 为开区间，+1 天保证包含 end 当日
    end_dt = datetime.strptime(end, "%Y%m%d") + timedelta(days=1)
    s = f"{start[:4]}-{start[4:6]}-{start[6:]}"
    e = end_dt.strftime("%Y-%m-%d")
    # 单次最多 800 根；HISTORY_DAYS=250 交易日足够
    param = f"{sym},day,{s},{e},800,{adjust}"
    r = requests.get(_TX_KLINE_URL, params={"param": param}, timeout=15)
    r.raise_for_status()
    js = r.json() or {}
    d = (js.get("data") or {}).get(sym) or {}
    bars = d.get(f"{adjust}day") or d.get("day") or []
    if not bars:
        raise ValueError(f"腾讯直连无K线数据: {sym}")
    rows = [
        {"date": b[0], "open": b[1], "close": b[2],
         "high": b[3], "low": b[4], "vol": b[5]}
        for b in bars
    ]
    return _normalize(pd.DataFrame(rows), {})


def fetch_with_fallback(code: str, start: str, end: str,
                        max_retry: int = 2, sleep: float = 0.5,
                        adjust: str = "qfq") -> Tuple[Optional[pd.DataFrame], str, Optional[str]]:
    """返回 (df, source, error)。df 为 None 表示两源均失败。

    source ∈ {tencent-ak, tencent-direct, failed}。
    """
    last_err = None
    for i in range(max_retry):
        try:
            return fetch_tencent(code, start, end, adjust), "tencent-ak", None
        except Exception as e:  # noqa: BLE001 - 数据源异常需吞掉并切源
            last_err = f"tencent-ak#{i + 1}: {type(e).__name__}: {e}"
            time.sleep(sleep)
    try:
        return fetch_tencent_direct(code, start, end, adjust), "tencent-direct", None
    except Exception as e:  # noqa: BLE001
        last_err = f"{last_err} | tencent-direct: {type(e).__name__}: {e}"
        return None, "failed", last_err


def throttle(params) -> None:
    """限速：sleep 0.3~0.5s（规范 §1.4）。"""
    import random

    time.sleep(random.uniform(params["SLEEP_MIN"], params["SLEEP_MAX"]))
