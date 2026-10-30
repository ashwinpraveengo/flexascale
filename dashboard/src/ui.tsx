import { ReactNode, useCallback, useEffect, useRef, useState } from 'react';
import { OWNER_COLOR, OWNER_LABEL } from './api';

/* ------------------------------------------------------------------ icons (inline, 1.75px stroke) */

const P: Record<string, string> = {
  overview: 'M3 13h8V3H3zM13 21h8V11h-8zM13 3v6h8V3zM3 21h8v-6H3z',
  live: 'M3 12h4l3 8 4-16 3 8h4',
  compare: 'M4 20V10M10 20V4M16 20v-7M22 20H2',
  auto: 'M12 2v4M12 18v4M4.9 4.9l2.8 2.8M16.3 16.3l2.8 2.8M2 12h4M18 12h4M4.9 19.1l2.8-2.8M16.3 7.7l2.8-2.8M12 8a4 4 0 100 8 4 4 0 000-8z',
  model: 'M12 2l9 5v10l-9 5-9-5V7zM12 22V12M21 7l-9 5-9-5',
  check: 'M20 6L9 17l-5-5',
  alert: 'M12 9v4M12 17h.01M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z',
  error: 'M12 8v4M12 16h.01M12 22a10 10 0 100-20 10 10 0 000 20z',
  info: 'M12 16v-4M12 8h.01M12 22a10 10 0 100-20 10 10 0 000 20z',
  play: 'M6 4l14 8-14 8z',
  stop: 'M6 6h12v12H6z',
  external: 'M14 3h7v7M10 14L21 3M21 14v7H3V3h7',
  sun: 'M12 17a5 5 0 100-10 5 5 0 000 10zM12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4',
  moon: 'M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z',
  menu: 'M3 6h18M3 12h18M3 18h18',
  server: 'M3 4h18v6H3zM3 14h18v6H3zM7 7h.01M7 17h.01',
  cost: 'M12 1v22M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6',
  shield: 'M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z',
  layers: 'M12 2l10 6-10 6L2 8zM2 16l10 6 10-6',
  clock: 'M12 22a10 10 0 100-20 10 10 0 000 20zM12 6v6l4 2',
  refresh: 'M23 4v6h-6M1 20v-6h6M3.5 9a9 9 0 0114.8-3.4L23 10M1 14l4.7 4.4A9 9 0 0020.5 15',
  graph: 'M5 6a2 2 0 100-4 2 2 0 000 4zM19 6a2 2 0 100-4 2 2 0 000 4zM12 22a2 2 0 100-4 2 2 0 000 4zM5 6l6.5 12M19 6l-6.5 12M7 4h10',
  history: 'M3 12a9 9 0 109-9 9.7 9.7 0 00-6.7 2.8L3 8M3 3v5h5M12 7v5l4 2',
};

export function Icon({ name, size = 16, className = '', style }: { name: keyof typeof P | string; size?: number; className?: string; style?: React.CSSProperties }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" className={className} style={style} aria-hidden>
      <path d={P[name] || P.info} />
    </svg>
  );
}

/* ------------------------------------------------------------------ status */

export type Level = 'good' | 'warning' | 'serious' | 'critical' | 'unknown';

const LEVEL: Record<Level, { color: string; icon: string; label: string }> = {
  good: { color: 'var(--good)', icon: 'check', label: 'OK' },
  warning: { color: 'var(--warning)', icon: 'alert', label: 'Warning' },
  serious: { color: 'var(--serious)', icon: 'alert', label: 'Degraded' },
  critical: { color: 'var(--critical)', icon: 'error', label: 'Critical' },
  unknown: { color: 'var(--muted)', icon: 'info', label: 'Unknown' },
};

/** Status is never colour alone: icon + label + colour. */
export function StatusBadge({ level, label, title }: { level: Level; label?: string; title?: string }) {
  const l = LEVEL[level];
  return (
    <span className="pill" title={title}>
      <Icon name={l.icon} size={13} style={{ color: l.color }} />
      <span>{label ?? l.label}</span>
    </span>
  );
}

