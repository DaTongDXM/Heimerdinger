"""SQLite 建表、连接与参数版本化。

设计原则：
- 入场单（entry_order）append-only：不提供任何 UPDATE 路径。
- 参数版本化：每次运行记录 param_version，保证扫描结果可复现。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_kline (
    code        TEXT NOT NULL,
    date        TEXT NOT NULL,
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    vol         REAL,
    adjust      TEXT DEFAULT 'qfq',
    PRIMARY KEY (code, date)
);

CREATE TABLE IF NOT EXISTS universe_snapshot (
    date            TEXT NOT NULL,
    code            TEXT NOT NULL,
    name            TEXT,
    in_universe     INTEGER NOT NULL,
    exclude_reason  TEXT,
    PRIMARY KEY (date, code)
);

CREATE TABLE IF NOT EXISTS scan_result (
    scan_date       TEXT NOT NULL,
    code            TEXT NOT NULL,
    name            TEXT,
    position        TEXT NOT NULL,
    position_detail TEXT,
    signal          TEXT,
    signal_detail   TEXT,
    trade_type      TEXT,
    halved          INTEGER DEFAULT 0,
    is_candidate    INTEGER DEFAULT 0,
    ref_platform_top REAL,
    ref_platform_bottom REAL,
    ref_ma20        REAL,
    ref_prev_close  REAL,
    param_version   TEXT,
    PRIMARY KEY (scan_date, code)
);

-- 入场单：append-only，禁止 UPDATE
CREATE TABLE IF NOT EXISTS entry_order (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    code                TEXT NOT NULL,
    name                TEXT,
    scan_date           TEXT,
    trade_type          TEXT NOT NULL,
    structure_position  TEXT NOT NULL,
    observed_facts      TEXT NOT NULL,
    stop_loss_price     REAL NOT NULL,
    first_target_price  REAL NOT NULL,
    remainder_protection TEXT NOT NULL,
    time_stop_days      INTEGER NOT NULL,
    self_check_pass     INTEGER NOT NULL,
    entry_price         REAL,
    layers              INTEGER DEFAULT 1,
    status              TEXT DEFAULT 'OPEN',
    created_at          TEXT NOT NULL,
    param_version       TEXT
);

CREATE TABLE IF NOT EXISTS holding (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_order_id  INTEGER NOT NULL,
    open_date       TEXT NOT NULL,
    open_price      REAL NOT NULL,
    layers          INTEGER NOT NULL,
    status          TEXT DEFAULT 'OPEN'
);

CREATE TABLE IF NOT EXISTS exit_record (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_order_id  INTEGER NOT NULL,
    exit_date       TEXT NOT NULL,
    exit_price      REAL NOT NULL,
    hold_days       INTEGER,
    exit_type       TEXT,
    hit_rule        TEXT,
    is_planned      INTEGER DEFAULT 1,
    pnl_pct         REAL
);

CREATE TABLE IF NOT EXISTS watch_pool (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    code              TEXT NOT NULL,
    source_exit_type  TEXT,
    reentry_trigger   TEXT,
    status            TEXT DEFAULT 'ACTIVE',
    entered_date      TEXT NOT NULL,
    cleared_date      TEXT,
    days_remaining    INTEGER
);

CREATE TABLE IF NOT EXISTS violation_log (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    date     TEXT NOT NULL,
    rule_id  TEXT NOT NULL,
    code     TEXT,
    detail   TEXT
);

CREATE TABLE IF NOT EXISTS param_version (
    version        TEXT PRIMARY KEY,
    params_json    TEXT NOT NULL,
    effective_from TEXT NOT NULL,
    note           TEXT
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_kline_code ON daily_kline(code);
CREATE INDEX IF NOT EXISTS idx_scan_date ON scan_result(scan_date);
"""


def get_db_path(root: Optional[Path] = None) -> Path:
    root = Path(root) if root else Path(__file__).resolve().parents[2]
    data_dir = root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "heimerdinger.db"


def connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else get_db_path()
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def record_param_version(conn: sqlite3.Connection, params, note: str = "") -> str:
    """写入参数版本（已存在则跳过）。返回版本号。"""
    import json
    from datetime import date

    version = params.version
    conn.execute(
        "INSERT OR IGNORE INTO param_version(version, params_json, effective_from, note) "
        "VALUES (?,?,?,?)",
        (version, json.dumps(params.as_dict(), sort_keys=True, ensure_ascii=False),
         date.today().isoformat(), note),
    )
    conn.commit()
    return version
