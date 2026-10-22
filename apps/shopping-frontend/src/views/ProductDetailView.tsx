import React, { useState, useEffect } from 'react';
import { ArrowLeft, ShoppingBag, Check, ShieldCheck, Truck, RefreshCw, AlertCircle } from 'lucide-react';
import { Product, InventoryItem } from '../types';
import { api } from '../api';

interface ProductDetailViewProps {
  product: Product;
  onAddToCart: (product: Product, quantity: number) => void;
  onBack: () => void;
}

export const ProductDetailView: React.FC<ProductDetailViewProps> = ({
  product,
  onAddToCart,
  onBack,
}) => {
  const [quantity, setQuantity] = useState(1);
  const [inventory, setInventory] = useState<InventoryItem | null>(null);
  const [loadingInventory, setLoadingInventory] = useState(true);
  const [added, setAdded] = useState(false);

  useEffect(() => {
    let isMounted = true;
    setLoadingInventory(true);
    api.inventory.getInventory(product.id)
      .then((data) => {
        if (isMounted) {
          setInventory(data);
          setLoadingInventory(false);
        }
      })
      .catch((err) => {
        console.error('Failed to load inventory for product:', err);
        if (isMounted) setLoadingInventory(false);
      });
    return () => { isMounted = false; };
  }, [product.id]);

  const availableStock = inventory ? inventory.available_quantity : 50;
  const isOutOfStock = !loadingInventory && inventory !== null && availableStock <= 0;

  const handleAdd = () => {
    onAddToCart(product, quantity);
    setAdded(true);
    setTimeout(() => setAdded(false), 2000);
  };

  return (
    <div className="max-w-5xl mx-auto space-y-8 pb-16">
      {/* Back to Products */}
      <button
        onClick={onBack}
        className="inline-flex items-center gap-2 text-sm font-semibold text-slate-600 hover:text-brand-600 transition-colors"
      >
        <ArrowLeft className="w-4 h-4" />
        Back to Products
      </button>

      <div className="bg-white rounded-3xl border border-slate-200/80 shadow-sm overflow-hidden p-6 sm:p-10 grid grid-cols-1 md:grid-cols-2 gap-10">
        {/* Product Image Gallery */}
        <div className="relative aspect-square rounded-2xl overflow-hidden bg-slate-100 border border-slate-100 shadow-inner">
          <img
            src={product.image_url || 'https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=600'}
            alt={product.name}
            className="w-full h-full object-cover object-center"
          />
          {product.category && (
            <span className="absolute top-4 left-4 px-3 py-1 text-xs font-semibold bg-white/95 backdrop-blur-md text-brand-700 rounded-full shadow-sm">
              {product.category.name}
            </span>
          )}
        </div>

        {/* Product Info & Purchase Form */}
        <div className="flex flex-col justify-between space-y-6">
          <div className="space-y-4">
            <h1 className="text-2xl sm:text-3xl font-extrabold text-slate-900 tracking-tight">
              {product.name}
            </h1>

            <div className="flex items-center gap-4">
              <span className="text-3xl font-black text-slate-900">
                ${Number(product.price).toFixed(2)}
              </span>

              {/* Stock Status Pill */}
              {loadingInventory ? (
                <span className="text-xs text-slate-400 flex items-center gap-1">
                  <RefreshCw className="w-3.5 h-3.5 animate-spin" /> Checking stock...
                </span>
              ) : isOutOfStock ? (
                <span className="px-2.5 py-1 text-xs font-bold bg-rose-50 text-rose-700 border border-rose-200 rounded-full flex items-center gap-1">
                  <AlertCircle className="w-3.5 h-3.5" /> Out of Stock
                </span>
              ) : (
                <span className="px-2.5 py-1 text-xs font-bold bg-emerald-50 text-emerald-700 border border-emerald-200 rounded-full flex items-center gap-1">
                  <Check className="w-3.5 h-3.5" /> {availableStock} in stock
                </span>
              )}
            </div>

            <p className="text-sm text-slate-600 leading-relaxed pt-2">
              {product.description}
            </p>
          </div>

          {/* Quantity and Actions */}
          <div className="space-y-4 pt-6 border-t border-slate-100">
            <div className="flex items-center gap-4">
              <span className="text-xs font-bold uppercase tracking-wider text-slate-500">
                Quantity
              </span>
              <div className="flex items-center border border-slate-200 rounded-xl overflow-hidden bg-slate-50">
                <button
                  type="button"
                  disabled={quantity <= 1 || isOutOfStock}
                  onClick={() => setQuantity((q) => Math.max(1, q - 1))}
                  className="px-3.5 py-1.5 text-sm font-bold text-slate-600 hover:bg-slate-200 disabled:opacity-40 transition-colors"
                >
                  -
                </button>
                <span className="px-4 py-1.5 text-sm font-semibold text-slate-900 bg-white">
                  {quantity}
                </span>
                <button
                  type="button"
                  disabled={quantity >= availableStock || isOutOfStock}
                  onClick={() => setQuantity((q) => q + 1)}
                  className="px-3.5 py-1.5 text-sm font-bold text-slate-600 hover:bg-slate-200 disabled:opacity-40 transition-colors"
                >
                  +
                </button>
              </div>
            </div>

            <div className="flex items-center gap-3">
              <button
                type="button"
                disabled={isOutOfStock}
                onClick={handleAdd}
                className={`flex-1 py-3.5 px-6 rounded-xl font-bold text-sm shadow-md transition-all flex items-center justify-center gap-2 ${
                  added
                    ? 'bg-emerald-600 text-white'
                    : isOutOfStock
                    ? 'bg-slate-200 text-slate-400 cursor-not-allowed'
                    : 'bg-brand-600 hover:bg-brand-700 text-white shadow-brand-500/20 hover:-translate-y-0.5'
                }`}
              >
                {added ? (
                  <>
                    <Check className="w-4 h-4" /> Added to Cart!
                  </>
                ) : (
                  <>
                    <ShoppingBag className="w-4 h-4" /> Add to Shopping Cart
                  </>
                )}
              </button>
            </div>

            {/* Microservice Highlights */}
            <div className="grid grid-cols-2 gap-3 pt-4 text-xs text-slate-500">
              <div className="flex items-center gap-2">
                <Truck className="w-4 h-4 text-brand-600" />
                <span>Simulated Fast Shipping</span>
              </div>
              <div className="flex items-center gap-2">
                <ShieldCheck className="w-4 h-4 text-emerald-600" />
                <span>Atomic Inventory Lock</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
