-- E-Commerce Application Database Initialization
-- Creates schemas and tables for all microservices

-- 1. Users Schema
CREATE SCHEMA IF NOT EXISTS users;

CREATE TABLE IF NOT EXISTS users.users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL DEFAULT 'customer',
    address TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users.users(email);

-- 2. Catalog Schema
CREATE SCHEMA IF NOT EXISTS catalog;

CREATE TABLE IF NOT EXISTS catalog.categories (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    slug VARCHAR(100) UNIQUE NOT NULL,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS catalog.products (
    id SERIAL PRIMARY KEY,
    category_id INTEGER REFERENCES catalog.categories(id) ON DELETE SET NULL,
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(255) UNIQUE NOT NULL,
    description TEXT,
    price NUMERIC(10, 2) NOT NULL CHECK (price >= 0),
    image_url TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_products_category ON catalog.products(category_id);
CREATE INDEX IF NOT EXISTS idx_products_slug ON catalog.products(slug);
CREATE INDEX IF NOT EXISTS idx_products_price ON catalog.products(price);

-- 3. Inventory Schema
CREATE SCHEMA IF NOT EXISTS inventory;

CREATE TABLE IF NOT EXISTS inventory.inventory (
    product_id INTEGER PRIMARY KEY,
    stock_quantity INTEGER NOT NULL DEFAULT 0 CHECK (stock_quantity >= 0),
    reserved_quantity INTEGER NOT NULL DEFAULT 0 CHECK (reserved_quantity >= 0),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS inventory.reservations (
    id VARCHAR(64) PRIMARY KEY,
    order_id INTEGER,
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    status VARCHAR(32) NOT NULL DEFAULT 'reserved', -- 'reserved', 'confirmed', 'released'
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_reservations_order ON inventory.reservations(order_id);
CREATE INDEX IF NOT EXISTS idx_reservations_status ON inventory.reservations(status);

-- 4. Shopping Cart Schema
CREATE SCHEMA IF NOT EXISTS cart;

CREATE TABLE IF NOT EXISTS cart.carts (
    id SERIAL PRIMARY KEY,
    user_id INTEGER UNIQUE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cart.cart_items (
    id SERIAL PRIMARY KEY,
    cart_id INTEGER NOT NULL REFERENCES cart.carts(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (cart_id, product_id)
);

CREATE INDEX IF NOT EXISTS idx_cart_items_cart ON cart.cart_items(cart_id);

-- 5. Order Management Schema
CREATE SCHEMA IF NOT EXISTS orders;

CREATE TABLE IF NOT EXISTS orders.orders (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    total_amount NUMERIC(10, 2) NOT NULL CHECK (total_amount >= 0),
    status VARCHAR(32) NOT NULL DEFAULT 'pending', -- 'pending', 'confirmed', 'failed', 'cancelled'
    idempotency_key VARCHAR(128) UNIQUE,
    shipping_address TEXT,
    payment_id VARCHAR(64),
    failure_reason TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS orders.order_items (
    id SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders.orders(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price NUMERIC(10, 2) NOT NULL CHECK (unit_price >= 0)
);

CREATE INDEX IF NOT EXISTS idx_orders_user ON orders.orders(user_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders.orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_idempotency ON orders.orders(idempotency_key);

-- 6. Payment Schema
CREATE SCHEMA IF NOT EXISTS payments;

CREATE TABLE IF NOT EXISTS payments.payments (
    id SERIAL PRIMARY KEY,
    transaction_id VARCHAR(64) UNIQUE NOT NULL,
    order_id INTEGER NOT NULL,
    amount NUMERIC(10, 2) NOT NULL CHECK (amount >= 0),
    status VARCHAR(32) NOT NULL, -- 'success', 'failed', 'pending'
    payment_method VARCHAR(64) NOT NULL DEFAULT 'simulated_card',
    idempotency_key VARCHAR(128) UNIQUE,
    failure_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_payments_order ON payments.payments(order_id);
CREATE INDEX IF NOT EXISTS idx_payments_transaction ON payments.payments(transaction_id);
