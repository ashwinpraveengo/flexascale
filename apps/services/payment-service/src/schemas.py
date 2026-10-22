from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

class PaymentProcessRequest(BaseModel):
    order_id: int
    amount: float = Field(..., gt=0)
    card_number: Optional[str] = "4000000000000001"  # simulated test card
    payment_method: Optional[str] = "simulated_card"
    idempotency_key: Optional[str] = None
    simulate_failure: Optional[bool] = False
    delay_ms: Optional[int] = None

class PaymentProcessResponse(BaseModel):
    transaction_id: str
    order_id: int
    amount: float
    status: str  # 'success', 'failed'
    payment_method: str
    failure_message: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

class PaymentOut(BaseModel):
    id: int
    transaction_id: str
    order_id: int
    amount: float
    status: str
    payment_method: str
    idempotency_key: Optional[str] = None
    failure_message: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
