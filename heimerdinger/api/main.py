"""FastAPI 应用入口。

启动：
    python -m heimerdinger.api.main          # 直接运行
    uvicorn heimerdinger.api.main:app --port 8100
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from ..pipeline.data_source import configure_network
from .routes import router

ROOT = Path(__file__).resolve().parents[2]

# API 进程同样需要直连行情域名（绕过系统代理），与 CLI 行为一致
import os  # noqa: E402

configure_network(os.environ.get("HEIMERDINGER_USE_PROXY", "") != "1")

app = FastAPI(title="Heimerdinger", version="0.1.0",
              description="个人短线交易纪律执行系统 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

# 前端构建产物（web/dist，npm run build 生成）；开发时走 vite dev + proxy
web_dist = ROOT / "web" / "dist"
if web_dist.exists():
    app.mount("/", StaticFiles(directory=str(web_dist), html=True), name="web")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("heimerdinger.api.main:app", host="127.0.0.1", port=8100, reload=False)
