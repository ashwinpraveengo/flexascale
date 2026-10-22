from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field

class CategoryBase(BaseModel):
    name: str = Field(..., min_length=1)
    slug: str = Field(..., min_length=1)
    description: Optional[str] = None

class CategoryCreate(CategoryBase):
    pass

class CategoryOut(CategoryBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True

class ProductBase(BaseModel):
    name: str = Field(..., min_length=1)
    slug: str = Field(..., min_length=1)
    description: Optional[str] = None
    price: float = Field(..., ge=0)
    category_id: Optional[int] = None
    image_url: Optional[str] = None
    is_active: bool = True

class ProductCreate(ProductBase):
    pass

class ProductUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = Field(None, ge=0)
    category_id: Optional[int] = None
    image_url: Optional[str] = None
    is_active: Optional[bool] = None

class ProductOut(ProductBase):
    id: int
    created_at: datetime
    updated_at: datetime
    category: Optional[CategoryOut] = None

    class Config:
        from_attributes = True

class ProductListResponse(BaseModel):
    items: List[ProductOut]
    total: int
    page: int
    limit: int
