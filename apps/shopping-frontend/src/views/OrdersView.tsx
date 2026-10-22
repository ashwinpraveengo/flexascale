import React, { useState, useEffect } from 'react';
import { Package, Clock, CheckCircle2, AlertCircle, XCircle, ChevronDown, ChevronUp, RefreshCw } from 'lucide-react';
import { Order, User } from '../types';
import { api } from '../api';

interface OrdersViewProps {
  user: User;
  onExploreProducts: () => void;
}

export const OrdersView: React.FC<OrdersViewProps> = ({ user, onExploreProducts }) => {
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedOrderId, setExpandedOrderId] = useState<number | null>(null);

  const loadOrders = async () => {
    setLoading(true);
    try {
      const data = await api.orders.getUserOrders(user.id);
      setOrders(data);
    } catch (e) {
      console.error('Failed to load user orders:', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadOrders();
  }, [user.id]);

  const handleCancel = async (orderId: number) => {
    if (!confirm('Are you sure you want to cancel this order?')) return;
    try {
      await api.orders.cancelOrder(orderId);
      loadOrders();
    } catch (e: any) {
      alert(`Could not cancel order: ${e.message}`);
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'confirmed':
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
            <CheckCircle2 className="w-3.5 h-3.5" /> Confirmed
          </span>
        );
      case 'pending':
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-50 text-amber-700 border border-amber-200">
            <Clock className="w-3.5 h-3.5" /> Pending
          </span>
        );
      case 'failed':
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-rose-50 text-rose-700 border border-rose-200">
            <AlertCircle className="w-3.5 h-3.5" /> Failed
          </span>
        );
      case 'cancelled':
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-slate-100 text-slate-600 border border-slate-200">
            <XCircle className="w-3.5 h-3.5" /> Cancelled
          </span>
        );
      default:
        return null;
    }
  };

  return (
    <div className="max-w-4xl mx-auto space-y-6 pb-16">
      <div className="flex items-center justify-between pb-4 border-b border-slate-200">
        <div>
          <h1 className="text-3xl font-extrabold text-slate-900 tracking-tight">Order History</h1>
          <p className="text-sm text-slate-500 mt-1">
            Track past and current microservice order transactions
          </p>
        </div>
        <button
          onClick={loadOrders}
          className="p-2 text-slate-500 hover:text-slate-800 rounded-lg hover:bg-slate-100 transition-colors"
          title="Refresh orders"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {loading ? (
        <div className="py-16 text-center text-sm text-slate-400">
          <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2 text-brand-600" />
          Loading orders...
        </div>
      ) : orders.length === 0 ? (
        <div className="bg-white rounded-3xl p-12 text-center border border-slate-200/80 shadow-sm space-y-4">
          <Package className="w-12 h-12 text-slate-300 mx-auto" />
          <h3 className="text-lg font-bold text-slate-800">No orders found</h3>
          <p className="text-xs text-slate-500 max-w-sm mx-auto">
            You haven't placed any orders yet. Visit our store to find products.
          </p>
          <button
            onClick={onExploreProducts}
            className="px-5 py-2.5 text-xs font-semibold text-white bg-brand-600 hover:bg-brand-700 rounded-xl transition-all shadow-sm"
          >
            Explore Catalog
          </button>
        </div>
      ) : (
        <div className="space-y-4">
          {orders.map((order) => {
            const isExpanded = expandedOrderId === order.id;
            return (
              <div
                key={order.id}
                className="bg-white rounded-2xl border border-slate-200/80 shadow-sm overflow-hidden transition-all"
              >
                {/* Header row */}
                <div
                  className="p-5 flex items-center justify-between cursor-pointer hover:bg-slate-50/70 transition-colors"
                  onClick={() => setExpandedOrderId(isExpanded ? null : order.id)}
                >
                  <div className="flex items-center gap-4">
                    <div className="w-10 h-10 rounded-xl bg-slate-100 flex items-center justify-center text-slate-600 font-bold text-sm">
                      #{order.id}
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-sm text-slate-900">
                          ${Number(order.total_amount).toFixed(2)}
                        </span>
                        {getStatusBadge(order.status)}
                      </div>
                      <div className="text-xs text-slate-400 mt-0.5">
                        {new Date(order.created_at).toLocaleString()} • {order.items?.length || 0} items
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-3">
                    {order.status === 'confirmed' && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          handleCancel(order.id);
                        }}
                        className="px-2.5 py-1 text-xs font-medium text-slate-500 hover:text-rose-600 border border-slate-200 hover:border-rose-300 rounded-lg transition-colors"
                      >
                        Cancel
                      </button>
                    )}
                    <button className="text-slate-400">
                      {isExpanded ? <ChevronUp className="w-5 h-5" /> : <ChevronDown className="w-5 h-5" />}
                    </button>
                  </div>
                </div>

                {/* Expanded details */}
                {isExpanded && (
                  <div className="p-5 bg-slate-50/50 border-t border-slate-100 space-y-4 text-xs animate-in fade-in duration-150">
                    {order.failure_reason && (
                      <div className="p-3 bg-rose-50 border border-rose-200 rounded-xl text-rose-800">
                        <span className="font-bold">Failure Explanation: </span>
                        {order.failure_reason}
                      </div>
                    )}

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                      <div>
                        <span className="font-semibold text-slate-400 uppercase tracking-wider text-[10px]">
                          Shipping Address
                        </span>
                        <p className="text-slate-700 mt-0.5">{order.shipping_address || 'N/A'}</p>
                      </div>
                      <div>
                        <span className="font-semibold text-slate-400 uppercase tracking-wider text-[10px]">
                          Payment Reference
                        </span>
                        <p className="font-mono text-slate-700 mt-0.5">{order.payment_id || 'None'}</p>
                      </div>
                    </div>

                    <div>
                      <span className="font-semibold text-slate-400 uppercase tracking-wider text-[10px] block mb-2">
                        Line Items
                      </span>
                      <div className="divide-y divide-slate-100 bg-white rounded-xl border border-slate-200/80 overflow-hidden">
                        {order.items.map((item) => (
                          <div key={item.id} className="p-3 flex justify-between items-center">
                            <div>
                              <span className="font-semibold text-slate-800">
                                Product #{item.product_id}
                              </span>
                              <span className="text-slate-400 ml-2">× {item.quantity}</span>
                            </div>
                            <span className="font-bold text-slate-900">
                              ${Number(item.subtotal || item.unit_price * item.quantity).toFixed(2)}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
