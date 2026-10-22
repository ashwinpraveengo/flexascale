from datetime import datetime, timezone
from sqlalchemy import Column, Integer, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from .database import Base
from .config import DATABASE_URL

table_args_cart = {"schema": "cart"} if "postgresql" in DATABASE_URL else {}
table_args_items = {"schema": "cart"} if "postgresql" in DATABASE_URL else {}

class Cart(Base):
    __tablename__ = "carts"
    __table_args__ = table_args_cart

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, unique=True, index=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    items = relationship("CartItem", back_populates="cart", cascade="all, delete-orphan")

class CartItem(Base):
    __tablename__ = "cart_items"
    __table_args__ = (
        UniqueConstraint("cart_id", "product_id", name="uq_cart_product"),
        {"schema": "cart"} if "postgresql" in DATABASE_URL else {}
    )

    id = Column(Integer, primary_key=True, index=True)
    cart_id = Column(
        Integer,
        ForeignKey("cart.carts.id" if "postgresql" in DATABASE_URL else "carts.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    product_id = Column(Integer, nullable=False, index=True)
    quantity = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    cart = relationship("Cart", back_populates="items")
