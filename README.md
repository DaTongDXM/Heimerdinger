# Heimerdinger

个人短线交易纪律执行系统。**不是选股工具，是纪律执行工具**——把「位置优先 → 信号确认 → 类型化出入场规则 → 观察池跟踪」固化为每日流水线。

规范来源：《个人短线交易系统框架规范 v1.3》，完整需求见 [`docs/`](./docs)。

## 快速开始

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

python -m heimerdinger.cli selftest              # 规则自检（23 项，不需要网络）
python -m heimerdinger.cli simulate --stocks 30  # 离线端到端（合成数据，不需要网络）
python -m heimerdinger.cli init                  # 初始化数据库
python -m heimerdinger.cli universe              # 构建 universe
python -m heimerdinger.cli fetch --limit 50      # 拉取日线（首次建议 --full）
python -m heimerdinger.cli scan --limit 50       # 全流程扫描，输出候选清单
```

候选清单落盘在 `data/candidates/YYYY-MM-DD.json`。

## 命令

| 命令 | 说明 |
|------|------|
| `init` | 初始化 SQLite 与参数版本 |
| `universe` | 构建 universe（板块前缀 + ST 动态重判 + 次新股剔除） |
| `fetch` | 日线增量/全量更新（AKShare 主源 + 腾讯兜底） |
| `scan` | 全流程：位置分类 → 信号筛选 → 类型匹配 → 候选清单 |
| `selftest` | 规则自检（32 项：N1-N8 + 入场单 8 项 + 位置分类 + 出场引擎 + 观察池） |
| `simulate` | 离线端到端，合成数据验证流水线（不需要网络） |
| `order` | 创建入场单（8 项强制校验，缺项拒存，冷却期拦截） |
| `monitor` | 出场判定（按入场时锁定的规则，`--confirm` 执行并入观察池） |
| `watch` | 观察池再入场触发检查（`--sweep` 执行 20 日到期清理） |

## 当前进度

已完成 **M1 数据底座 + M2 筛选闭环 + M3 纪律闭环 + M4 可视化**（T01-T10）：

- [x] 参数集中管理 + 版本化（结果可复现）
- [x] universe 过滤（U-1~U-4）
- [x] 日线获取（qfq 前复权、主备切换、失败清单不阻塞）
- [x] 增量缓存（SQLite）
- [x] 指标层（MA / KDJ / MACD / 量能）
- [x] 位置三分类 + 硬过滤（含 Q1 自适应平台、Q9 趋势约束）
- [x] 信号族 + 有效组合校验（N1 单独 KDJ 金叉无效）
- [x] 类型匹配 A/B/C（含 Q4 加仓计划）
- [x] T07 入场单 8 项落库 + 强制校验（append-only，盈利后 30 分钟拦截）
- [x] T08 出场引擎（按类型分派 E-A/E-B/E-C）+ 观察池（预写再入场触发）
- [x] T09-T10 FastAPI 薄层 + Web UI（`start.bat` 一键启动，浏览器打开 http://127.0.0.1:8100）
- [ ] T11 月度统计完善（API 已有简版：分类型胜率 / PAR / 样本门禁）
- [ ] T12 定时任务（15:30 后自动跑全流程）

## Web UI（npm 工程化：Vue3 + TypeScript + Vite + Element Plus）

```bash
cd web
npm install
npm run dev        # 开发：http://localhost:5173，/api 自动代理到 8100
npm run typecheck  # vue-tsc 类型检查
npm run build      # 构建：产物 web/dist/，由 FastAPI 托管
```

生产模式：双击 `start.bat`（首次自动构建前端再启动 API），浏览器打开 <http://127.0.0.1:8100>。

五个页面：**候选池**（按类型分组 + 加仓计划）、**入场单**（8 项表单 + append-only 列表）、**持仓**（出场动作 + 确认执行）、**观察池**（再入场触发 + 剩余天数）、**复盘**（PAR / 分类型统计 / 违规记录 / 20 笔样本门禁进度条）。

```
web/src/
├── main.ts / App.vue        # 入口与布局（顶栏 + tab 切换）
├── api/index.ts             # API 封装（fetch）
├── types.ts                 # 类型定义（Candidate/EntryOrder/...）
├── styles/global.css        # 全局样式（涨红跌绿 A 股配色）
└── views/
    ├── CandidatesView.vue   # 候选池
    ├── OrderView.vue        # 入场单
    ├── HoldingsView.vue     # 持仓
    ├── WatchView.vue        # 观察池
    └── StatsView.vue        # 复盘
```

## 设计要点

- **先位置、后信号**：下跌中继在阶段②被硬过滤，不进入信号计算。
- **口径强制**：所有指标基于 T-1 及以前收盘数据，指标模块不接受盘中价参数。
- **参数版本化**：每次运行记录 `param_version`，同一参数 + 同一日线快照 → 结果一致。
- **禁止事项内建**：N1-N8 由 `heimerdinger/guard.py` 统一拦截，资金流相关逻辑无任何代码路径。

## 网络说明

行情接口为东财 / 腾讯公开接口。若环境存在 `HTTP_PROXY` 导致连接被拒，程序默认直连；
需要走代理时设置环境变量 `HEIMERDINGER_USE_PROXY=1`。

## 文档

| 文档 | 用途 |
|------|------|
| [docs/README.md](./docs/README.md) | 文档索引与决策状态 |
| [docs/PRD.md](./docs/PRD.md) | 需求池 P0/P1/P2、验收标准 |
| [docs/STRATEGY_SPEC.md](./docs/STRATEGY_SPEC.md) | 规则工程化规格（开发唯一依据） |
| [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) | 架构、数据模型、任务列表 |
| [docs/ROADMAP.md](./docs/ROADMAP.md) | 路线图与优先级 |
| [docs/METRICS.md](./docs/METRICS.md) | 北极星指标 PAR 与验证闭环 |

---

仅供个人研究使用，不构成投资建议。
