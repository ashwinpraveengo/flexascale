import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/ecommerce")
CATALOG_SERVICE_URL = os.getenv("CATALOG_SERVICE_URL", "http://catalog-service:8002")
CART_SERVICE_URL = os.getenv("CART_SERVICE_URL", "http://cart-service:8003")
INVENTORY_SERVICE_URL = os.getenv("INVENTORY_SERVICE_URL", "http://inventory-service:8005")
PAYMENT_SERVICE_URL = os.getenv("PAYMENT_SERVICE_URL", "http://payment-service:8006")
SERVICE_NAME = os.getenv("SERVICE_NAME", "order-service")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8004"))
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "6.0"))
