from contextlib import asynccontextmanager
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, Header, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text

from .config import SERVICE_NAME
from .database import get_db, init_db, engine
from .models import User
from .schemas import UserRegister, UserLogin, UserUpdate, UserOut, TokenResponse
from .security import hash_password, verify_password, create_access_token, decode_access_token
from .metrics import setup_metrics

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        init_db()
    except Exception as e:
        print(f"Warning: DB init failed at startup (may be waiting for migrations): {e}")
    yield

app = FastAPI(title="User and Authentication Service", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

setup_metrics(app, SERVICE_NAME)

@app.get("/healthz", tags=["Health"])
def health_check():
    return {"status": "ok", "service": SERVICE_NAME}

@app.get("/readyz", tags=["Health"])
def ready_check():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ready", "service": SERVICE_NAME, "database": "connected"}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"Database not ready: {str(e)}")

def get_current_user(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
            headers={"WWW-Authenticate": "Bearer"}
        )
    token = authorization.split(" ")[1]
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is invalid or expired",
            headers={"WWW-Authenticate": "Bearer"}
        )
    user_id = int(payload.get("sub"))
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user

def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required")
    return current_user

@app.post("/api/users/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: UserRegister, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == payload.email.lower()).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

    user = User(
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        address=payload.address,
        role=payload.role if payload.role in ("customer", "admin") else "customer"
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token({"sub": str(user.id), "email": user.email, "role": user.role})
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))

@app.post("/api/users/login", response_model=TokenResponse)
def login(payload: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email.lower()).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    token = create_access_token({"sub": str(user.id), "email": user.email, "role": user.role})
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))

@app.get("/api/users/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user)):
    return UserOut.model_validate(current_user)

@app.put("/api/users/me", response_model=UserOut)
def update_me(payload: UserUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if payload.full_name is not None:
        current_user.full_name = payload.full_name
    if payload.address is not None:
        current_user.address = payload.address
    if payload.password is not None:
        current_user.password_hash = hash_password(payload.password)

    db.commit()
    db.refresh(current_user)
    return UserOut.model_validate(current_user)

@app.get("/api/users/verify-token")
def verify_token_endpoint(authorization: Optional[str] = Header(None), db: Session = Depends(get_db)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing authorization header")
    token = authorization.split(" ")[1]
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    return payload

@app.get("/api/users/{user_id}", response_model=UserOut)
def get_user_by_id(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return UserOut.model_validate(user)

@app.get("/api/users", response_model=List[UserOut])
def list_users(
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin)
):
    users = db.query(User).offset(skip).limit(limit).all()
    return [UserOut.model_validate(u) for u in users]
