# Heimerdinger 部署文档

> 部署时间：2026-09-21 · 服务器：腾讯云轻量应用服务器（北京）

## 1. 环境信息

| 项目 | 值 |
| --- | --- |
| 实例 ID | `lhins-1t2o6032`（地域 `ap-beijing`） |
| 公网 IP | `62.234.122.179` |
| 系统 | Ubuntu 22.04（内核 5.15，Python 3.10.12，Node v20.18.0） |
| 规格 | 2 核 2G / 50G SSD / 4Mbps |
| 访问地址 | http://62.234.122.179:8100 |
| 防火墙 | 腾讯云控制台已放行 TCP 8100（0.0.0.0/0） |

## 2. 服务器目录布局

```
/opt/heimerdinger/
├── .venv/              # Python 虚拟环境（akshare/pandas/fastapi/uvicorn）
├── app/                # git 工作树（origin = github.com/DaTongDXM/Heimerdinger）
│   ├── heimerdinger/   # Python 包
│   ├── web/dist/       # 前端构建产物（FastAPI 挂载到 "/"）
│   └── data/           # 数据库与候选清单（git ignored）
│       ├── heimerdinger.db
│       ├── candidates/<日期>.json
│       └── failed/<日期>.json
└── daily_scan.py       # 定时任务入口：调 POST /api/scan/run
```

数据库路径由 `storage/db.py` 按 `__file__` 推导为 `app/data/heimerdinger.db`，**与工作目录无关**。

## 3. 服务管理

```bash
systemctl status  heimerdinger          # 查看状态
systemctl restart heimerdinger          # 重启
journalctl -u heimerdinger -f           # 实时日志
```

服务定义 `/etc/systemd/system/heimerdinger.service`：

```
WorkingDirectory=/opt/heimerdinger/app
Environment=PYTHONPATH=/opt/heimerdinger/app
ExecStart=/opt/heimerdinger/.venv/bin/uvicorn heimerdinger.api.main:app --host 0.0.0.0 --port 8100
Restart=always
```

已 `systemctl enable`：开机自启、崩溃自动拉起。

## 4. 定时扫描

用 systemd timer（未使用 crontab）：

```
/etc/systemd/system/heimerdinger-daily.timer   → 周一至周五 15:30（Persistent=true，错过会补跑）
/etc/systemd/system/heimerdinger-daily.service → 执行 daily_scan.py
```

```bash
systemctl list-timers | grep heimerdinger      # 查看下次触发时间
journalctl -u heimerdinger-daily -n 50         # 查看执行日志
```

`daily_scan.py` 通过 `POST http://127.0.0.1:8100/api/scan/run` 触发，走 API 的后台线程：
带进度、防重入、候选实时落盘。

**首次建库**耗时较长（4414 只标的日线，约 2~3 小时），之后每天仅做增量
（`cache.update_symbol` 判断 `latest >= upto` 时零请求跳过）。

## 5. 更新代码

```bash
# 本地
cd D:\wxd\code\Heimerdinger
npm --prefix web run build       # 前端有改动时必须先构建
git add -A && git commit -m "..." && git push

# 服务器
cd /opt/heimerdinger/app && git pull
systemctl restart heimerdinger
```

注意两点：

1. **`web/dist` 必须提交**。服务器不装 Node 依赖、不执行构建，
   FastAPI 直接挂载 `web/dist`。`.gitignore` 已移除 `web/dist/` 规则。
2. **服务器直连 GitHub 的 TLS 会被掐断**（`GnuTLS recv error -110`）。
   已配置全局镜像重写：
   ```bash
   git config --global url."https://ghproxy.net/https://github.com/".insteadOf "https://github.com/"
   ```
   `git pull` 因此自动走镜像，`origin` 仍保持标准 GitHub 地址。

## 6. 已验证事项

- 规则自检：`python -m heimerdinger.cli selftest` → **32/32 PASS**
- 数据链路：服务器可访问腾讯行情，`latest_trading_day()` 返回 `2026-09-21`
- 外网访问：`http://62.234.122.179:8100`、`/api/version`、静态资源均 200
- 服务进程常驻、开机自启、崩溃重启

## 7. 已知限制

- 服务器内存 2G 且无物理 swap，已建 2G 交换文件（重启后失效，需时重新
  `fallocate -l 2G /swapfile && mkswap /swapfile && swapon /swapfile`）。
- 通过腾讯云 TAT 下发命令时，部分命令（crontab、端口/进程探测、外部 curl）
  会被判定为敏感而拒绝；定时任务改用 systemd timer，端口探测改由外部发起。