export function OwnerBadge({ owner, compact }: { owner: string; compact?: boolean }) {
  return (
    <span className="pill" title={OWNER_LABEL[owner] || owner}>
      <span className="dot" style={{ background: OWNER_COLOR[owner] || 'var(--muted)' }} />
      {compact ? (owner === 'flexascale' ? 'FlexaScale' : owner === 'hpa' ? 'HPA' : owner === 'reset' ? 'Reset hold' : OWNER_LABEL[owner] || owner) : OWNER_LABEL[owner] || owner}
    </span>
  );
}

/* ------------------------------------------------------------------ layout */

export function Card({ title, eyebrow, actions, children, className = '', pad = true }: {
  title?: ReactNode; eyebrow?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; pad?: boolean;
}) {
  return (
    <section className={`card fade-in min-w-0 ${pad ? 'p-4 sm:p-5' : ''} ${className}`}>
      {(title || actions || eyebrow) && (
        <header className={`flex flex-wrap items-start justify-between gap-2 ${pad ? 'mb-3' : 'p-4 sm:p-5 pb-3'}`}>
          <div className="min-w-0">
            {eyebrow && <div className="eyebrow mb-0.5">{eyebrow}</div>}
            {title && <h2 className="font-semibold text-[15px] leading-snug">{title}</h2>}
          </div>
          {actions && <div className="flex items-center gap-2 flex-wrap">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function Stat({ label, value, sub, icon, level, hint, accent }: {
  label: string; value: ReactNode; sub?: ReactNode; icon?: string; level?: Level; hint?: string; accent?: string;
}) {
  return (
    <div className="card p-4 min-w-0 fade-in relative overflow-hidden" title={hint}>
      {accent && <div className="absolute inset-x-0 top-0 h-[2px]" style={{ background: accent }} />}
      <div className="flex items-center justify-between gap-2 mb-2">
        <span className="eyebrow truncate">{label}</span>
        {icon && <Icon name={icon} size={15} className="muted shrink-0" />}
      </div>
      <div className="text-[26px] font-semibold leading-none tracking-tight truncate">{value}</div>
      {(sub || level) && (
        <div className="mt-2 text-xs ink2 flex items-center gap-1.5 min-w-0">
          {level && <Icon name={LEVEL[level].icon} size={13} style={{ color: LEVEL[level].color }} className="shrink-0" />}
          <span className="line-clamp-2">{sub}</span>
        </div>
      )}
    </div>
  );
}

export function Empty({ children, icon = 'info', height = 160 }: { children: ReactNode; icon?: string; height?: number }) {
  return (
    <div className="flex flex-col items-center justify-center text-center gap-2 muted text-sm px-4" style={{ minHeight: height }}>
      <Icon name={icon} size={22} />
      <div className="max-w-sm">{children}</div>
    </div>
  );
}

export function ErrorNote({ error, what }: { error: string | null | undefined; what?: string }) {
  if (!error) return null;
  return (
    <div role="alert" className="card-flat px-3 py-2 text-sm flex items-start gap-2" style={{ borderColor: 'var(--critical)' }}>
      <Icon name="error" size={15} style={{ color: 'var(--critical)' }} className="mt-0.5 shrink-0" />
      <span className="min-w-0 break-words">
        {what ? <b>{what}: </b> : null}
        {error}
      </span>
    </div>
  );
}

export function Skeleton({ h = 16, w = '100%', className = '' }: { h?: number; w?: number | string; className?: string }) {
  return <div className={`skeleton ${className}`} style={{ height: h, width: w }} />;
}

export function Meter({ value, max, color = 'var(--accent)', label }: { value: number | null | undefined; max: number; color?: string; label?: string }) {
  const pct = value == null ? 0 : Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div className="w-full" aria-label={label} role="meter" aria-valuenow={value ?? undefined} aria-valuemin={0} aria-valuemax={max}>
      <div className="h-1.5 rounded-full overflow-hidden" style={{ background: 'var(--surface-3)' }}>
        <div className="h-full rounded-full transition-[width] duration-500" style={{ width: `${pct}%`, background: color }} />
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ hooks */

export function usePoll<T>(fn: () => Promise<T>, ms: number, deps: unknown[] = []): { data: T | null; error: string | null; reload: () => void; loading: boolean } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const load = useCallback(() => {
    fn().then(
      (d) => {
        setData(d);
        setError(null);
        setLoading(false);
      },
      (e) => {
        setError(String(e?.message || e));
        setLoading(false);
      },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => {
    setLoading(true);
    load();
    const id = window.setInterval(() => {
      if (document.visibilityState === 'visible') load();
    }, ms);
    return () => window.clearInterval(id);
  }, [load, ms]);
  return { data, error, reload: load, loading };
}

/** Client-side ring buffer of values observed while this page is open (labelled as such where shown). */
export function useHistory<T>(value: T | null | undefined, key: unknown, max = 120): T[] {
  const buf = useRef<T[]>([]);
  const last = useRef<unknown>(undefined);
  if (value != null && key !== last.current) {
    last.current = key;
    buf.current = [...buf.current, value].slice(-max);
  }
  return buf.current;
}

export function Sparkline({ values, color = 'var(--accent)', height = 28, width = 120 }: { values: (number | null)[]; color?: string; height?: number; width?: number }) {
  const v = values.filter((x): x is number => x != null);
  if (v.length < 2) return <div style={{ height, width }} />;
  const max = Math.max(...v, 1e-9);
  const min = Math.min(...v, 0);
  const pts = values
    .map((x, i) => (x == null ? null : `${(i / (values.length - 1)) * width},${height - 2 - ((x - min) / (max - min || 1)) * (height - 4)}`))
    .filter(Boolean)
    .join(' ');
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden>
      <polyline points={pts} fill="none" stroke={color} strokeWidth={1.75} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

/* ------------------------------------------------------------------ freshness */

/** Seconds since a server timestamp, re-rendered every second. */
export function useAge(ts: number | null | undefined): number | null {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => window.clearInterval(id);
  }, []);
  return ts ? Math.max(0, now - ts) : null;
}

/** Live / stale / disconnected indicator for a polled feed. */
export function Freshness({ ts, error, staleAfter = 20, label = 'Live' }: { ts?: number | null; error?: string | null; staleAfter?: number; label?: string }) {
  const age = useAge(ts);
  const state = error ? 'down' : age == null ? 'wait' : age > staleAfter ? 'stale' : 'live';
  const color = state === 'live' ? 'var(--good)' : state === 'stale' ? 'var(--warning)' : state === 'down' ? 'var(--critical)' : 'var(--muted)';
  const text = state === 'live' ? `${label} · ${Math.round(age as number)} s` : state === 'stale' ? `Stale · ${Math.round(age as number)} s old` : state === 'down' ? 'Disconnected' : 'Connecting…';
  return (
    <span className="pill" title={error || (ts ? `last update ${new Date(ts * 1000).toLocaleTimeString()}` : undefined)} role="status">
      <span className={`dot ${state === 'live' ? 'dot-live' : ''}`} style={{ background: color, color }} />
      <span className="tnum">{text}</span>
    </span>
  );
}

export function Banner({ level, children }: { level: Level; children: ReactNode }) {
  return (
    <div role="alert" className="card-flat px-4 py-2.5 text-sm flex items-start gap-2.5 fade-in"
      style={{ borderColor: `var(--${level === 'unknown' ? 'border' : level})`, background: 'var(--surface)' }}>
      <Icon name={level === 'critical' ? 'error' : 'alert'} size={16} style={{ color: `var(--${level})` }} className="mt-0.5 shrink-0" />
      <div className="min-w-0">{children}</div>
    </div>
  );
}

/** Small labelled value used in dense panels. */
export function KV({ k, v, mono, wrap }: { k: ReactNode; v: ReactNode; mono?: boolean; wrap?: boolean }) {
  return (
    <div className="min-w-0">
      <div className="eyebrow truncate">{k}</div>
      <div className={`${wrap ? 'break-words' : 'truncate'} ${mono ? 'tnum' : ''}`}>{v}</div>
    </div>
  );
}
