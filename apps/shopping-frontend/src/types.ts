export interface User {
  id: number;
  email: string;
  full_name: string;
  role: 'customer' | 'admin';
  address?: string;
}

export interface Category {
  id: number;
  name: string;
  slug: string;
  description?: string;
}

export interface Product {
  id: number;
  name: string;
  slug: string;
  description?: string;
  price: number;
  category_id?: number;
  image_url?: string;
  is_active: boolean;
  category?: Category;
}

export interface CartItem {
  id: number;
  product_id: number;
  quantity: number;
  product_name?: string;
  unit_price?: number;
  subtotal?: number;
  image_url?: string;
  in_stock?: boolean;
}

export interface Cart {
  id: number;
  user_id: number;
  items: CartItem[];
  total_items: number;
  total_amount: number;
  updated_at: string;
}

export interface OrderItem {
  id: number;
  product_id: number;
  quantity: number;
  unit_price: number;
  subtotal: number;
}

export interface Order {
  id: number;
  user_id: number;
  total_amount: number;
  status: 'pending' | 'confirmed' | 'failed' | 'cancelled';
  shipping_address?: string;
  payment_id?: string;
  failure_reason?: string;
  created_at: string;
  updated_at: string;
  items: OrderItem[];
}

export interface InventoryItem {
  product_id: number;
  stock_quantity: number;
  reserved_quantity: number;
  available_quantity: number;
  updated_at: string;
}

export interface SystemStatus {
  gateway: string;
  all_services_healthy: boolean;
  services: Record<string, {
    url: string;
    status: 'up' | 'down' | 'degraded';
    status_code?: number;
    error?: string;
  }>;
}

export interface Review {
  id: number;
  product_id: number;
  user_id: number;
  rating: number;
  title: string;
  body: string | null;
  created_at: string;
}

export interface Recommendation {
  id: number;
  name: string;
  price: number;
  image_url: string | null;
  rating: number;
  score: number;
}
