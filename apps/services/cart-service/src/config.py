import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/ecommerce")
CATALOG_SERVICE_URL = os.getenv("CATALOG_SERVICE_URL", "http://catalog-service:8002")
INVENTORY_SERVICE_URL = os.getenv("INVENTORY_SERVICE_URL", "http://inventory-service:8005")
SERVICE_NAME = os.getenv("SERVICE_NAME", "cart-service")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8003"))
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "5.0"))
