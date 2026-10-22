#!/usr/bin/env python3
"""
Repeatable database seeding script for the E-Commerce shopping application.
Initializes schemas and populates test users, categories, products, and inventory.
"""

import os
import sys
from pathlib import Path
import bcrypt
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/ecommerce")

def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

CATEGORIES = [
    {"name": "Electronics", "slug": "electronics", "description": "Laptops, audio, gadgets, and tech essentials."},
    {"name": "Clothing", "slug": "clothing", "description": "Comfortable apparel, modern fits, and premium fabrics."},
    {"name": "Home & Kitchen", "slug": "home-kitchen", "description": "Appliances, cookware, and cozy home accessories."},
    {"name": "Books", "slug": "books", "description": "Bestselling fiction, non-fiction, and tech manuals."},
    {"name": "Sports & Fitness", "slug": "sports-fitness", "description": "Equipment, activewear, and workout gear."}
]

PRODUCTS = [
    {
        "name": "CloudPro Wireless Noise-Cancelling Headphones",
        "slug": "cloudpro-wireless-headphones",
        "category_slug": "electronics",
        "description": "High-fidelity spatial audio with 40-hour battery life and adaptive active noise cancellation.",
        "price": 249.99,
        "image_url": "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=600&auto=format&fit=crop&q=80",
        "stock": 150
    },
    {
        "name": "ErgoMechanical Ultra Keyboard",
        "slug": "ergomechanical-ultra-keyboard",
        "category_slug": "electronics",
        "description": "Hot-swappable mechanical switches, RGB backlighting, and split ergonomic aluminum frame.",
        "price": 179.50,
        "image_url": "https://images.unsplash.com/photo-1587829741301-dc798b83add3?w=600&auto=format&fit=crop&q=80",
        "stock": 80
    },
    {
        "name": "RetinaGlide 4K Curved Monitor 34\"",
        "slug": "retinaglide-4k-curved-monitor",
        "category_slug": "electronics",
        "description": "UltraWide 144Hz IPS display with 1ms response time and HDR600 color grading.",
        "price": 649.00,
        "image_url": "https://images.unsplash.com/photo-1527443224154-c4a3942d3acf?w=600&auto=format&fit=crop&q=80",
        "stock": 45
    },
    {
        "name": "AeroBook Pro 16 Laptop",
        "slug": "aerobook-pro-16-laptop",
        "category_slug": "electronics",
        "description": "Octa-core ARM architecture, 32GB unified memory, and 1TB NVMe storage.",
        "price": 1499.00,
        "image_url": "https://images.unsplash.com/photo-1517336714731-489689fd1ca8?w=600&auto=format&fit=crop&q=80",
        "stock": 30
    },
    {
        "name": "Merino Wool Minimalist Hoodie",
        "slug": "merino-wool-minimalist-hoodie",
        "category_slug": "clothing",
        "description": "100% natural thermal regulating merino wool designed for cold mornings and relaxed evenings.",
        "price": 89.00,
        "image_url": "https://images.unsplash.com/photo-1556905055-8f358a7a47b2?w=600&auto=format&fit=crop&q=80",
        "stock": 120
    },
    {
        "name": "All-Weather Technical Parka",
        "slug": "all-weather-technical-parka",
        "category_slug": "clothing",
        "description": "Waterproof GORE-TEX membrane, taped seams, and insulated down baffles.",
        "price": 299.00,
        "image_url": "https://images.unsplash.com/photo-1544441893-675973e31985?w=600&auto=format&fit=crop&q=80",
        "stock": 60
    },
    {
        "name": "Raw Denim Classic Slim Jeans",
        "slug": "raw-denim-classic-slim-jeans",
        "category_slug": "clothing",
        "description": "14oz Japanese selvedge denim, durable copper rivets, and a tailored slim taper.",
        "price": 119.00,
        "image_url": "https://images.unsplash.com/photo-1542272604-780c96856592?w=600&auto=format&fit=crop&q=80",
        "stock": 100
    },
    {
        "name": "Precision Espresso Maker & Grinder",
        "slug": "precision-espresso-maker",
        "category_slug": "home-kitchen",
        "description": "Dual thermoblock PID temperature control with integrated conical burr grinder.",
        "price": 549.99,
        "image_url": "https://images.unsplash.com/photo-1517668808822-9ebb02f2a0e6?w=600&auto=format&fit=crop&q=80",
        "stock": 40
    },
    {
        "name": "Cast Iron Dutch Oven 6-Quart",
        "slug": "cast-iron-dutch-oven",
        "category_slug": "home-kitchen",
        "description": "Enameled interior, superior heat retention, oven safe up to 500°F.",
        "price": 79.95,
        "image_url": "https://images.unsplash.com/photo-1584990347449-3998f483b38c?w=600&auto=format&fit=crop&q=80",
        "stock": 90
    },
    {
        "name": "Japanese Damascus Chef's Knife 8\"",
        "slug": "japanese-damascus-chefs-knife",
        "category_slug": "home-kitchen",
        "description": "67 layers of VG-10 high-carbon steel with pakkawood ergonomic handle.",
        "price": 115.00,
        "image_url": "https://images.unsplash.com/photo-1593618998160-e34014e67546?w=600&auto=format&fit=crop&q=80",
        "stock": 75
    },
    {
        "name": "Designing Data-Intensive Applications",
        "slug": "designing-data-intensive-applications",
        "category_slug": "books",
        "description": "The definitive guide to the architecture of distributed systems, storage, and processing.",
        "price": 45.00,
        "image_url": "https://images.unsplash.com/photo-1544716278-ca5e3f4abd8c?w=600&auto=format&fit=crop&q=80",
        "stock": 200
    },
    {
        "name": "Reinforcement Learning: An Introduction",
        "slug": "reinforcement-learning-intro",
        "category_slug": "books",
        "description": "Sutton and Barto's foundational text on Markov Decision Processes and policy gradients.",
        "price": 65.00,
        "image_url": "https://images.unsplash.com/photo-1532012164546-f432f2e3777f?w=600&auto=format&fit=crop&q=80",
        "stock": 110
    },
    {
        "name": "Adjustable Dumbbell Set (5 - 52.5 lbs)",
        "slug": "adjustable-dumbbell-set",
        "category_slug": "sports-fitness",
        "description": "Rapid dial weight selection replaces 15 sets of dumbbells in a compact footprint.",
        "price": 329.00,
        "image_url": "https://images.unsplash.com/photo-1584735935682-2f2b69dff9d2?w=600&auto=format&fit=crop&q=80",
        "stock": 35
    },
    {
        "name": "TrailRunner Carbon Fiber Trekking Poles",
        "slug": "trailrunner-trekking-poles",
        "category_slug": "sports-fitness",
        "description": "Ultralight foldable poles with moisture-wicking cork grips and tungsten carbide tips.",
        "price": 69.95,
        "image_url": "https://images.unsplash.com/photo-1510312305653-8ed496efae75?w=600&auto=format&fit=crop&q=80",
        "stock": 85
    }
]

