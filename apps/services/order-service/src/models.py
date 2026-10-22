from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Numeric, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from .database import Base
from .config import DATABASE_URL

table_args_order = {"schema": "orders"} if "postgresql" in DATABASE_URL else {}
table_args_items = {"schema": "orders"} if "postgresql" in DATABASE_URL else {}

class Order(Base):
    __tablename__ = "orders"
    __table_args__ = table_args_order

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True, nullable=False)
    total_amount = Column(Numeric(10, 2), nullable=False)
    status = Column(String(32), nullable=False, default="pending")  # 'pending', 'confirmed', 'failed', 'cancelled'
    idempotency_key = Column(String(128), unique=True, index=True, nullable=True)
    shipping_address = Column(Text, nullable=True)
    payment_id = Column(String(64), nullable=True)
    failure_reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")

class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = table_args_items

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(
        Integer,
        ForeignKey("orders.orders.id" if "postgresql" in DATABASE_URL else "orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    product_id = Column(Integer, nullable=False, index=True)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Numeric(10, 2), nullable=False)

    order = relationship("Order", back_populates="items")
