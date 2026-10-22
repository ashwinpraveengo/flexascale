from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

class UserRegister(BaseModel):
    email: str = Field(..., min_length=3)
    password: str = Field(..., min_length=6)
    full_name: str = Field(..., min_length=1)
    address: Optional[str] = None
    role: Optional[str] = "customer"

class UserLogin(BaseModel):
    email: str
    password: str

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    address: Optional[str] = None
    password: Optional[str] = Field(None, min_length=6)

class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    address: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut

class TokenPayload(BaseModel):
    sub: str  # user_id
    email: str
    role: str
    exp: int
