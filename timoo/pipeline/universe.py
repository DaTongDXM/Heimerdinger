"""阶段① U-1~U-4：构建 universe。

规则（规范 §1.0）：
- 保留：沪深主板 + 创业板（600/601/603/605/000/001/002/003/300/301）
- 剔除：科创板 688/689、北交所 43/83/87/92（及 8 开头其余）、ST/*ST/退
- 剔除：上市不足 130 个交易日次新股（U-3）
- ST 判定必须每次运行重新执行，禁止使用缓存名单（U-2）
"""

from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd

from ..config import EXCLUDE_PREFIXES, KEEP_PREFIXES, ST_KEYWORDS


_EM_CLIST_URL = "https://82.push2.eastmoney.com/api/qt/clist/get"
# 分段拉取：单次查询覆盖全部板块时返回数据量过大，部分网络环境下会被服务端断开。
_EM_SEGMENTS = ("m:0+t:6,m:0+t:80", "m:1+t:2,m:1+t:23")


def _fetch_spot_by_segments(pz: int = 100, sleep: float = 0.6) -> pd.DataFrame:
    """兜底：按板块分段请求东财 clist 接口，合并去重。"""
    import time

    import requests

    rows: dict = {}
    for fs in _EM_SEGMENTS:
        pn = 1
        while True:
            params = {"pn": pn, "pz": pz, "po": 1, "np": 1, "fltt": 2, "invt": 2,
                      "fid": "f12", "fs": fs, "fields": "f12,f14"}
            r = requests.get(_EM_CLIST_URL, params=params, timeout=15)
            r.raise_for_status()
            js = r.json() or {}
            data = js.get("data") or {}
            diff = data.get("diff") or []
            if not diff:
                break
            for it in diff:
                code = str(it.get("f12", "")).strip()
                if code:
                    rows[code] = str(it.get("f14", "")).strip()
            total = int(data.get("total") or 0)
            if pn * pz >= total:
                break
            pn += 1
            time.sleep(sleep)
    if not rows:
        raise RuntimeError("分段拉取未获得任何股票")
    return pd.DataFrame([{"代码": c, "名称": n} for c, n in rows.items()])


def fetch_spot(retries: int = 2, sleep: float = 2.0) -> pd.DataFrame:
    """拉取全市场 A 股快照（代码 + 名称）。

    主路径：``ak.stock_zh_a_spot_em``；失败则降级为分段直连东财接口。
    """
    import time

    try:
        import akshare as ak  # lazy import：未安装时 CLI 仍可 --help

        last: Exception | None = None
        for i in range(retries):
            try:
                return ak.stock_zh_a_spot_em()
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(sleep)
        raise RuntimeError(f"akshare 快照失败: {last}") from last
    except RuntimeError:
        return _fetch_spot_by_segments()
    except ImportError:
        return _fetch_spot_by_segments()


def _norm_code(code: Any) -> str:
    return str(code).strip().zfill(6)


def _is_kept_board(code: str) -> bool:
    return code.startswith(KEEP_PREFIXES)


def _is_excluded_board(code: str) -> bool:
    return code.startswith(EXCLUDE_PREFIXES)


def _is_st(name: Any) -> bool:
    n = str(name or "").upper()
    return any(k in n for k in ST_KEYWORDS)


def build_universe(spot: pd.DataFrame) -> pd.DataFrame:
    """按板块前缀与名称过滤，返回含剔除理由的全量快照。

    返回列：code, name, in_universe, exclude_reason
    次新股（U-3）在日线长度已知后由 ``mark_new_stocks`` 二次标记。
    """
    code_col = next((c for c in spot.columns if c in ("代码", "code", "symbol")), None)
    name_col = next((c for c in spot.columns if c in ("名称", "name")), None)
    if code_col is None or name_col is None:
        raise ValueError(f"spot 数据缺少代码/名称列，实际列：{list(spot.columns)}")

    rows: List[Dict[str, Any]] = []
    for _, r in spot.iterrows():
        code = _norm_code(r[code_col])
        name = str(r[name_col] or "")
        reason = ""
        if _is_excluded_board(code):
            reason = "科创板/北交所"
        elif not _is_kept_board(code):
            reason = "非沪深主板/创业板"
        elif _is_st(name):
            reason = "ST/退市风险"
        rows.append(
            {
                "code": code,
                "name": name,
                "in_universe": 0 if reason else 1,
                "exclude_reason": reason,
            }
        )
    return pd.DataFrame(rows)


def in_universe_codes(uni: pd.DataFrame) -> List[str]:
    return uni.loc[uni["in_universe"] == 1, "code"].tolist()


def mark_new_stocks(uni: pd.DataFrame, kline_len: Dict[str, int], min_days: int) -> pd.DataFrame:
    """U-3：日线长度不足 min_days 的标记为次新股并剔除。

    说明：spot 快照不含上市日期，用实际可获取的日线长度判定，避免额外请求。
    """
    def _flag(row):
        if row["in_universe"] != 1:
            return row
        if kline_len.get(row["code"], 0) < min_days:
            row = row.copy()
            row["in_universe"] = 0
            row["exclude_reason"] = f"次新股(日线<{min_days})"
        return row

    return uni.apply(_flag, axis=1)
