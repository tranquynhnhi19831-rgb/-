from models.database import Base, engine
from models import (  # noqa
    account_snapshot,
    config_model,
    log,
    paper_order_intent,
    position,
    risk_event,
    runtime_state,
    signal,
    trade,
    trade_decision,
)
from services.schema_migration import run_schema_migrations, verify_required_schema


def init_db() -> None:
    # `create_all` creates brand-new tables but intentionally does not alter an
    # existing SQLite table. Explicit versioned migrations handle known upgrades
    # and the final verifier fails closed on any unresolved schema drift.
    Base.metadata.create_all(bind=engine)
    run_schema_migrations(engine)
    verify_required_schema(engine)


if __name__ == "__main__":
    init_db()
    print("SQLite 数据库初始化/迁移完成: backend/data/trading.db")
