export type Json = any; // eslint-disable-line @typescript-eslint/no-explicit-any

async function request(path: string, init?: RequestInit): Promise<Json> {
  const res = await fetch(path, {
    ...init,
    headers: { 'content-type': 'application/json', ...(init?.headers || {}) },
  });
  const text = await res.text();
  const body = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const detail = body?.detail;
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail ?? res.statusText));
  }
  return body;
}

export const api = {
  overview: () => request('/api/lab/overview'),
  scenarios: () => request('/api/lab/scenarios'),
  live: (app: string) => request(`/api/lab/apps/${encodeURIComponent(app)}/live`),
  active: () => request('/api/lab/experiments/active'),
  runs: () => request('/api/lab/experiments'),
  run: (id: string) => request(`/api/lab/experiments/${encodeURIComponent(id)}`),
  compare: (a: string, b: string) =>
    request(`/api/lab/compare?baseline=${encodeURIComponent(a)}&candidate=${encodeURIComponent(b)}`),
  models: () => request('/api/lab/models'),
  start: (body: Json) => request('/api/lab/experiments', { method: 'POST', body: JSON.stringify(body) }),
  stop: () => request('/api/lab/experiments/stop', { method: 'POST' }),
};

export const SERIES = ['--s1', '--s2', '--s3', '--s4', '--s5', '--s6', '--s7', '--s8'];

export function seriesColor(index: number): string {
  return `var(${SERIES[index % SERIES.length]})`;
}

export function fmt(v: number | null | undefined, digits = 0, suffix = ''): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  return `${v.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits })}${suffix}`;
}

export function fmtElapsed(s: number | null | undefined): string {
  if (s === null || s === undefined) return 'prep';
  const m = Math.floor(s / 60);
  const r = Math.floor(s % 60);
  return `${m}:${r.toString().padStart(2, '0')}`;
}
