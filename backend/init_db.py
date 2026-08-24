from models.database import Base, engine
from models import (  # noqa
    account_snapshot,
    config_model,
    log,
    position,
    risk_event,
    signal,
    trade,
    trade_decision,
)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


if __name__ == "__main__":
    init_db()
    print("SQLite 数据库初始化完成: backend/data/trading.db")