TEST_USERS = [
    {
        "email": "admin@flexascale.io",
        "password": "AdminPass123!",
        "full_name": "System Administrator",
        "role": "admin",
        "address": "100 Cloud Native Way, Cluster 1"
    },
    {
        "email": "demo@flexascale.io",
        "password": "CustomerPass123!",
        "full_name": "Alice Customer",
        "role": "customer",
        "address": "42 Microservice Lane, Pod 7"
    },
    {
        "email": "tester@flexascale.io",
        "password": "TesterPass123!",
        "full_name": "Bob LoadTester",
        "role": "customer",
        "address": "99 Benchmark Blvd, Replica 3"
    }
]

def seed_database():
    print(f"Connecting to database: {DATABASE_URL}")
    engine = create_engine(DATABASE_URL)
    is_postgres = "postgresql" in DATABASE_URL

    # Run init.sql if postgres
    init_sql_path = Path(__file__).resolve().parent / "init.sql"
    if is_postgres and init_sql_path.exists():
        print("Executing init.sql DDL...")
        with engine.connect() as conn:
            with open(init_sql_path, "r") as f:
                conn.execute(text(f.read()))
            conn.commit()

    with engine.connect() as conn:
        # 1. Seed Users
        print("Seeding test users...")
        user_table = "users.users" if is_postgres else "users"
        for u in TEST_USERS:
            check_q = text(f"SELECT id FROM {user_table} WHERE email = :email")
            res = conn.execute(check_q, {"email": u["email"]}).first()
            if not res:
                hashed = hash_password(u["password"])
                insert_q = text(
                    f"INSERT INTO {user_table} (email, password_hash, full_name, role, address) "
                    "VALUES (:email, :hash, :name, :role, :address)"
                )
                conn.execute(insert_q, {
                    "email": u["email"],
                    "hash": hashed,
                    "name": u["full_name"],
                    "role": u["role"],
                    "address": u["address"]
                })
                print(f"  + Created user: {u['email']} ({u['role']})")
            else:
                print(f"  = User already exists: {u['email']}")

        # 2. Seed Categories
        print("Seeding categories...")
        cat_table = "catalog.categories" if is_postgres else "categories"
        cat_id_map = {}
        for c in CATEGORIES:
            check_q = text(f"SELECT id FROM {cat_table} WHERE slug = :slug")
            res = conn.execute(check_q, {"slug": c["slug"]}).first()
            if not res:
                insert_q = text(
                    f"INSERT INTO {cat_table} (name, slug, description) "
                    "VALUES (:name, :slug, :description) RETURNING id"
                )
                row = conn.execute(insert_q, c).first()
                cat_id_map[c["slug"]] = row[0]
                print(f"  + Created category: {c['name']}")
            else:
                cat_id_map[c["slug"]] = res[0]

        # 3. Seed Products & Inventory
        print("Seeding products & inventory...")
        prod_table = "catalog.products" if is_postgres else "products"
        inv_table = "inventory.inventory" if is_postgres else "inventory"

        for p in PRODUCTS:
            cat_id = cat_id_map.get(p["category_slug"])
            check_q = text(f"SELECT id FROM {prod_table} WHERE slug = :slug")
            res = conn.execute(check_q, {"slug": p["slug"]}).first()
            prod_id = None
            if not res:
                insert_q = text(
                    f"INSERT INTO {prod_table} (category_id, name, slug, description, price, image_url, is_active) "
                    "VALUES (:category_id, :name, :slug, :description, :price, :image_url, true) RETURNING id"
                )
                row = conn.execute(insert_q, {
                    "category_id": cat_id,
                    "name": p["name"],
                    "slug": p["slug"],
                    "description": p["description"],
                    "price": p["price"],
                    "image_url": p["image_url"]
                }).first()
                prod_id = row[0]
                print(f"  + Created product: {p['name']} (ID: {prod_id}, ${p['price']})")
            else:
                prod_id = res[0]

            # Upsert initial stock
            inv_check = text(f"SELECT product_id FROM {inv_table} WHERE product_id = :pid")
            inv_res = conn.execute(inv_check, {"pid": prod_id}).first()
            if not inv_res:
                inv_insert = text(
                    f"INSERT INTO {inv_table} (product_id, stock_quantity, reserved_quantity) "
                    "VALUES (:pid, :stock, 0)"
                )
                conn.execute(inv_insert, {"pid": prod_id, "stock": p["stock"]})
                print(f"    -> Stock initialized: {p['stock']} units")

        conn.commit()
    print("\nDatabase seeding completed successfully!")

if __name__ == "__main__":
    seed_database()
