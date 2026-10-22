import React from 'react';
import { CheckCircle2, Package, ArrowRight, Truck, Calendar } from 'lucide-react';
import { Order } from '../types';

interface OrderConfirmationViewProps {
  order: Order;
  onViewOrders: () => void;
  onContinueShopping: () => void;
}

export const OrderConfirmationView: React.FC<OrderConfirmationViewProps> = ({
  order,
  onViewOrders,
  onContinueShopping,
}) => {
  return (
    <div className="max-w-2xl mx-auto space-y-8 py-10 pb-16">
      <div className="bg-white rounded-3xl p-8 sm:p-10 border border-slate-200/80 shadow-lg text-center space-y-6">
        <div className="w-20 h-20 mx-auto rounded-3xl bg-emerald-50 text-emerald-600 flex items-center justify-center border border-emerald-100 shadow-sm animate-in zoom-in duration-300">
          <CheckCircle2 className="w-12 h-12" />
        </div>

        <div className="space-y-2">
          <span className="text-xs font-bold uppercase tracking-wider text-emerald-600 bg-emerald-50 px-3 py-1 rounded-full border border-emerald-200">
            Order Confirmed & Payment Captured
          </span>
          <h1 className="text-3xl font-extrabold text-slate-900 tracking-tight">
            Thank you for your order!
          </h1>
          <p className="text-sm text-slate-500">
            We've received your order and initiated inventory fulfillment.
          </p>
        </div>

        {/* Order Details Card */}
        <div className="bg-slate-50 rounded-2xl p-5 text-left space-y-3 text-xs border border-slate-100">
          <div className="flex justify-between items-center pb-3 border-b border-slate-200">
            <div>
              <span className="text-slate-400">Order Reference</span>
              <div className="font-bold text-slate-900 text-sm">#{order.id}</div>
            </div>
            <div className="text-right">
              <span className="text-slate-400">Transaction ID</span>
              <div className="font-mono text-slate-700 text-[11px] truncate max-w-[140px]">
                {order.payment_id || 'N/A'}
              </div>
            </div>
          </div>

          <div className="flex justify-between text-slate-600">
            <span className="flex items-center gap-1.5">
              <Calendar className="w-3.5 h-3.5 text-slate-400" /> Date
            </span>
            <span className="font-medium text-slate-800">
              {new Date(order.created_at).toLocaleString()}
            </span>
          </div>

          <div className="flex justify-between text-slate-600">
            <span className="flex items-center gap-1.5">
              <Truck className="w-3.5 h-3.5 text-slate-400" /> Shipping Destination
            </span>
            <span className="font-medium text-slate-800 max-w-[240px] truncate">
              {order.shipping_address || 'Default address'}
            </span>
          </div>

          <div className="pt-2 border-t border-slate-200 flex justify-between items-baseline text-sm font-bold text-slate-900">
            <span>Total Charged</span>
            <span className="text-base text-brand-600">${Number(order.total_amount).toFixed(2)}</span>
          </div>
        </div>

        {/* Ordered Items Preview */}
        {order.items && order.items.length > 0 && (
          <div className="text-left space-y-2 pt-2">
            <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider">
              Items Ordered ({order.items.length})
            </h3>
            <div className="divide-y divide-slate-100 border border-slate-100 rounded-xl overflow-hidden bg-white">
              {order.items.map((item) => (
                <div key={item.id} className="p-3 flex justify-between items-center text-xs">
                  <div className="flex items-center gap-2">
                    <Package className="w-4 h-4 text-slate-400" />
                    <span className="font-medium text-slate-800">
                      Product #{item.product_id}
                    </span>
                    <span className="text-slate-400">× {item.quantity}</span>
                  </div>
                  <span className="font-bold text-slate-900">
                    ${Number(item.subtotal || item.unit_price * item.quantity).toFixed(2)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="flex flex-col sm:flex-row gap-3 pt-4">
          <button
            onClick={onViewOrders}
            className="flex-1 py-3 px-4 rounded-xl font-semibold text-xs bg-slate-100 hover:bg-slate-200 text-slate-800 transition-colors"
          >
            View Order History
          </button>
          <button
            onClick={onContinueShopping}
            className="flex-1 py-3 px-4 rounded-xl font-semibold text-xs bg-brand-600 hover:bg-brand-700 text-white shadow-md shadow-brand-500/20 transition-all flex items-center justify-center gap-1.5"
          >
            Continue Shopping <ArrowRight className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
};
