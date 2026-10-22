from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Numeric, Text, DateTime
from .database import Base
from .config import DATABASE_URL

table_args = {"schema": "payments"} if "postgresql" in DATABASE_URL else {}

class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = table_args

    id = Column(Integer, primary_key=True, index=True)
    transaction_id = Column(String(64), unique=True, index=True, nullable=False)
    order_id = Column(Integer, index=True, nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    status = Column(String(32), nullable=False)  # 'success', 'failed', 'pending'
    payment_method = Column(String(64), nullable=False, default="simulated_card")
    idempotency_key = Column(String(128), unique=True, index=True, nullable=True)
    failure_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
