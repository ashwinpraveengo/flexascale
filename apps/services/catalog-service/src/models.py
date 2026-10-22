from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, Numeric, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from .database import Base
from .config import DATABASE_URL

table_args = {"schema": "catalog"} if "postgresql" in DATABASE_URL else {}

class Category(Base):
    __tablename__ = "categories"
    __table_args__ = table_args

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    slug = Column(String(100), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    products = relationship("Product", back_populates="category")

class Product(Base):
    __tablename__ = "products"
    __table_args__ = table_args

    id = Column(Integer, primary_key=True, index=True)
    category_id = Column(
        Integer,
        ForeignKey("catalog.categories.id" if "postgresql" in DATABASE_URL else "categories.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )
    name = Column(String(255), nullable=False)
    slug = Column(String(255), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    price = Column(Numeric(10, 2), nullable=False, index=True)
    image_url = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    category = relationship("Category", back_populates="products")
