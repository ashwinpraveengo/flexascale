import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/ecommerce")
SERVICE_NAME = os.getenv("SERVICE_NAME", "catalog-service")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8002"))
