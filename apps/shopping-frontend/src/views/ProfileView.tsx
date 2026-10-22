import React, { useState } from 'react';
import { User as UserIcon, Shield, Check, RefreshCw } from 'lucide-react';
import { User } from '../types';
import { api } from '../api';

interface ProfileViewProps {
  user: User;
  onUpdateUser: (user: User) => void;
}

export const ProfileView: React.FC<ProfileViewProps> = ({ user, onUpdateUser }) => {
  const [fullName, setFullName] = useState(user.full_name);
  const [address, setAddress] = useState(user.address || '');
  const [password, setPassword] = useState('');
  const [saving, setSaving] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    setSuccess(false);

    try {
      const payload: any = { full_name: fullName, address };
      if (password) payload.password = password;
      const updated = await api.auth.updateProfile(payload);
      onUpdateUser(updated);
      setSuccess(true);
      setPassword('');
      setTimeout(() => setSuccess(false), 3000);
    } catch (err: any) {
      setError(err.message || 'Failed to update profile');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto space-y-8 pb-16">
      <div className="pb-4 border-b border-slate-200">
        <h1 className="text-3xl font-extrabold text-slate-900 tracking-tight">User Profile</h1>
        <p className="text-sm text-slate-500 mt-1">Manage your account information and default addresses</p>
      </div>

      <div className="bg-white rounded-3xl p-8 border border-slate-200/80 shadow-sm space-y-6">
        <div className="flex items-center gap-4 pb-6 border-b border-slate-100">
          <div className="w-16 h-16 rounded-2xl bg-gradient-to-tr from-brand-600 to-indigo-600 text-white flex items-center justify-center font-bold text-2xl uppercase shadow-md shadow-brand-500/20">
            {user.full_name?.charAt(0) || user.email.charAt(0)}
          </div>
          <div>
            <h2 className="text-xl font-bold text-slate-900">{user.full_name}</h2>
            <p className="text-xs text-slate-500">{user.email}</p>
            <span className="inline-flex items-center gap-1 mt-1 text-[11px] font-semibold uppercase px-2 py-0.5 rounded-full bg-brand-50 text-brand-700 border border-brand-200">
              <Shield className="w-3 h-3" /> {user.role}
            </span>
          </div>
        </div>

        {success && (
          <div className="p-3.5 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-800 text-xs font-semibold flex items-center gap-2">
            <Check className="w-4 h-4 text-emerald-600" /> Profile successfully updated!
          </div>
        )}

        {error && (
          <div className="p-3.5 rounded-xl bg-rose-50 border border-rose-200 text-rose-800 text-xs font-semibold">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-5 text-sm">
          <div>
            <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">
              Full Name
            </label>
            <input
              type="text"
              required
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-brand-500 text-slate-900"
            />
          </div>

          <div>
            <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">
              Email Address
            </label>
            <input
              type="email"
              disabled
              value={user.email}
              className="w-full px-4 py-2.5 bg-slate-100 border border-slate-200 rounded-xl text-slate-500 cursor-not-allowed"
            />
          </div>

          <div>
            <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">
              Default Shipping Address
            </label>
            <textarea
              rows={3}
              value={address}
              onChange={(e) => setAddress(e.target.value)}
              className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-brand-500 text-slate-900"
              placeholder="Enter your street address, city, state and zip"
            />
          </div>

          <div>
            <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">
              New Password (Optional)
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-brand-500 text-slate-900"
              placeholder="Leave blank to keep current password"
            />
          </div>

          <button
            type="submit"
            disabled={saving}
            className="w-full py-3.5 px-6 rounded-xl font-bold text-sm bg-brand-600 hover:bg-brand-700 text-white shadow-md shadow-brand-500/20 transition-all flex items-center justify-center gap-2"
          >
            {saving ? (
              <>
                <RefreshCw className="w-4 h-4 animate-spin" /> Saving Changes...
              </>
            ) : (
              'Save Changes'
            )}
          </button>
        </form>
      </div>
    </div>
  );
};
