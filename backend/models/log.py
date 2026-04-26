from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.sql import func
from models.database import Base


class Log(Base):
    __tablename__ = "logs"
    id = Column(Integer, primary_key=True, index=True)
    level = Column(String, default="INFO")
    category = Column(String, default="system")
    message = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
