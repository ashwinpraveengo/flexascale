import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/ecommerce")
SERVICE_NAME = os.getenv("SERVICE_NAME", "inventory-service")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8005"))
RESERVATION_EXPIRY_MINUTES = int(os.getenv("RESERVATION_EXPIRY_MINUTES", "15"))
