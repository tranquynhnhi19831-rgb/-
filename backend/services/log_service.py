from models.log import Log


def add_log(db, message: str, level: str = "INFO", category: str = "system") -> None:
    db.add(Log(level=level, category=category, message=message))
    db.commit()
