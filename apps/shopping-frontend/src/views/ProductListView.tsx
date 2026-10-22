import React, { useState } from 'react';
import { Search, Filter, ShoppingCart, SlidersHorizontal, ArrowUpDown } from 'lucide-react';
import { Category, Product } from '../types';

interface ProductListViewProps {
  products: Product[];
  categories: Category[];
  selectedCategoryId: number | null;
  onSelectCategory: (id: number | null) => void;
  onSelectProduct: (product: Product) => void;
  onAddToCart: (product: Product) => void;
  sortBy: string;
  onSortChange: (sort: string) => void;
  searchTerm: string;
  onSearchChange: (q: string) => void;
}

export const ProductListView: React.FC<ProductListViewProps> = ({
  products,
  categories,
  selectedCategoryId,
  onSelectCategory,
  onSelectProduct,
  onAddToCart,
  sortBy,
  onSortChange,
  searchTerm,
  onSearchChange,
}) => {
  const [minPrice, setMinPrice] = useState<string>('');
  const [maxPrice, setMaxPrice] = useState<string>('');

  const filtered = products.filter((p) => {
    if (selectedCategoryId && p.category_id !== selectedCategoryId) return false;
    if (searchTerm) {
      const q = searchTerm.toLowerCase();
      const matchName = p.name.toLowerCase().includes(q);
      const matchDesc = p.description?.toLowerCase().includes(q);
      if (!matchName && !matchDesc) return false;
    }
    if (minPrice && p.price < parseFloat(minPrice)) return false;
    if (maxPrice && p.price > parseFloat(maxPrice)) return false;
    return true;
  });

  return (
    <div className="space-y-8 pb-16">
      {/* Top Header & Search Controls */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-6 border-b border-slate-200">
        <div>
          <h1 className="text-3xl font-extrabold text-slate-900 tracking-tight">Product Catalog</h1>
          <p className="text-sm text-slate-500 mt-1">
            Showing {filtered.length} products available for immediate purchase
          </p>
        </div>

        <div className="flex items-center gap-3">
          <div className="relative">
            <ArrowUpDown className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
            <select
              value={sortBy}
              onChange={(e) => onSortChange(e.target.value)}
              className="pl-9 pr-8 py-2 text-sm bg-white border border-slate-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-brand-500 font-medium text-slate-700 cursor-pointer shadow-sm"
            >
              <option value="newest">Sort: Newest</option>
              <option value="price_asc">Price: Low to High</option>
              <option value="price_desc">Price: High to Low</option>
              <option value="name_asc">Name: A to Z</option>
            </select>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-8">
        {/* Sidebar Filters */}
        <div className="space-y-6">
          <div className="bg-white p-5 rounded-2xl border border-slate-200/80 shadow-sm space-y-6">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-bold text-slate-900 uppercase tracking-wider flex items-center gap-2">
                <SlidersHorizontal className="w-4 h-4 text-brand-600" />
                Filters
              </h3>
              {(selectedCategoryId || minPrice || maxPrice || searchTerm) && (
                <button
                  onClick={() => {
                    onSelectCategory(null);
                    setMinPrice('');
                    setMaxPrice('');
                    onSearchChange('');
                  }}
                  className="text-xs text-brand-600 hover:text-brand-800 font-medium"
                >
                  Reset All
                </button>
              )}
            </div>

            {/* Category Filter */}
            <div>
              <h4 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2.5">Category</h4>
              <div className="space-y-1">
                <button
                  onClick={() => onSelectCategory(null)}
                  className={`w-full text-left px-3 py-2 rounded-xl text-xs font-medium transition-colors flex items-center justify-between ${
                    selectedCategoryId === null
                      ? 'bg-brand-50 text-brand-700 font-bold'
                      : 'text-slate-600 hover:bg-slate-50'
                  }`}
                >
                  <span>All Categories</span>
                  <span>{products.length}</span>
                </button>
                {categories.map((c) => {
                  const count = products.filter((p) => p.category_id === c.id).length;
                  return (
                    <button
                      key={c.id}
                      onClick={() => onSelectCategory(c.id)}
                      className={`w-full text-left px-3 py-2 rounded-xl text-xs font-medium transition-colors flex items-center justify-between ${
                        selectedCategoryId === c.id
                          ? 'bg-brand-50 text-brand-700 font-bold'
                          : 'text-slate-600 hover:bg-slate-50'
                      }`}
                    >
                      <span className="truncate">{c.name}</span>
                      <span className="text-slate-400 text-[11px]">{count}</span>
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Price Range Filter */}
            <div>
              <h4 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2.5">Price Range ($)</h4>
              <div className="flex items-center gap-2">
                <input
                  type="number"
                  placeholder="Min"
                  value={minPrice}
                  onChange={(e) => setMinPrice(e.target.value)}
                  className="w-full px-3 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500"
                />
                <span className="text-slate-400 text-xs">-</span>
                <input
                  type="number"
                  placeholder="Max"
                  value={maxPrice}
                  onChange={(e) => setMaxPrice(e.target.value)}
                  className="w-full px-3 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500"
                />
              </div>
            </div>
          </div>
        </div>

        {/* Product Grid */}
        <div className="lg:col-span-3">
          {filtered.length === 0 ? (
            <div className="bg-white rounded-2xl p-12 text-center border border-slate-200/80 shadow-sm space-y-3">
              <Search className="w-12 h-12 text-slate-300 mx-auto" />
              <h3 className="text-lg font-bold text-slate-800">No products match your criteria</h3>
              <p className="text-sm text-slate-500 max-w-sm mx-auto">
                Try clearing your search query or adjusting your category and price filters.
              </p>
              <button
                onClick={() => {
                  onSelectCategory(null);
                  setMinPrice('');
                  setMaxPrice('');
                  onSearchChange('');
                }}
                className="mt-2 px-4 py-2 text-xs font-semibold text-white bg-brand-600 hover:bg-brand-700 rounded-xl transition-colors shadow-sm"
              >
                Clear All Filters
              </button>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
              {filtered.map((product) => (
                <div
                  key={product.id}
                  className="group flex flex-col bg-white rounded-2xl overflow-hidden border border-slate-200/80 shadow-sm hover:shadow-lg transition-all hover:-translate-y-1"
                >
                  {/* Image */}
                  <div
                    className="relative aspect-square w-full bg-slate-100 overflow-hidden cursor-pointer"
                    onClick={() => onSelectProduct(product)}
                  >
                    <img
                      src={product.image_url || 'https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=600'}
                      alt={product.name}
                      className="w-full h-full object-cover object-center group-hover:scale-105 transition-transform duration-300"
                      loading="lazy"
                    />
                    {product.category && (
                      <span className="absolute top-3 left-3 px-2 py-0.5 text-[11px] font-semibold bg-white/90 backdrop-blur-sm text-slate-700 rounded-md shadow-sm">
                        {product.category.name}
                      </span>
                    )}
                  </div>

                  {/* Body */}
                  <div className="p-4 flex-1 flex flex-col justify-between space-y-3">
                    <div onClick={() => onSelectProduct(product)} className="cursor-pointer">
                      <h3 className="font-semibold text-sm text-slate-900 group-hover:text-brand-600 transition-colors line-clamp-1">
                        {product.name}
                      </h3>
                      <p className="text-xs text-slate-500 line-clamp-2 mt-1">
                        {product.description}
                      </p>
                    </div>

                    <div className="flex items-center justify-between pt-2 border-t border-slate-100">
                      <span className="text-lg font-bold text-slate-900">
                        ${Number(product.price).toFixed(2)}
                      </span>
                      <button
                        onClick={() => onAddToCart(product)}
                        className="p-2 rounded-xl bg-brand-50 hover:bg-brand-600 text-brand-600 hover:text-white transition-colors flex items-center justify-center shadow-sm"
                        title="Add to cart"
                      >
                        <ShoppingCart className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
