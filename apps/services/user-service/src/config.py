import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/ecommerce")
JWT_SECRET = os.getenv("JWT_SECRET", "super-secret-jwt-key-for-shopping-app-2026")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRATION_MINUTES = int(os.getenv("JWT_EXPIRATION_MINUTES", "1440"))
SERVICE_NAME = os.getenv("SERVICE_NAME", "user-service")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8001"))
