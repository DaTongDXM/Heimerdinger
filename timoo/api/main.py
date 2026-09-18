"""FastAPI 应用入口。

启动：
    python -m timoo.api.main          # 直接运行
    uvicorn timoo.api.main:app --port 8100
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .routes import router

ROOT = Path(__file__).resolve().parents[2]

app = FastAPI(title="timoo", version="0.1.0",
              description="个人短线交易纪律执行系统 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

# 前端静态页（web/index.html），已注册的 /api 路由优先匹配
web_dir = ROOT / "web"
if web_dir.exists():
    app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("timoo.api.main:app", host="127.0.0.1", port=8100, reload=False)
