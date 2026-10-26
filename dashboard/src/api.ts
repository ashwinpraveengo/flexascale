export type Json = any; // eslint-disable-line @typescript-eslint/no-explicit-any

async function request(path: string, init?: RequestInit): Promise<Json> {
  const res = await fetch(path, {
    ...init,
    headers: { 'content-type': 'application/json', ...(init?.headers || {}) },
  });
  const text = await res.text();
  let body: Json = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    throw new Error(`${res.status} ${res.statusText}: not JSON`);
  }
  if (!res.ok) {
    const detail = body?.detail;
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail ?? res.statusText));
  }
  return body;
}

export const api = {
  overview: () => request('/api/lab/overview'),
  scenarios: () => request('/api/lab/scenarios'),
  live: (app: string) => request(`/api/lab/apps/${encodeURIComponent(app)}/live`).then(withLeaseOwnership),
  active: () => request('/api/lab/experiments/active'),
  runs: () => request('/api/lab/experiments'),
  run: (id: string) => request(`/api/lab/experiments/${encodeURIComponent(id)}`),
  compare: (a: string, b: string) =>
    request(`/api/lab/compare?baseline=${encodeURIComponent(a)}&candidate=${encodeURIComponent(b)}`),
  benchmark: (app: string) => request(`/api/lab/benchmark?app=${encodeURIComponent(app)}`),
  models: () => request('/api/lab/models'),
  start: (body: Json) => request('/api/lab/experiments', { method: 'POST', body: JSON.stringify(body) }),
  stop: () => request('/api/lab/experiments/stop', { method: 'POST' }),
};

/** Categorical slots in fixed order (validated palette); assign by entity, never by rank. */
export const SERIES = ['--s1', '--s2', '--s3', '--s4', '--s5', '--s6', '--s7', '--s8'];

export function seriesColor(index: number): string {
  return `var(${SERIES[index % SERIES.length]})`;
}

/**
 * The backend reports any frozen HPA as owner "flexascale". The lab's pre-run replica reset
 * also freezes HPAs briefly, with the controller lease free; only a held lease means FlexaScale.
 */
function withLeaseOwnership(live: Json): Json {
  const leaseHeld = !!live?.lease?.holder && !live.lease.expired;
  if (leaseHeld || !Array.isArray(live?.services)) return live;
  return { ...live, services: live.services.map((s: Json) => (s.owner === 'flexascale' ? { ...s, owner: 'reset' } : s)) };
}

export const OWNER_COLOR: Record<string, string> = {
  hpa: 'var(--hpa)',
  flexascale: 'var(--flexa)',
  reset: 'var(--muted)',
  none: 'var(--muted)',
  excluded: 'var(--muted)',
};

export const OWNER_LABEL: Record<string, string> = {
  hpa: 'Native HPA',
  flexascale: 'FlexaScale',
  reset: 'Held at minimum by the pre-run reset',
  none: 'No autoscaler',
  excluded: 'Not managed',
};

export const CONTROLLER_LABEL: Record<string, string> = {
  hpa: 'Native HPA',
  flexascale: 'FlexaScale',
  auto: 'Auto',
  hpa_fast: 'Native HPA, 60 s scale-down',
};

/** Native HPA in charge: the default HPA, or the tuned-HPA reference (shorter scale-down window). */
/** Failure-rate differences are fractions of a percentage point: show them with two decimals. */
export const deltaDigits = (unit: string) => (unit.trim() === 'pp' ? 2 : 1);

export const isNativeHpa = (controller: string | undefined) => controller === 'hpa' || controller === 'hpa_fast';

export function fmt(v: number | null | undefined, digits = 0, suffix = ''): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  return `${v.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits })}${suffix}`;
}

export function fmtSigned(v: number | null | undefined, digits = 1, suffix = ''): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  const shown = fmt(Math.abs(v), digits);
  const zero = Number(Math.abs(v).toFixed(digits)) === 0;
  return `${zero ? '' : v > 0 ? '+' : '−'}${shown}${suffix}`;
}

export function fmtElapsed(s: number | null | undefined): string {
  if (s === null || s === undefined) return 'prep';
  const m = Math.floor(s / 60);
  const r = Math.floor(s % 60);
  return `${m}:${r.toString().padStart(2, '0')}`;
}

export function fmtAgo(ts: number | null | undefined): string {
  if (!ts) return '—';
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return `${Math.round(s)} s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

export function fmtMoney(v: number | null | undefined, currency = 'USD', digits = 4): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  const sym = currency === 'USD' ? '$' : `${currency} `;
  return `${sym}${fmt(v, digits)}`;
}

export const TERMINAL = ['completed', 'stopped', 'failed', 'interrupted'];
