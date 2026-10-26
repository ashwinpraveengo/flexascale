import React, { useState, useEffect } from 'react';
import { User, Category, Product, Cart, Order, SystemStatus } from './types';
import { api } from './api';
import { Navbar } from './components/Navbar';
import { HomeView } from './views/HomeView';
import { ProductListView } from './views/ProductListView';
import { ProductDetailView } from './views/ProductDetailView';
import { CartView } from './views/CartView';
import { CheckoutView } from './views/CheckoutView';
import { OrderConfirmationView } from './views/OrderConfirmationView';
import { OrdersView } from './views/OrdersView';
import { ProfileView } from './views/ProfileView';
import { AdminProductsView } from './views/AdminProductsView';
import { AdminInventoryView } from './views/AdminInventoryView';
import { AuthViews } from './views/AuthViews';

export const App: React.FC = () => {
  const [user, setUser] = useState<User | null>(() => {
    const saved = localStorage.getItem('user');
    return saved ? JSON.parse(saved) : null;
  });

  const [currentView, setCurrentView] = useState<string>('home');
  const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
  const [confirmedOrder, setConfirmedOrder] = useState<Order | null>(null);

  const [categories, setCategories] = useState<Category[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [cart, setCart] = useState<Cart | null>(null);
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);

  // Filters & Search
  const [selectedCategoryId, setSelectedCategoryId] = useState<number | null>(null);
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [sortBy, setSortBy] = useState<string>('newest');

  // Load initial data
  const loadCatalogData = async () => {
    try {
      const [cats, prodsResp] = await Promise.all([
        api.catalog.listCategories().catch(() => []),
        api.catalog.listProducts({ limit: 100 }).catch(() => ({ items: [] })),
      ]);
      setCategories(cats);
      setProducts(prodsResp.items || []);
    } catch (err) {
      console.error('Error fetching catalog data:', err);
    }
  };

  const loadCartData = async (userId: number) => {
    try {
      const cartData = await api.cart.getCart(userId);
      setCart(cartData);
    } catch (err) {
      console.error('Error fetching cart:', err);
    }
  };

  const pollSystemStatus = async () => {
    try {
      const status = await api.system.getStatus();
      setSystemStatus(status);
    } catch (err) {
      console.warn('System status check failed:', err);
    }
  };

  useEffect(() => {
    loadCatalogData();
    pollSystemStatus();
    const interval = setInterval(pollSystemStatus, 15000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (user?.id) {
      loadCartData(user.id);
    } else {
      setCart(null);
    }
  }, [user?.id]);

  // Handlers
  const handleAddToCart = async (product: Product, quantity: number = 1) => {
    if (!user) {
      setCurrentView('login');
      return;
    }
    try {
      const updated = await api.cart.addItem(user.id, product.id, quantity);
      setCart(updated);
    } catch (err: any) {
      alert(`Could not add to cart: ${err.message}`);
    }
  };

  const handleUpdateCartQuantity = async (itemId: number, quantity: number) => {
    if (!user) return;
    try {
      const updated = await api.cart.updateItem(user.id, itemId, quantity);
      setCart(updated);
    } catch (err: any) {
      alert(`Could not update cart: ${err.message}`);
    }
  };

  const handleRemoveCartItem = async (itemId: number) => {
    if (!user) return;
    try {
      const updated = await api.cart.removeItem(user.id, itemId);
      setCart(updated);
    } catch (err: any) {
      alert(`Could not remove cart item: ${err.message}`);
    }
  };

  const handleClearCart = async () => {
    if (!user) return;
    try {
      await api.cart.clearCart(user.id);
      loadCartData(user.id);
    } catch (err: any) {
      alert(`Could not clear cart: ${err.message}`);
    }
  };

  const handleLogout = () => {
    api.auth.logout();
    setUser(null);
    setCart(null);
    setCurrentView('home');
  };

  const handleSearchSubmit = () => {
    setCurrentView('products');
  };

  const cartCount = cart?.total_items || 0;

  return (
    <div className="min-h-screen flex flex-col bg-slate-50 text-slate-900 font-sans">
      <Navbar
        user={user}
        cartCount={cartCount}
        onNavigate={(view) => {
          setCurrentView(view);
          window.scrollTo({ top: 0, behavior: 'smooth' });
        }}
        onLogout={handleLogout}
        systemStatus={systemStatus}
        searchTerm={searchTerm}
        onSearchChange={setSearchTerm}
        onSearchSubmit={handleSearchSubmit}
      />

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 pt-8">
        {currentView === 'home' && (
          <HomeView
            categories={categories}
            featuredProducts={products}
            onSelectCategory={(catId) => {
              setSelectedCategoryId(catId);
              setCurrentView('products');
            }}
            onSelectProduct={(p) => {
              setSelectedProduct(p);
              setCurrentView('product-detail');
            }}
            onAddToCart={handleAddToCart}
            onNavigate={(v) => setCurrentView(v)}
          />
        )}

        {currentView === 'products' && (
          <ProductListView
            products={products}
            categories={categories}
            selectedCategoryId={selectedCategoryId}
            onSelectCategory={setSelectedCategoryId}
            onSelectProduct={(p) => {
              setSelectedProduct(p);
              setCurrentView('product-detail');
            }}
            onAddToCart={handleAddToCart}
            sortBy={sortBy}
            onSortChange={setSortBy}
            searchTerm={searchTerm}
            onSearchChange={setSearchTerm}
          />
        )}

        {currentView === 'product-detail' && selectedProduct && (
          <ProductDetailView
            product={selectedProduct}
            onAddToCart={handleAddToCart}
            onBack={() => setCurrentView('products')}
            onSelectProduct={(id) => {
              api.catalog.getProduct(id).then((p) => {
                setSelectedProduct(p);
                window.scrollTo(0, 0);
              }).catch(() => undefined);
            }}
          />
        )}

        {currentView === 'cart' && (
          <CartView
            cart={cart}
            onUpdateQuantity={handleUpdateCartQuantity}
            onRemoveItem={handleRemoveCartItem}
            onClearCart={handleClearCart}
            onProceedToCheckout={() => {
              if (!user) {
                setCurrentView('login');
              } else {
                setCurrentView('checkout');
              }
            }}
            onContinueShopping={() => setCurrentView('products')}
          />
        )}

        {currentView === 'checkout' && user && (
          <CheckoutView
            user={user}
            cart={cart}
            onSuccess={(order) => {
              setConfirmedOrder(order);
              setCart(null);
              setCurrentView('order-confirmation');
            }}
            onBack={() => setCurrentView('cart')}
          />
        )}

        {currentView === 'order-confirmation' && confirmedOrder && (
          <OrderConfirmationView
            order={confirmedOrder}
            onViewOrders={() => setCurrentView('orders')}
            onContinueShopping={() => setCurrentView('products')}
          />
        )}

        {currentView === 'orders' && user && (
          <OrdersView
            user={user}
            onExploreProducts={() => setCurrentView('products')}
          />
        )}

        {currentView === 'profile' && user && (
          <ProfileView
            user={user}
            onUpdateUser={(u) => {
              setUser(u);
              localStorage.setItem('user', JSON.stringify(u));
            }}
          />
        )}

        {currentView === 'admin-products' && user?.role === 'admin' && (
          <AdminProductsView
            products={products}
            categories={categories}
            onRefresh={loadCatalogData}
          />
        )}

        {currentView === 'admin-inventory' && user?.role === 'admin' && (
          <AdminInventoryView products={products} />
        )}

        {(currentView === 'login' || currentView === 'register') && (
          <AuthViews
            mode={currentView}
            onSuccess={(u) => {
              setUser(u);
              setCurrentView('home');
            }}
            onSwitchMode={(m) => setCurrentView(m)}
          />
        )}
      </main>

      {/* Footer */}
      <footer className="bg-white border-t border-slate-200 mt-auto py-8">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col sm:flex-row items-center justify-between gap-4 text-xs text-slate-500">
          <div>
            <span className="font-bold text-slate-800">FlexaScale E-Commerce Store</span> • Cloud-Native Microservices Platform
          </div>
          <div className="flex items-center gap-4">
            <span>FastAPI Backends</span>
            <span>•</span>
            <span>PostgreSQL Persistence</span>
            <span>•</span>
            <span>Prometheus Metrics</span>
            <span>•</span>
            <span>Kubernetes & Helm</span>
          </div>
        </div>
      </footer>
    </div>
  );
};
export default App;
