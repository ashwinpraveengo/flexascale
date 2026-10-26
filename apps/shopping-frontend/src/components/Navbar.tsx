import React, { useState } from 'react';
import {
  ShoppingBag, Search, User as UserIcon, LogOut,
  Package, ShieldAlert, Cpu, CheckCircle2, AlertTriangle, Layers
} from 'lucide-react';
import { User, SystemStatus } from '../types';

interface NavbarProps {
  user: User | null;
  cartCount: number;
  onNavigate: (view: string, data?: any) => void;
  onLogout: () => void;
  systemStatus: SystemStatus | null;
  searchTerm: string;
  onSearchChange: (q: string) => void;
  onSearchSubmit: () => void;
}

export const Navbar: React.FC<NavbarProps> = ({
  user,
  cartCount,
  onNavigate,
  onLogout,
  systemStatus,
  searchTerm,
  onSearchChange,
  onSearchSubmit
}) => {
  const [showStatusModal, setShowStatusModal] = useState(false);
  const [showUserMenu, setShowUserMenu] = useState(false);

  const allHealthy = systemStatus?.all_services_healthy ?? true;

  return (
    <>
      <header className="sticky top-0 z-40 glass-nav border-b border-slate-200/80 shadow-sm transition-all">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16 gap-4">
            {/* Brand Logo */}
            <div
              className="flex items-center gap-2.5 cursor-pointer select-none group"
              onClick={() => onNavigate('home')}
            >
              <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-brand-600 to-indigo-600 flex items-center justify-center text-white shadow-md shadow-brand-500/20 group-hover:scale-105 transition-transform">
                <Layers className="w-5 h-5" />
              </div>
              <div>
                <span className="text-xl font-bold bg-gradient-to-r from-slate-900 via-brand-800 to-indigo-900 bg-clip-text text-transparent">
                  Flexa<span className="text-brand-600">Store</span>
                </span>
                <span className="hidden sm:inline-block ml-2 text-[10px] font-semibold tracking-wider uppercase px-1.5 py-0.5 rounded bg-brand-50 text-brand-700 border border-brand-200">
                  Microservices
                </span>
              </div>
            </div>

            {/* Search Bar */}
            <form
              onSubmit={(e) => { e.preventDefault(); onSearchSubmit(); }}
              className="flex-1 max-w-lg hidden md:block"
            >
              <div className="relative">
                <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                <input
                  type="text"
                  placeholder="Search products, brands, essentials..."
                  value={searchTerm}
                  onChange={(e) => onSearchChange(e.target.value)}
                  className="w-full pl-10 pr-4 py-2 text-sm bg-slate-100 hover:bg-slate-50 focus:bg-white border border-slate-200 rounded-full focus:outline-none focus:ring-2 focus:ring-brand-500 focus:border-transparent transition-all shadow-inner"
                />
              </div>
            </form>

            {/* Right Action Icons */}
            <div className="flex items-center gap-3">
              {/* System Cluster Diagnostics Button */}
              <button
                type="button"
                onClick={() => setShowStatusModal(true)}
                className={`hidden lg:flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-full border transition-colors ${
                  allHealthy
                    ? 'bg-emerald-50 text-emerald-700 border-emerald-200 hover:bg-emerald-100'
                    : 'bg-amber-50 text-amber-700 border-amber-200 hover:bg-amber-100'
                }`}
                title="View microservice cluster status"
              >
                <Cpu className="w-3.5 h-3.5" />
                <span>Cluster Health</span>
                <span className={`w-2 h-2 rounded-full ${allHealthy ? 'bg-emerald-500' : 'bg-amber-500'} animate-pulse`} />
              </button>

              {/* Browse Catalog */}
              <button
                onClick={() => onNavigate('products')}
                className="text-sm font-medium text-slate-700 hover:text-brand-600 px-2 py-1 rounded-md transition-colors"
              >
                Catalog
              </button>

              {/* Shopping Cart Button */}
              <button
                onClick={() => onNavigate('cart')}
                className="relative p-2 text-slate-700 hover:text-brand-600 rounded-full hover:bg-slate-100 transition-colors"
                aria-label="Shopping Cart"
              >
                <ShoppingBag className="w-5 h-5" />
                {cartCount > 0 && (
                  <span className="absolute -top-1 -right-1 bg-brand-600 text-white text-[11px] font-bold w-5 h-5 rounded-full flex items-center justify-center shadow-sm">
                    {cartCount > 99 ? '99+' : cartCount}
                  </span>
                )}
              </button>

              {/* User Account / Dropdown */}
              {user ? (
                <div className="relative">
                  <button
                    onClick={() => setShowUserMenu(!showUserMenu)}
                    className="flex items-center gap-2 p-1.5 rounded-full hover:bg-slate-100 transition-colors"
                  >
                    <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-brand-500 to-indigo-600 text-white flex items-center justify-center font-bold text-xs uppercase shadow-sm">
                      {user.full_name?.charAt(0) || user.email.charAt(0)}
                    </div>
                  </button>

                  {showUserMenu && (
                    <div
                      className="absolute right-0 mt-2 w-56 bg-white rounded-xl shadow-xl border border-slate-100 py-1.5 z-50 animate-in fade-in slide-in-from-top-2 duration-150"
                      onClick={() => setShowUserMenu(false)}
                    >
                      <div className="px-4 py-2 border-b border-slate-100">
                        <p className="text-sm font-semibold text-slate-900 truncate">{user.full_name}</p>
                        <p className="text-xs text-slate-500 truncate">{user.email}</p>
                        {user.role === 'admin' && (
                          <span className="inline-block mt-1 text-[10px] font-semibold uppercase px-2 py-0.5 bg-purple-100 text-purple-700 rounded-full">
                            Admin
                          </span>
                        )}
                      </div>

                      <button
                        onClick={() => onNavigate('profile')}
                        className="w-full text-left px-4 py-2 text-sm text-slate-700 hover:bg-slate-50 flex items-center gap-2"
                      >
                        <UserIcon className="w-4 h-4 text-slate-400" />
                        My Profile
                      </button>

                      <button
                        onClick={() => onNavigate('orders')}
                        className="w-full text-left px-4 py-2 text-sm text-slate-700 hover:bg-slate-50 flex items-center gap-2"
                      >
                        <Package className="w-4 h-4 text-slate-400" />
                        Order History
                      </button>

                      {user.role === 'admin' && (
                        <>
                          <div className="my-1 border-t border-slate-100" />
                          <div className="px-4 py-1 text-[10px] font-bold text-slate-400 uppercase tracking-wider">
                            Management
                          </div>
                          <button
                            onClick={() => onNavigate('admin-products')}
                            className="w-full text-left px-4 py-2 text-sm text-slate-700 hover:bg-slate-50 flex items-center gap-2"
                          >
                            <Layers className="w-4 h-4 text-purple-500" />
                            Manage Products
                          </button>
                          <button
                            onClick={() => onNavigate('admin-inventory')}
                            className="w-full text-left px-4 py-2 text-sm text-slate-700 hover:bg-slate-50 flex items-center gap-2"
                          >
                            <ShieldAlert className="w-4 h-4 text-amber-500" />
                            Manage Inventory
                          </button>
                        </>
                      )}

                      <div className="my-1 border-t border-slate-100" />
                      <button
                        onClick={onLogout}
                        className="w-full text-left px-4 py-2 text-sm text-rose-600 hover:bg-rose-50 flex items-center gap-2"
                      >
                        <LogOut className="w-4 h-4 text-rose-500" />
                        Sign Out
                      </button>
                    </div>
                  )}
                </div>
              ) : (
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => onNavigate('login')}
                    className="text-sm font-medium text-slate-700 hover:text-brand-600 px-3 py-1.5 rounded-lg transition-colors"
                  >
                    Sign In
                  </button>
                  <button
                    onClick={() => onNavigate('register')}
                    className="text-sm font-medium text-white bg-brand-600 hover:bg-brand-700 px-3.5 py-1.5 rounded-lg shadow-sm hover:shadow transition-all"
                  >
                    Register
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      </header>

      {/* Cluster Diagnostics Modal */}
      {showStatusModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm animate-in fade-in">
          <div className="bg-white rounded-2xl shadow-2xl max-w-lg w-full p-6 border border-slate-100">
            <div className="flex items-center justify-between pb-4 border-b border-slate-100">
              <div className="flex items-center gap-2.5">
                <Cpu className="w-6 h-6 text-brand-600" />
                <h3 className="text-lg font-bold text-slate-900">Microservice Cluster Topology</h3>
              </div>
              <button
                onClick={() => setShowStatusModal(false)}
                className="text-slate-400 hover:text-slate-600 rounded-lg p-1"
              >
                ✕
              </button>
            </div>

            <div className="py-4 space-y-3">
              <p className="text-xs text-slate-500">
                Live responsiveness of the backend microservices communicating through the API Gateway:
              </p>

              <div className="space-y-2">
                {systemStatus?.services ? (
                  Object.entries(systemStatus.services).map(([svc, info]) => (
                    <div
                      key={svc}
                      className="flex items-center justify-between p-2.5 rounded-lg bg-slate-50 border border-slate-100"
                    >
                      <div>
                        <span className="text-sm font-semibold text-slate-800 capitalize">
                          {svc.replace('-', ' ')} Service
                        </span>
                        <div className="text-[11px] text-slate-400 font-mono">{info.url}</div>
                      </div>
                      <div className="flex items-center gap-1.5">
                        {info.status === 'up' ? (
                          <>
                            <CheckCircle2 className="w-4 h-4 text-emerald-500" />
                            <span className="text-xs font-semibold text-emerald-600 uppercase">Healthy</span>
                          </>
                        ) : (
                          <>
                            <AlertTriangle className="w-4 h-4 text-amber-500" />
                            <span className="text-xs font-semibold text-amber-600 uppercase">Degraded</span>
                          </>
                        )}
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="text-sm text-slate-400 text-center py-4">Polling gateway status...</div>
                )}
              </div>
            </div>

            <div className="pt-3 border-t border-slate-100 flex justify-end">
              <button
                onClick={() => setShowStatusModal(false)}
                className="px-4 py-2 text-sm font-medium text-slate-600 hover:text-slate-900 bg-slate-100 hover:bg-slate-200 rounded-lg transition-colors"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
};
