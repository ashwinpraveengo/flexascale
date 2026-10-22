import React, { useState, useEffect } from 'react';
import { ShieldAlert, RefreshCw, Plus, Minus, Search, Check } from 'lucide-react';
import { InventoryItem, Product } from '../types';
import { api } from '../api';

interface AdminInventoryViewProps {
  products: Product[];
}

export const AdminInventoryView: React.FC<AdminInventoryViewProps> = ({ products }) => {
  const [inventoryList, setInventoryList] = useState<InventoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');
  const [updatingProductId, setUpdatingProductId] = useState<number | null>(null);

  const loadInventory = async () => {
    setLoading(true);
    try {
      const data = await api.inventory.listInventory();
      setInventoryList(data);
    } catch (e) {
      console.error('Failed to load inventory:', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadInventory();
  }, []);

  const handleAdjust = async (productId: number, adjustment: number) => {
    setUpdatingProductId(productId);
    try {
      await api.inventory.adjustStock(productId, adjustment);
      await loadInventory();
    } catch (err: any) {
      alert(`Adjustment failed: ${err.message}`);
    } finally {
      setUpdatingProductId(null);
    }
  };

  const handleSetStock = async (productId: number) => {
    const current = inventoryList.find((i) => i.product_id === productId)?.stock_quantity || 0;
    const input = prompt('Enter exact new stock quantity:', String(current));
    if (input === null) return;
    const qty = parseInt(input, 10);
    if (isNaN(qty) || qty < 0) {
      alert('Please enter a valid positive integer.');
      return;
    }

    setUpdatingProductId(productId);
    try {
      await api.inventory.setStock(productId, qty);
      await loadInventory();
    } catch (err: any) {
      alert(`Setting stock failed: ${err.message}`);
    } finally {
      setUpdatingProductId(null);
    }
  };

  const productMap = new Map<number, Product>();
  products.forEach((p) => productMap.set(p.id, p));

  const filtered = inventoryList.filter((inv) => {
    const prod = productMap.get(inv.product_id);
    const name = prod?.name || `Product #${inv.product_id}`;
    return name.toLowerCase().includes(searchTerm.toLowerCase());
  });

  return (
    <div className="max-w-6xl mx-auto space-y-6 pb-16">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-slate-200">
        <div>
          <div className="flex items-center gap-2">
            <span className="px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider bg-amber-100 text-amber-800 rounded-full">
              Admin Portal
            </span>
          </div>
          <h1 className="text-3xl font-extrabold text-slate-900 tracking-tight mt-1">
            Real-Time Inventory Control
          </h1>
          <p className="text-sm text-slate-500">
            Monitor stock levels, active locks, and adjust quantities
          </p>
        </div>

        <button
          onClick={loadInventory}
          className="inline-flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-semibold text-slate-700 bg-white border border-slate-200 shadow-sm hover:bg-slate-50 transition-all"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </button>
      </div>

      <div className="relative max-w-sm">
        <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
        <input
          type="text"
          placeholder="Search by product name..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          className="w-full pl-9 pr-4 py-2 text-xs bg-white border border-slate-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-brand-500 shadow-sm"
        />
      </div>

      <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-50 text-slate-500 uppercase tracking-wider font-semibold border-b border-slate-200/80">
              <tr>
                <th className="py-3 px-4">Product</th>
                <th className="py-3 px-4 text-center">Total Stock</th>
                <th className="py-3 px-4 text-center">Reserved Locks</th>
                <th className="py-3 px-4 text-center">Available Stock</th>
                <th className="py-3 px-4 text-right">Quick Stock Adjustment</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {filtered.map((inv) => {
                const prod = productMap.get(inv.product_id);
                const isUpdating = updatingProductId === inv.product_id;
                return (
                  <tr key={inv.product_id} className="hover:bg-slate-50/60 transition-colors">
                    <td className="py-3.5 px-4">
                      <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-lg bg-slate-100 overflow-hidden flex-shrink-0">
                          <img
                            src={prod?.image_url || 'https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=100'}
                            alt={prod?.name || 'Product'}
                            className="w-full h-full object-cover"
                          />
                        </div>
                        <div>
                          <div className="font-semibold text-slate-900 line-clamp-1">
                            {prod?.name || `Product #${inv.product_id}`}
                          </div>
                          <div className="text-[11px] text-slate-400 font-mono">
                            ID: {inv.product_id}
                          </div>
                        </div>
                      </div>
                    </td>

                    <td className="py-3.5 px-4 text-center font-bold text-slate-800">
                      {inv.stock_quantity}
                    </td>

                    <td className="py-3.5 px-4 text-center">
                      <span className={`px-2 py-0.5 rounded-full text-[11px] font-semibold ${
                        inv.reserved_quantity > 0 ? 'bg-amber-50 text-amber-700' : 'text-slate-400'
                      }`}>
                        {inv.reserved_quantity} locked
                      </span>
                    </td>

                    <td className="py-3.5 px-4 text-center">
                      <span className={`px-2.5 py-0.5 rounded-full text-xs font-bold ${
                        inv.available_quantity > 10
                          ? 'bg-emerald-50 text-emerald-700'
                          : inv.available_quantity > 0
                          ? 'bg-amber-50 text-amber-700'
                          : 'bg-rose-50 text-rose-700'
                      }`}>
                        {inv.available_quantity} available
                      </span>
                    </td>

                    <td className="py-3.5 px-4 text-right">
                      <div className="flex items-center justify-end gap-1.5">
                        <button
                          disabled={isUpdating || inv.stock_quantity <= 0}
                          onClick={() => handleAdjust(inv.product_id, -5)}
                          className="px-2 py-1 text-xs font-bold text-slate-600 bg-slate-100 hover:bg-slate-200 disabled:opacity-40 rounded-lg transition-colors"
                          title="Decrease 5"
                        >
                          -5
                        </button>
                        <button
                          disabled={isUpdating}
                          onClick={() => handleAdjust(inv.product_id, 10)}
                          className="px-2 py-1 text-xs font-bold text-slate-600 bg-slate-100 hover:bg-slate-200 disabled:opacity-40 rounded-lg transition-colors"
                          title="Replenish 10"
                        >
                          +10
                        </button>
                        <button
                          disabled={isUpdating}
                          onClick={() => handleAdjust(inv.product_id, 50)}
                          className="px-2 py-1 text-xs font-bold text-brand-700 bg-brand-50 hover:bg-brand-100 disabled:opacity-40 rounded-lg transition-colors"
                          title="Replenish 50"
                        >
                          +50
                        </button>
                        <button
                          disabled={isUpdating}
                          onClick={() => handleSetStock(inv.product_id)}
                          className="px-2.5 py-1 text-xs font-semibold text-slate-500 hover:text-slate-900 border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors"
                        >
                          Set Exact
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
