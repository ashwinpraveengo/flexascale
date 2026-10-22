import React, { useState } from 'react';
import { User as UserIcon, Lock, Mail, ArrowRight, Shield, RefreshCw } from 'lucide-react';
import { User } from '../types';
import { api, ApiError } from '../api';

interface AuthViewsProps {
  mode: 'login' | 'register';
  onSuccess: (user: User) => void;
  onSwitchMode: (mode: 'login' | 'register') => void;
}

export const AuthViews: React.FC<AuthViewsProps> = ({
  mode,
  onSuccess,
  onSwitchMode,
}) => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [address, setAddress] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      if (mode === 'login') {
        const res = await api.auth.login(email, password);
        onSuccess(res.user);
      } else {
        const res = await api.auth.register({
          email,
          password,
          full_name: fullName,
          address,
        });
        onSuccess(res.user);
      }
    } catch (err: any) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError(err.message || 'Authentication failed');
      }
    } finally {
      setLoading(false);
    }
  };

  const autofill = (userEmail: string, userPass: string) => {
    setEmail(userEmail);
    setPassword(userPass);
  };

  return (
    <div className="max-w-md mx-auto py-12 pb-16 space-y-6">
      <div className="bg-white rounded-3xl p-8 border border-slate-200/80 shadow-lg space-y-6">
        <div className="text-center space-y-1">
          <h1 className="text-2xl font-extrabold text-slate-900 tracking-tight">
            {mode === 'login' ? 'Welcome Back' : 'Create an Account'}
          </h1>
          <p className="text-xs text-slate-500">
            {mode === 'login'
              ? 'Sign in to access your cart, orders, and checkout'
              : 'Register to start shopping our cloud-native store'}
          </p>
        </div>

        {/* 1-Click Demo Logins for Quick Testing */}
        {mode === 'login' && (
          <div className="p-3 bg-slate-50 rounded-2xl border border-slate-100 space-y-2">
            <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block text-center">
              Quick Test Credentials
            </span>
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => autofill('demo@flexascale.io', 'CustomerPass123!')}
                className="py-1.5 px-2 bg-white hover:bg-brand-50 border border-slate-200 hover:border-brand-300 rounded-lg text-xs font-semibold text-slate-700 transition-colors"
              >
                👤 Customer (Alice)
              </button>
              <button
                type="button"
                onClick={() => autofill('admin@flexascale.io', 'AdminPass123!')}
                className="py-1.5 px-2 bg-white hover:bg-purple-50 border border-slate-200 hover:border-purple-300 rounded-lg text-xs font-semibold text-purple-700 transition-colors"
              >
                ⚡ Admin
              </button>
            </div>
          </div>
        )}

        {error && (
          <div className="p-3 rounded-xl bg-rose-50 border border-rose-200 text-rose-800 text-xs font-medium animate-in fade-in">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4 text-xs">
          {mode === 'register' && (
            <div>
              <label className="block font-bold text-slate-600 uppercase mb-1">Full Name</label>
              <div className="relative">
                <UserIcon className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
                <input
                  type="text"
                  required
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  placeholder="Jane Doe"
                  className="w-full pl-9 pr-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-brand-500 text-sm"
                />
              </div>
            </div>
          )}

          <div>
            <label className="block font-bold text-slate-600 uppercase mb-1">Email Address</label>
            <div className="relative">
              <Mail className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="name@example.com"
                className="w-full pl-9 pr-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-brand-500 text-sm"
              />
            </div>
          </div>

          <div>
            <label className="block font-bold text-slate-600 uppercase mb-1">Password</label>
            <div className="relative">
              <Lock className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className="w-full pl-9 pr-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-brand-500 text-sm"
              />
            </div>
          </div>

          {mode === 'register' && (
            <div>
              <label className="block font-bold text-slate-600 uppercase mb-1">Shipping Address (Optional)</label>
              <textarea
                rows={2}
                value={address}
                onChange={(e) => setAddress(e.target.value)}
                placeholder="Street address, city, state"
                className="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-brand-500 text-xs"
              />
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full py-3.5 px-4 rounded-xl font-bold text-sm bg-brand-600 hover:bg-brand-700 text-white shadow-md shadow-brand-500/25 transition-all flex items-center justify-center gap-2 hover:-translate-y-0.5 mt-2"
          >
            {loading ? (
              <>
                <RefreshCw className="w-4 h-4 animate-spin" /> Authenticating...
              </>
            ) : mode === 'login' ? (
              <>
                Sign In <ArrowRight className="w-4 h-4" />
              </>
            ) : (
              <>
                Create Account <ArrowRight className="w-4 h-4" />
              </>
            )}
          </button>
        </form>

        <div className="pt-2 text-center text-xs text-slate-500">
          {mode === 'login' ? (
            <span>
              Don't have an account?{' '}
              <button
                onClick={() => onSwitchMode('register')}
                className="font-bold text-brand-600 hover:text-brand-700 underline"
              >
                Sign Up
              </button>
            </span>
          ) : (
            <span>
              Already have an account?{' '}
              <button
                onClick={() => onSwitchMode('login')}
                className="font-bold text-brand-600 hover:text-brand-700 underline"
              >
                Sign In
              </button>
            </span>
          )}
        </div>
      </div>
    </div>
  );
};
