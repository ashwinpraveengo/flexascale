import React from 'react';
import { Trash2, ShoppingBag, ArrowRight, ArrowLeft } from 'lucide-react';
import { Cart } from '../types';

interface CartViewProps {
  cart: Cart | null;
  onUpdateQuantity: (itemId: number, quantity: number) => void;
  onRemoveItem: (itemId: number) => void;
  onClearCart: () => void;
  onProceedToCheckout: () => void;
  onContinueShopping: () => void;
}

export const CartView: React.FC<CartViewProps> = ({
  cart,
  onUpdateQuantity,
  onRemoveItem,
  onClearCart,
  onProceedToCheckout,
  onContinueShopping,
}) => {
  const items = cart?.items || [];
  const subtotal = cart?.total_amount || 0;
  const shipping = subtotal > 100 || subtotal === 0 ? 0 : 9.99;
  const tax = Math.round(subtotal * 0.08 * 100) / 100;
  const total = Math.round((subtotal + shipping + tax) * 100) / 100;

  if (items.length === 0) {
    return (
      <div className="max-w-2xl mx-auto py-16 text-center space-y-6">
        <div className="w-20 h-20 mx-auto rounded-3xl bg-slate-100 flex items-center justify-center text-slate-400">
          <ShoppingBag className="w-10 h-10" />
        </div>
        <div className="space-y-2">
          <h2 className="text-2xl font-bold text-slate-900">Your shopping cart is empty</h2>
          <p className="text-sm text-slate-500 max-w-sm mx-auto">
            Discover our high-performance catalog and add products to your cart.
          </p>
        </div>
        <button
          onClick={onContinueShopping}
          className="inline-flex items-center gap-2 px-6 py-3 rounded-xl font-semibold text-sm bg-brand-600 hover:bg-brand-700 text-white shadow-md shadow-brand-500/20 transition-all"
        >
          Explore Catalog <ArrowRight className="w-4 h-4" />
        </button>
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto space-y-8 pb-16">
      <div className="flex items-center justify-between pb-4 border-b border-slate-200">
        <div>
          <h1 className="text-3xl font-extrabold text-slate-900 tracking-tight">Shopping Cart</h1>
          <p className="text-sm text-slate-500 mt-1">
            {cart?.total_items || items.length} {items.length === 1 ? 'item' : 'items'} in your cart
          </p>
        </div>
        <button
          onClick={onClearCart}
          className="text-xs font-semibold text-rose-600 hover:text-rose-800 transition-colors"
        >
          Clear Cart
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Cart Items List */}
        <div className="lg:col-span-2 space-y-4">
          {items.map((item) => (
            <div
              key={item.id}
              className="flex items-center gap-4 p-4 rounded-2xl bg-white border border-slate-200/80 shadow-sm"
            >
              <div className="w-20 h-20 rounded-xl bg-slate-100 overflow-hidden flex-shrink-0">
                <img
                  src={item.image_url || 'https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=300'}
                  alt={item.product_name || 'Product'}
                  className="w-full h-full object-cover"
                />
              </div>

              <div className="flex-1 min-w-0">
                <h3 className="font-semibold text-sm text-slate-900 truncate">
                  {item.product_name || `Product #${item.product_id}`}
                </h3>
                <div className="text-xs text-slate-500 mt-0.5">
                  Unit Price: ${Number(item.unit_price || 0).toFixed(2)}
                </div>

                <div className="flex items-center gap-3 mt-3">
                  <div className="flex items-center border border-slate-200 rounded-lg overflow-hidden bg-slate-50">
                    <button
                      type="button"
                      disabled={item.quantity <= 1}
                      onClick={() => onUpdateQuantity(item.id, item.quantity - 1)}
                      className="px-2.5 py-1 text-xs font-bold text-slate-600 hover:bg-slate-200 disabled:opacity-40"
                    >
                      -
                    </button>
                    <span className="px-3 py-1 text-xs font-bold text-slate-900 bg-white">
                      {item.quantity}
                    </span>
                    <button
                      type="button"
                      onClick={() => onUpdateQuantity(item.id, item.quantity + 1)}
                      className="px-2.5 py-1 text-xs font-bold text-slate-600 hover:bg-slate-200"
                    >
                      +
                    </button>
                  </div>

                  <button
                    onClick={() => onRemoveItem(item.id)}
                    className="p-1.5 text-slate-400 hover:text-rose-600 rounded-lg hover:bg-rose-50 transition-colors"
                    title="Remove item"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>

              <div className="text-right">
                <span className="font-bold text-base text-slate-900">
                  ${Number(item.subtotal || 0).toFixed(2)}
                </span>
              </div>
            </div>
          ))}

          <button
            onClick={onContinueShopping}
            className="inline-flex items-center gap-2 text-xs font-semibold text-slate-600 hover:text-brand-600 pt-2 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" /> Continue Shopping
          </button>
        </div>

        {/* Order Summary Card */}
        <div className="bg-white rounded-3xl p-6 border border-slate-200/80 shadow-sm space-y-6 h-fit">
          <h2 className="text-lg font-bold text-slate-900 border-b border-slate-100 pb-3">
            Order Summary
          </h2>

          <div className="space-y-3 text-sm">
            <div className="flex justify-between text-slate-600">
              <span>Subtotal</span>
              <span className="font-medium text-slate-900">${subtotal.toFixed(2)}</span>
            </div>
            <div className="flex justify-between text-slate-600">
              <span>Shipping</span>
              <span className="font-medium text-slate-900">
                {shipping === 0 ? 'FREE' : `$${shipping.toFixed(2)}`}
              </span>
            </div>
            <div className="flex justify-between text-slate-600">
              <span>Estimated Tax (8%)</span>
              <span className="font-medium text-slate-900">${tax.toFixed(2)}</span>
            </div>

            <div className="pt-3 border-t border-slate-100 flex justify-between items-baseline">
              <span className="text-base font-bold text-slate-900">Total</span>
              <span className="text-2xl font-black text-brand-600">${total.toFixed(2)}</span>
            </div>
          </div>

          <button
            onClick={onProceedToCheckout}
            className="w-full py-4 rounded-xl font-bold text-sm bg-brand-600 hover:bg-brand-700 text-white shadow-lg shadow-brand-500/25 transition-all flex items-center justify-center gap-2 hover:-translate-y-0.5"
          >
            Proceed to Checkout <ArrowRight className="w-4 h-4" />
          </button>

          <p className="text-[11px] text-slate-400 text-center">
            Simulated payment transactions backed by atomic inventory locking.
          </p>
        </div>
      </div>
    </div>
  );
};
