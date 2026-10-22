import React, { useState } from 'react';
import { ShieldCheck, CreditCard, AlertCircle, RefreshCw, CheckCircle2 } from 'lucide-react';
import { User, Cart, Order } from '../types';
import { api, ApiError } from '../api';

interface CheckoutViewProps {
  user: User;
  cart: Cart | null;
  onSuccess: (order: Order) => void;
  onBack: () => void;
}

export const CheckoutView: React.FC<CheckoutViewProps> = ({
  user,
  cart,
  onSuccess,
  onBack,
}) => {
  const [shippingAddress, setShippingAddress] = useState(
    user.address || '42 Cloud Native Blvd, Suite 100, Kubernetes City, CA 94105'
  );
  const [cardNumber, setCardNumber] = useState('4000000000000001');
  const [simulateFailure, setSimulateFailure] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const subtotal = cart?.total_amount || 0;
  const shipping = subtotal > 100 ? 0 : 9.99;
  const tax = Math.round(subtotal * 0.08 * 100) / 100;
  const total = Math.round((subtotal + shipping + tax) * 100) / 100;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      const order = await api.orders.checkout({
        user_id: user.id,
        shipping_address: shippingAddress,
        card_number: cardNumber,
        payment_method: 'simulated_card',
        simulate_failure: simulateFailure,
        idempotency_key: `idemp_${Date.now()}_${Math.random().toString(36).substring(7)}`,
      });

      setLoading(false);
      onSuccess(order);
    } catch (err: any) {
      setLoading(false);
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError(err.message || 'Checkout failed. Please try again.');
      }
    }
  };

  return (
    <div className="max-w-4xl mx-auto space-y-8 pb-16">
      <div className="pb-4 border-b border-slate-200">
        <h1 className="text-3xl font-extrabold text-slate-900 tracking-tight">Checkout</h1>
        <p className="text-sm text-slate-500 mt-1">
          Complete your purchase securely through the microservice gateway
        </p>
      </div>

      {error && (
        <div className="p-4 rounded-2xl bg-rose-50 border border-rose-200 text-rose-800 flex items-start gap-3 animate-in fade-in">
          <AlertCircle className="w-5 h-5 text-rose-600 flex-shrink-0 mt-0.5" />
          <div className="text-sm">
            <h4 className="font-bold">Transaction Aborted</h4>
            <p className="mt-0.5 text-rose-700">{error}</p>
            <p className="mt-1 text-xs text-rose-500 font-mono">
              Note: Resilient 2-phase saga automatically released any reserved inventory items.
            </p>
          </div>
        </div>
      )}

      <form onSubmit={handleSubmit} className="grid grid-cols-1 md:grid-cols-3 gap-8">
        {/* Left Form: Shipping & Simulated Payment */}
        <div className="md:col-span-2 space-y-6">
          {/* Shipping Address */}
          <div className="bg-white p-6 rounded-3xl border border-slate-200/80 shadow-sm space-y-4">
            <h2 className="text-base font-bold text-slate-900 flex items-center gap-2">
              <span className="w-6 h-6 rounded-full bg-brand-100 text-brand-700 text-xs flex items-center justify-center font-bold">
                1
              </span>
              Shipping Destination
            </h2>

            <div>
              <label className="block text-xs font-semibold text-slate-600 uppercase tracking-wider mb-1.5">
                Full Street Address
              </label>
              <textarea
                required
                rows={3}
                value={shippingAddress}
                onChange={(e) => setShippingAddress(e.target.value)}
                className="w-full px-4 py-2.5 text-sm bg-slate-50 border border-slate-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-brand-500"
                placeholder="Street address, city, state, postal code"
              />
            </div>
          </div>

          {/* Payment Simulation */}
          <div className="bg-white p-6 rounded-3xl border border-slate-200/80 shadow-sm space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-base font-bold text-slate-900 flex items-center gap-2">
                <span className="w-6 h-6 rounded-full bg-brand-100 text-brand-700 text-xs flex items-center justify-center font-bold">
                  2
                </span>
                Simulated Payment Method
              </h2>
              <div className="flex items-center gap-1.5 text-xs font-medium text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded-md border border-emerald-200">
                <ShieldCheck className="w-3.5 h-3.5" />
                <span>Simulated Sandbox</span>
              </div>
            </div>

            <div className="space-y-3">
              <label className="block text-xs font-semibold text-slate-600 uppercase tracking-wider">
                Select Test Scenario Card
              </label>
              <select
                value={cardNumber}
                onChange={(e) => setCardNumber(e.target.value)}
                className="w-full px-4 py-2.5 text-sm bg-slate-50 border border-slate-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-brand-500 font-medium text-slate-800"
              >
                <option value="4000000000000001">
                  💳 Test Visa (Success Scenario) - 4000 ... 0001
                </option>
                <option value="4000000000000002">
                  ❌ Test Card (Decline Scenario) - 4000 ... 0002
                </option>
                <option value="4000000000009999">
                  ❌ Test Card (Bank Error Scenario) - 4000 ... 9999
                </option>
              </select>
            </div>

            {/* Failure Simulation Toggle */}
            <div className="pt-2">
              <label className="flex items-center gap-2.5 cursor-pointer p-3 rounded-xl bg-amber-50/70 border border-amber-200/80">
                <input
                  type="checkbox"
                  checked={simulateFailure}
                  onChange={(e) => setSimulateFailure(e.target.checked)}
                  className="w-4 h-4 text-amber-600 rounded focus:ring-amber-500 border-amber-300"
                />
                <span className="text-xs font-semibold text-amber-900">
                  Force Payment Failure (Tests automated inventory reservation rollback)
                </span>
              </label>
            </div>
          </div>
        </div>

        {/* Right Summary */}
        <div className="bg-white p-6 rounded-3xl border border-slate-200/80 shadow-sm space-y-6 h-fit">
          <h2 className="text-base font-bold text-slate-900 border-b border-slate-100 pb-3">
            Review Order
          </h2>

          <div className="space-y-3 max-h-48 overflow-y-auto pr-1">
            {cart?.items.map((item) => (
              <div key={item.id} className="flex justify-between items-center text-xs">
                <span className="truncate max-w-[160px] text-slate-700">
                  {item.quantity}x {item.product_name || `Product #${item.product_id}`}
                </span>
                <span className="font-semibold text-slate-900">
                  ${Number(item.subtotal || 0).toFixed(2)}
                </span>
              </div>
            ))}
          </div>

          <div className="space-y-2 pt-3 border-t border-slate-100 text-xs text-slate-600">
            <div className="flex justify-between">
              <span>Subtotal</span>
              <span className="font-semibold text-slate-900">${subtotal.toFixed(2)}</span>
            </div>
            <div className="flex justify-between">
              <span>Shipping</span>
              <span className="font-semibold text-slate-900">
                {shipping === 0 ? 'FREE' : `$${shipping.toFixed(2)}`}
              </span>
            </div>
            <div className="flex justify-between">
              <span>Tax (8%)</span>
              <span className="font-semibold text-slate-900">${tax.toFixed(2)}</span>
            </div>
            <div className="pt-2 border-t border-slate-100 flex justify-between text-sm font-bold text-slate-900">
              <span>Grand Total</span>
              <span className="text-lg font-black text-brand-600">${total.toFixed(2)}</span>
            </div>
          </div>

          <button
            type="submit"
            disabled={loading || subtotal === 0}
            className="w-full py-4 rounded-xl font-bold text-sm bg-brand-600 hover:bg-brand-700 text-white shadow-lg shadow-brand-500/25 disabled:opacity-50 transition-all flex items-center justify-center gap-2 hover:-translate-y-0.5"
          >
            {loading ? (
              <>
                <RefreshCw className="w-4 h-4 animate-spin" />
                Coordinating Saga...
              </>
            ) : (
              <>
                <CreditCard className="w-4 h-4" />
                Authorize & Place Order
              </>
            )}
          </button>

          <button
            type="button"
            onClick={onBack}
            className="w-full text-center text-xs text-slate-500 hover:text-slate-800"
          >
            Return to Cart
          </button>
        </div>
      </form>
    </div>
  );
};
