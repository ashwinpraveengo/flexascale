from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime
from .database import Base
from .config import DATABASE_URL

table_args = {"schema": "inventory"} if "postgresql" in DATABASE_URL else {}

class InventoryItem(Base):
    __tablename__ = "inventory"
    __table_args__ = table_args

    product_id = Column(Integer, primary_key=True, index=True)
    stock_quantity = Column(Integer, nullable=False, default=0)
    reserved_quantity = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

class Reservation(Base):
    __tablename__ = "reservations"
    __table_args__ = table_args

    id = Column(String(64), primary_key=True, index=True)
    order_id = Column(Integer, index=True, nullable=True)
    product_id = Column(Integer, nullable=False, index=True)
    quantity = Column(Integer, nullable=False)
    status = Column(String(32), nullable=False, default="reserved")  # 'reserved', 'confirmed', 'released'
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime(timezone=True), nullable=True)
