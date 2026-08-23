from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes_public import router as public_router
from init_db import init_db

init_db()

# This is intentionally a separate FastAPI application. It does NOT include
# config, start/stop, backtest or execution routers. Tencent Cloud should expose
# this app publicly and keep backend.main private/loopback-only.
app = FastAPI(
    title="jianghe-quant-public-dashboard",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)
app.include_router(public_router)


@app.get("/")
def root():
    return {
        "ok": True,
        "service": "jianghe-quant-public-dashboard",
        "mode": "READ_ONLY",
    }
