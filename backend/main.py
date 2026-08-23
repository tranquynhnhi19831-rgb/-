from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from init_db import init_db
from api.routes_config import router as config_router
from api.routes_trading import router as trading_router
from api.routes_dashboard import router as dashboard_router
from api.routes_backtest import router as backtest_router
from api.routes_testnet import router as testnet_router
from api.websocket import router as ws_router

init_db()

app = FastAPI(title="binance-deepseek-n-trading-bot")

# Private/Admin API is loopback-only in local development and must not be a
# generic browser-accessible localhost service. Only our own local frontend is
# allowed to make cross-origin browser requests. Public read-only CORS lives in
# public_main.py and has a deliberately different policy.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

app.include_router(config_router)
app.include_router(trading_router)
app.include_router(dashboard_router)
app.include_router(backtest_router)
app.include_router(testnet_router)
app.include_router(ws_router)


@app.get("/")
def root():
    return {"ok": True, "msg": "backend running", "visibility": "PRIVATE_ADMIN"}
