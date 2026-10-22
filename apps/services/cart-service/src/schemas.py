from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field

class CartItemAdd(BaseModel):
    product_id: int
    quantity: int = Field(1, ge=1)

class CartItemUpdate(BaseModel):
    quantity: int = Field(..., ge=1)

class CartItemOut(BaseModel):
    id: int
    product_id: int
    quantity: int
    product_name: Optional[str] = None
    unit_price: Optional[float] = None
    subtotal: Optional[float] = None
    image_url: Optional[str] = None
    in_stock: Optional[bool] = None

class CartOut(BaseModel):
    id: int
    user_id: int
    items: List[CartItemOut]
    total_items: int
    total_amount: float
    updated_at: datetime
