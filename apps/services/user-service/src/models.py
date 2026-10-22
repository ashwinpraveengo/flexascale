from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime
from .database import Base
from .config import DATABASE_URL

table_args = {"schema": "users"} if "postgresql" in DATABASE_URL else {}

class User(Base):
    __tablename__ = "users"
    __table_args__ = table_args

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False, default="customer")  # 'customer', 'admin'
    address = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
