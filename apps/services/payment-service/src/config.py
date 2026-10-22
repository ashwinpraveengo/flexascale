import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/ecommerce")
SERVICE_NAME = os.getenv("SERVICE_NAME", "payment-service")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8006"))
SIMULATE_FAILURE_RATE = float(os.getenv("SIMULATE_FAILURE_RATE", "0.0"))
PAYMENT_DEFAULT_DELAY_MS = int(os.getenv("PAYMENT_DEFAULT_DELAY_MS", "50"))
