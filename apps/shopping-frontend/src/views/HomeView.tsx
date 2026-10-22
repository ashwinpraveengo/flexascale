import React from 'react';
import { Sparkles, ArrowRight, ShieldCheck, Zap, Server, ShoppingCart } from 'lucide-react';
import { Category, Product } from '../types';

interface HomeViewProps {
  categories: Category[];
  featuredProducts: Product[];
  onSelectCategory: (categoryId: number) => void;
  onSelectProduct: (product: Product) => void;
  onAddToCart: (product: Product) => void;
  onNavigate: (view: string) => void;
}

export const HomeView: React.FC<HomeViewProps> = ({
  categories,
  featuredProducts,
  onSelectCategory,
  onSelectProduct,
  onAddToCart,
  onNavigate,
}) => {
  return (
    <div className="space-y-14 pb-16">
      {/* Hero Section */}
      <section className="relative overflow-hidden rounded-3xl bg-gradient-to-br from-slate-900 via-indigo-950 to-slate-900 text-white shadow-2xl p-8 sm:p-12 lg:p-16 border border-slate-800">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_30%_30%,rgba(14,165,233,0.15),transparent_70%)]" />
        <div className="relative max-w-3xl space-y-6">
          <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-brand-500/10 border border-brand-400/30 text-brand-300 text-xs font-semibold uppercase tracking-wider backdrop-blur-md">
            <Sparkles className="w-4 h-4 text-brand-400" />
            Cloud-Native Distributed E-Commerce
          </div>
          <h1 className="text-4xl sm:text-5xl lg:text-6xl font-extrabold tracking-tight leading-tight">
            Next-Gen Shopping <br />
            <span className="bg-gradient-to-r from-brand-400 via-sky-300 to-indigo-300 bg-clip-text text-transparent">
              Engineered for Scale
            </span>
          </h1>
          <p className="text-base sm:text-lg text-slate-300 max-w-2xl font-normal leading-relaxed">
            Experience our 7-microservice resilient architecture featuring real-time inventory locking,
            two-phase checkout sagas, and low-latency asynchronous processing.
          </p>
          <div className="flex flex-wrap gap-4 pt-2">
            <button
              onClick={() => onNavigate('products')}
              className="inline-flex items-center gap-2 px-6 py-3.5 rounded-xl font-semibold text-sm bg-gradient-to-r from-brand-500 to-sky-600 hover:from-brand-600 hover:to-sky-700 text-white shadow-lg shadow-brand-500/25 transition-all hover:-translate-y-0.5"
            >
              Shop All Products
              <ArrowRight className="w-4 h-4" />
            </button>
            <button
              onClick={() => onNavigate('products')}
              className="px-6 py-3.5 rounded-xl font-semibold text-sm bg-slate-800/80 hover:bg-slate-700/80 text-slate-200 border border-slate-700/60 backdrop-blur-md transition-all"
            >
              Browse Categories
            </button>
          </div>
        </div>

        {/* Feature Highlights Grid */}
        <div className="relative mt-12 grid grid-cols-1 sm:grid-cols-3 gap-6 pt-8 border-t border-slate-800/80">
          <div className="flex items-start gap-3.5">
            <div className="p-2.5 rounded-xl bg-brand-500/10 text-brand-400 border border-brand-500/20">
              <Zap className="w-5 h-5" />
            </div>
            <div>
              <h4 className="text-sm font-semibold text-white">Instant Reservations</h4>
              <p className="text-xs text-slate-400 mt-0.5">Atomic inventory locking prevents overselling.</p>
            </div>
          </div>
          <div className="flex items-start gap-3.5">
            <div className="p-2.5 rounded-xl bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
              <ShieldCheck className="w-5 h-5" />
            </div>
            <div>
              <h4 className="text-sm font-semibold text-white">Two-Phase Sagas</h4>
              <p className="text-xs text-slate-400 mt-0.5">Automated rollback compensation on failures.</p>
            </div>
          </div>
          <div className="flex items-start gap-3.5">
            <div className="p-2.5 rounded-xl bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
              <Server className="w-5 h-5" />
            </div>
            <div>
              <h4 className="text-sm font-semibold text-white">Prometheus & Grafana</h4>
              <p className="text-xs text-slate-400 mt-0.5">Deep observability with sub-millisecond metrics.</p>
            </div>
          </div>
        </div>
      </section>

      {/* Categories Showcase */}
      <section className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-bold text-slate-900 tracking-tight">Shop by Category</h2>
            <p className="text-sm text-slate-500">Explore products across our curated departments</p>
          </div>
          <button
            onClick={() => onNavigate('products')}
            className="text-sm font-semibold text-brand-600 hover:text-brand-700 flex items-center gap-1"
          >
            All Products <ArrowRight className="w-4 h-4" />
          </button>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-4">
          {categories.map((cat) => (
            <div
              key={cat.id}
              onClick={() => onSelectCategory(cat.id)}
              className="group cursor-pointer rounded-2xl p-5 bg-white border border-slate-200/80 hover:border-brand-500 shadow-sm hover:shadow-md transition-all hover:-translate-y-1 text-center"
            >
              <div className="w-12 h-12 mx-auto rounded-xl bg-brand-50 text-brand-600 group-hover:bg-brand-600 group-hover:text-white flex items-center justify-center font-bold text-lg transition-colors">
                {cat.name.charAt(0)}
              </div>
              <h3 className="mt-3 font-semibold text-sm text-slate-800 group-hover:text-brand-600 transition-colors">
                {cat.name}
              </h3>
              <p className="text-[11px] text-slate-400 line-clamp-1 mt-0.5">{cat.description}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Featured Products Grid */}
      <section className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-bold text-slate-900 tracking-tight">Featured Products</h2>
            <p className="text-sm text-slate-500">Handpicked items ready for fast delivery</p>
          </div>
          <button
            onClick={() => onNavigate('products')}
            className="text-sm font-semibold text-brand-600 hover:text-brand-700 flex items-center gap-1"
          >
            View More <ArrowRight className="w-4 h-4" />
          </button>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-6">
          {featuredProducts.slice(0, 8).map((product) => (
            <div
              key={product.id}
              className="group flex flex-col bg-white rounded-2xl overflow-hidden border border-slate-200/80 shadow-sm hover:shadow-lg transition-all hover:-translate-y-1"
            >
              {/* Product Image */}
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

              {/* Product Details */}
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
      </section>
    </div>
  );
};
