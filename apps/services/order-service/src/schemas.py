from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field

class CheckoutItem(BaseModel):
    product_id: int
    quantity: int = Field(..., ge=1)

class CheckoutRequest(BaseModel):
    user_id: int
    items: Optional[List[CheckoutItem]] = None  # If omitted, pulls directly from cart-service
    shipping_address: str = Field(..., min_length=3)
    card_number: Optional[str] = "4000000000000001"
    payment_method: Optional[str] = "simulated_card"
    simulate_failure: Optional[bool] = False
    idempotency_key: Optional[str] = None

class OrderItemOut(BaseModel):
    id: int
    product_id: int
    quantity: int
    unit_price: float
    subtotal: float

class OrderOut(BaseModel):
    id: int
    user_id: int
    total_amount: float
    status: str  # 'pending', 'confirmed', 'failed', 'cancelled'
    shipping_address: Optional[str] = None
    payment_id: Optional[str] = None
    failure_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    items: List[OrderItemOut] = []

    class Config:
        from_attributes = True
