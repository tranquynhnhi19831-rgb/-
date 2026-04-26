from models.database import Base, engine
from models import config_model, trade, signal, position, log, account_snapshot, risk_event  # noqa


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


if __name__ == "__main__":
    init_db()
    print("SQLite 数据库初始化完成: backend/data/trading.db")
