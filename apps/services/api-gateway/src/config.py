import os

SERVICE_NAME = os.getenv("SERVICE_NAME", "api-gateway")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8000"))
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "10.0"))

USER_SERVICE_URL = os.getenv("USER_SERVICE_URL", "http://user-service:8001")
CATALOG_SERVICE_URL = os.getenv("CATALOG_SERVICE_URL", "http://catalog-service:8002")
CART_SERVICE_URL = os.getenv("CART_SERVICE_URL", "http://cart-service:8003")
ORDER_SERVICE_URL = os.getenv("ORDER_SERVICE_URL", "http://order-service:8004")
INVENTORY_SERVICE_URL = os.getenv("INVENTORY_SERVICE_URL", "http://inventory-service:8005")
PAYMENT_SERVICE_URL = os.getenv("PAYMENT_SERVICE_URL", "http://payment-service:8006")
SEARCH_SERVICE_URL = os.getenv("SEARCH_SERVICE_URL", "http://search-service:8007")
RECOMMENDATION_SERVICE_URL = os.getenv("RECOMMENDATION_SERVICE_URL", "http://recommendation-service:8008")
REVIEW_SERVICE_URL = os.getenv("REVIEW_SERVICE_URL", "http://review-service:8009")
PRICING_SERVICE_URL = os.getenv("PRICING_SERVICE_URL", "http://pricing-service:8010")
SHIPPING_SERVICE_URL = os.getenv("SHIPPING_SERVICE_URL", "http://shipping-service:8012")
WISHLIST_SERVICE_URL = os.getenv("WISHLIST_SERVICE_URL", "http://wishlist-service:8015")
