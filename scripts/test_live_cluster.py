import os
import sys
import httpx

def main():
    base_url = os.getenv("API_URL", "http://127.0.0.1:18000")
    print(f"Targeting API Gateway at: {base_url}")

    # 1. System status
    print("1. Checking Aggregated System Status...")
    r = httpx.get(f"{base_url}/api/system/status", timeout=10.0)
    print(f"   Status: {r.status_code}, Response: {r.json()}")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"

    # 2. Login
    print("2. Authenticating as demo@flexascale.io...")
    r = httpx.post(f"{base_url}/api/users/login", json={"email": "demo@flexascale.io", "password": "CustomerPass123!"}, timeout=10.0)
    print(f"   Status: {r.status_code}")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    user = r.json().get("user", {})
    user_id = user.get("id", 2)
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    print(f"   Authenticated as User ID: {user_id}")

    # 3. List products
    print("3. Listing Products from Catalog...")
    r = httpx.get(f"{base_url}/api/products", headers=headers, timeout=10.0)
    data = r.json()
    products = data.get("items", [])
    total = data.get("total", len(products))
    print(f"   Status: {r.status_code}, Found {len(products)} products, Total: {total}")
    assert total >= 14, f"Expected at least 14 products, got {total}"
    p1 = products[0]
    p1_name = p1['name']
    p1_price = p1['price']
    print(f"   First product: {p1_name} - ${p1_price}")

    # 4. Add to cart
    print("4. Adding item to Cart...")
    httpx.delete(f"{base_url}/api/cart/{user_id}/items", headers=headers, timeout=10.0)
    r = httpx.post(f"{base_url}/api/cart/{user_id}/items", headers=headers, json={"product_id": p1["id"], "quantity": 2}, timeout=10.0)
    print(f"   Status: {r.status_code}, Cart items: {len(r.json()['items'])}")
    assert r.status_code == 200

    # 5. Get cart
    print("5. Checking Cart contents...")
    r = httpx.get(f"{base_url}/api/cart/{user_id}", headers=headers, timeout=10.0)
    cart = r.json()
    print(f"   Cart Total: ${cart['total_amount']}")
    assert cart["total_amount"] == p1["price"] * 2

    # 6. Checkout
    print("6. Performing Checkout (2-phase distributed saga)...")
    checkout_payload = {
        "user_id": user_id,
        "shipping_address": "123 K8s Microservice Way, Cloud City, CA",
        "card_number": "4242424242424242",
        "payment_method": "credit_card"
    }
    r = httpx.post(f"{base_url}/api/orders/checkout", headers=headers, json=checkout_payload, timeout=15.0)
    print(f"   Status: {r.status_code}, Order: {r.json()}")
    assert r.status_code in (200, 201)
    order = r.json()
    assert order["status"] == "confirmed"
    assert order["payment_id"] is not None

    # 7. Order history
    print("7. Verifying Order in History...")
    r = httpx.get(f"{base_url}/api/orders/user/{user_id}", headers=headers, timeout=10.0)
    orders = r.json()
    print(f"   Found {len(orders)} order(s) in history")
    assert len(orders) >= 1
    assert orders[0]["id"] == order["id"]

    # 8. Verify cart empty
    print("8. Verifying Cart is cleared after confirmed order...")
    r = httpx.get(f"{base_url}/api/cart/{user_id}", headers=headers, timeout=10.0)
    assert len(r.json()["items"]) == 0
    print("   Cart is empty: verified!")

    # 9. Prometheus metrics
    print("9. Scraping Prometheus Metrics on API Gateway...")
    r = httpx.get(f"{base_url}/metrics", timeout=10.0)
    assert r.status_code == 200
    assert "http_requests_total" in r.text
    print("   Prometheus metrics active and scraped: verified!")

    print("\n>>> ALL LIVE KUBERNETES END-TO-END TESTS PASSED SUCCESSFULLY! <<<")

if __name__ == "__main__":
    main()
