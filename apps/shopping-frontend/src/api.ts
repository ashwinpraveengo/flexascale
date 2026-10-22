import {
  User, Category, Product, Cart, Order, InventoryItem, SystemStatus
} from './types';

const API_BASE = '/api';

export class ApiError extends Error {
  status: number;
  data: any;

  constructor(message: string, status: number, data?: any) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

async function request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const token = localStorage.getItem('token');
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> || {}),
  };

  if (token && !headers['Authorization']) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    let errorData = null;
    try {
      errorData = await response.json();
    } catch {
      errorData = await response.text();
    }
    const message = errorData?.detail || errorData?.message || response.statusText || 'API Request failed';
    throw new ApiError(message, response.status, errorData);
  }

  if (response.status === 204) {
    return {} as T;
  }

  return response.json();
}

export const api = {
  auth: {
    login: async (email: string, password: string) => {
      const data = await request<{ access_token: string; user: User }>('/users/login', {
        method: 'POST',
        body: JSON.stringify({ email, password }),
      });
      localStorage.setItem('token', data.access_token);
      localStorage.setItem('user', JSON.stringify(data.user));
      return data;
    },
    register: async (payload: { email: string; password: string; full_name: string; address?: string }) => {
      const data = await request<{ access_token: string; user: User }>('/users/register', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      localStorage.setItem('token', data.access_token);
      localStorage.setItem('user', JSON.stringify(data.user));
      return data;
    },
    logout: () => {
      localStorage.removeItem('token');
      localStorage.removeItem('user');
    },
    me: () => request<User>('/users/me'),
    updateProfile: (payload: { full_name?: string; address?: string; password?: string }) =>
      request<User>('/users/me', {
        method: 'PUT',
        body: JSON.stringify(payload),
      }),
  },

  catalog: {
    listCategories: () => request<Category[]>('/categories'),
    listProducts: (params?: {
      q?: string;
      category_id?: number;
      min_price?: number;
      max_price?: number;
      sort_by?: string;
      page?: number;
      limit?: number;
    }) => {
      const search = new URLSearchParams();
      if (params) {
        Object.entries(params).forEach(([key, val]) => {
          if (val !== undefined && val !== null && val !== '') {
            search.append(key, String(val));
          }
        });
      }
      const queryStr = search.toString();
      return request<{ items: Product[]; total: number; page: number; limit: number }>(
        `/products${queryStr ? `?${queryStr}` : ''}`
      );
    },
    getProduct: (id: number) => request<Product>(`/products/${id}`),
    createProduct: (payload: Partial<Product>) =>
      request<Product>('/products', {
        method: 'POST',
        body: JSON.stringify(payload),
      }),
    updateProduct: (id: number, payload: Partial<Product>) =>
      request<Product>(`/products/${id}`, {
        method: 'PUT',
        body: JSON.stringify(payload),
      }),
    deleteProduct: (id: number) =>
      request<void>(`/products/${id}`, {
        method: 'DELETE',
      }),
  },

  cart: {
    getCart: (userId: number) => request<Cart>(`/cart/${userId}`),
    addItem: (userId: number, productId: number, quantity: number = 1) =>
      request<Cart>(`/cart/${userId}/items`, {
        method: 'POST',
        body: JSON.stringify({ product_id: productId, quantity }),
      }),
    updateItem: (userId: number, itemId: number, quantity: number) =>
      request<Cart>(`/cart/${userId}/items/${itemId}`, {
        method: 'PUT',
        body: JSON.stringify({ quantity }),
      }),
    removeItem: (userId: number, itemId: number) =>
      request<Cart>(`/cart/${userId}/items/${itemId}`, {
        method: 'DELETE',
      }),
    clearCart: (userId: number) =>
      request<void>(`/cart/${userId}/items`, {
        method: 'DELETE',
      }),
  },

  orders: {
    checkout: (payload: {
      user_id: number;
      shipping_address: string;
      card_number?: string;
      payment_method?: string;
      simulate_failure?: boolean;
      idempotency_key?: string;
    }) =>
      request<Order>('/orders/checkout', {
        method: 'POST',
        body: JSON.stringify(payload),
      }),
    getUserOrders: (userId: number) => request<Order[]>(`/orders/user/${userId}`),
    getOrder: (orderId: number) => request<Order>(`/orders/${orderId}`),
    cancelOrder: (orderId: number) =>
      request<Order>(`/orders/${orderId}/cancel`, {
        method: 'POST',
      }),
    listOrders: () => request<Order[]>('/orders'),
  },

  inventory: {
    getInventory: (productId: number) => request<InventoryItem>(`/inventory/${productId}`),
    listInventory: () => request<InventoryItem[]>('/inventory'),
    setStock: (productId: number, stockQuantity: number) =>
      request<InventoryItem>(`/inventory/${productId}`, {
        method: 'PUT',
        body: JSON.stringify({ stock_quantity: stockQuantity }),
      }),
    adjustStock: (productId: number, adjustment: number) =>
      request<InventoryItem>(`/inventory/${productId}/adjust`, {
        method: 'POST',
        body: JSON.stringify({ adjustment }),
      }),
  },

  system: {
    getStatus: () => request<SystemStatus>('/system/status'),
  },
};
