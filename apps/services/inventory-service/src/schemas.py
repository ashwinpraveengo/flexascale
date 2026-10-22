from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field

class InventoryOut(BaseModel):
    product_id: int
    stock_quantity: int
    reserved_quantity: int
    available_quantity: int
    updated_at: datetime

class StockUpdateRequest(BaseModel):
    stock_quantity: int = Field(..., ge=0)

class StockAdjustRequest(BaseModel):
    adjustment: int  # can be positive (replenish) or negative (shrinkage)

class ReserveItem(BaseModel):
    product_id: int
    quantity: int = Field(..., ge=1)

class ReserveRequest(BaseModel):
    order_id: Optional[int] = None
    items: List[ReserveItem]

class ReservationItemOut(BaseModel):
    reservation_id: str
    product_id: int
    quantity: int
    status: str

class ReserveResponse(BaseModel):
    success: bool
    reservations: List[ReservationItemOut]

class ConfirmReleaseRequest(BaseModel):
    order_id: Optional[int] = None
    reservation_ids: Optional[List[str]] = None
