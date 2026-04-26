from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from init_db import init_db
from api.routes_config import router as config_router
from api.routes_trading import router as trading_router
from api.routes_dashboard import router as dashboard_router
from api.routes_backtest import router as backtest_router
from api.websocket import router as ws_router

init_db()

app = FastAPI(title="binance-deepseek-n-trading-bot")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

app.include_router(config_router)
app.include_router(trading_router)
app.include_router(dashboard_router)
app.include_router(backtest_router)
app.include_router(ws_router)


@app.get("/")
def root():
    return {"ok": True, "msg": "backend running"}
