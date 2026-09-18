"""阶段① U-1~U-4：构建 universe。

规则（规范 §1.0）：
- 保留：沪深主板 + 创业板（600/601/603/605/000/001/002/003/300/301）
- 剔除：科创板 688/689、北交所 43/83/87/92（及 8 开头其余）、ST/*ST/退
- 剔除：上市不足 130 个交易日次新股（U-3）
- ST 判定必须每次运行重新执行，禁止使用缓存名单（U-2）

数据源（2026-09-18 修订：东财接口全部移除）：
- 代码清单：ak.stock_info_a_code_name（AKShare 封装）
- 名称/ST 状态：腾讯 qt.gtimg.cn 实时报价批量刷新（保证当日 ST 标记最新）
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

import pandas as pd

from ..config import EXCLUDE_PREFIXES, KEEP_PREFIXES, ST_KEYWORDS

_TX_QUOTE_URL = "http://qt.gtimg.cn/q="
_TX_BATCH = 60          # 单次批量报价的股票数
_TX_BATCH_SLEEP = 0.15  # 批次间隔（秒）


def _fetch_tencent_names(codes: List[str]) -> Dict[str, str]:
    """腾讯实时报价批量拉取代码→名称（用于刷新 ST 状态）。

    响应为 GBK 文本：v_sh600000="1~浦发银行~600000~现价~昨收~…";
    字段 [1]=名称，[2]=代码。异常行直接跳过。
    """
    import requests

    names: Dict[str, str] = {}
    for i in range(0, len(codes), _TX_BATCH):
        batch = codes[i:i + _TX_BATCH]
        syms = ",".join(("sh" if c.startswith("6") else "sz") + c for c in batch)
        r = requests.get(_TX_QUOTE_URL + syms, timeout=15)
        r.raise_for_status()
        r.encoding = "gbk"
        for line in r.text.splitlines():
            line = line.strip().rstrip(";")
            if "~" not in line or "=" not in line:
                continue
            try:
                fields = line.split("=", 1)[1].strip('"').split("~")
                code, name = fields[2], fields[1]
            except (IndexError, ValueError):
                continue
            if code in batch and name:
                names[code] = name
        if i + _TX_BATCH < len(codes):
            time.sleep(_TX_BATCH_SLEEP)
    return names


def fetch_spot(retries: int = 2, sleep: float = 2.0) -> pd.DataFrame:
    """拉取全市场 A 股快照（代码 + 名称）。

    ① AKShare 封装拉代码清单（含兜底名称）；
    ② 腾讯实时报价批量刷新名称（U-2：ST 判定用当日最新名称）；
       腾讯批量失败时退回 ① 的名称，不阻塞流程。
    返回列：代码、名称（与东财快照同构，build_universe 无需感知来源）。
    """
    import akshare as ak

    last: Exception | None = None
    base = None
    for i in range(retries):
        try:
            base = ak.stock_info_a_code_name()  # code, name 两列
            break
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(sleep)
    if base is None:
        raise RuntimeError(f"AKShare 代码清单获取失败: {last}") from last

    base = base.rename(columns={"code": "代码", "name": "名称"})
    base["代码"] = base["代码"].astype(str).str.strip().str.zfill(6)
    try:
        tnames = _fetch_tencent_names(base["代码"].tolist())
        if tnames:
            # 腾讯实时名称优先（ST 状态当日最新），缺失的回退 AKShare 名称
            base["名称"] = base["代码"].map(tnames).fillna(base["名称"])
    except Exception:  # noqa: BLE001 - 腾讯批量失败不阻塞，用 AKShare 名称
        pass
    return base[["代码", "名称"]].reset_index(drop=True)


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
