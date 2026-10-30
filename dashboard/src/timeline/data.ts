/**
 * Data model of the Live Autoscaling Timeline.
 *
 * Every value comes from a recorded sample (lab experiment samples every 5 s, or the lab's live
 * history of /live polls). Nothing is interpolated or synthesised:
 *  - a null value, or a gap of more than GAP_FACTOR sample intervals, breaks the line;
 *  - a scaling marker exists only where two consecutive samples show different desired replicas;
 *  - proposals (FlexaScale policy, HPA) are shown only for samples whose decision was recent.
 */
import { Json } from '../api';

export const GAP_FACTOR = 2.5;

export interface SvcPoint {
  desired: number | null;
  ready: number | null;
  hpaDesired: number | null;
  frozen: boolean;
  owner: Owner;
  cpu: number | null;
  mem: number | null;
  rps: number | null;
  errRate: number | null;
  latency: number | null;
  latencyP95: number | null;
  noTraffic: boolean;
  stale: boolean;
  missing: string[];
  /** FlexaScale policy's own proposal (before safety guards). */
  fsPolicy: number | null;
  /** What FlexaScale requested after the guards, only while it owns the service. */
  fsProposed: number | null;
  fsApplied: boolean | null;
  /** Native HPA's proposal: its status.desiredReplicas while it owns the service (real), else the rule estimate. */
  hpaProposal: number | null;
  hpaProposalKind: 'hpa_status' | 'rule_estimate' | null;
}

export type Owner = 'hpa' | 'flexascale' | 'reset' | 'none';

export interface TPoint {
  t: number;
  elapsed: number | null;
  users: number | null;
  rps: number | null;
  failRps: number | null;
  p50: number | null;
  p95: number | null;
  p99: number | null;
  e2eViolation: boolean | null;
  services: Record<string, SvcPoint>;
}

export interface TEvent {
  t: number;
  kind: string;
  message: string;
  service?: string;
  frm?: number;
  to?: number;
  owner?: string;
}

export type FeedMode = 'live' | 'replay' | 'live-history';

export interface Feed {
  mode: FeedMode;
  points: TPoint[];
  events: TEvent[];
  interval: number;
  /** Load start (experiment) for "+m:ss" labels; null outside experiments. */
  start: number | null;
  /** Planned load duration in seconds (experiments): the "Run" window spans it. */
  duration?: number | null;
  services: string[];
  sloE2eMs: number | null;
  sloServiceMs: number | null;
  cpuTargetPct: number | null;
  /** Free text for the badge (run id, recorded date). */
  label?: string;
  controller?: string;
}

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);

/** Lab experiment sample -> TPoint. ``fsRun``: FlexaScale or Auto run (a frozen HPA means FlexaScale owns it). */
export function fromExperimentSample(s: Json, fsRun: boolean): TPoint {
  const services: Record<string, SvcPoint> = {};
  for (const [name, v] of Object.entries<Json>(s.services || {})) {
    const frozen = !!v.frozen;
    const owner: Owner = frozen ? (fsRun ? 'flexascale' : 'reset') : v.hpa ? 'hpa' : 'none';
    const hpaActive = !!v.hpa && !frozen;
    services[name] = {
      desired: num(v.desired),
      ready: num(v.ready),
      hpaDesired: num(v.hpa_desired),
      frozen,
      owner,
      cpu: num(v.cpu_pct),
      mem: num(v.memory_pct),
      rps: num(v.request_rate),
      errRate: num(v.error_rate),
      latency: num(v.latency_ms),
      latencyP95: num(v.latency_p95_ms),
      noTraffic: !!v.no_traffic,
      stale: !!v.stale,
      missing: Array.isArray(v.missing) ? v.missing : [],
      fsPolicy: num(v.fs_policy),
      fsProposed: num(v.fs_proposed),
      fsApplied: v.fs_applied ?? null,
      hpaProposal: hpaActive ? num(v.hpa_desired) : num(v.hpa_rule),
      hpaProposalKind: hpaActive && num(v.hpa_desired) != null ? 'hpa_status' : num(v.hpa_rule) != null ? 'rule_estimate' : null,
    };
  }
  return {
    t: s.t,
    elapsed: num(s.elapsed),
    users: num(s.users),
    rps: num(s.rps),
    failRps: num(s.fail_rps),
    p50: num(s.p50_ms),
    p95: num(s.p95_ms),
    p99: num(s.p99_ms),
    e2eViolation: s.p95_ms == null ? null : !!s.e2e_slo_violation,
    services,
  };
}

/** Lab live-history point (no Locust data outside experiments). */
export function fromHistoryPoint(h: Json): TPoint {
  const services: Record<string, SvcPoint> = {};
  for (const [name, v] of Object.entries<Json>(h.services || {})) {
    const frozen = !!v.frozen;
    const owner: Owner = v.owner === 'flexascale' && h.lease_held ? 'flexascale' : frozen ? 'reset' : v.owner === 'hpa' ? 'hpa' : 'none';
    services[name] = {
      desired: num(v.desired), ready: num(v.ready), hpaDesired: num(v.hpa_desired), frozen, owner,
      cpu: num(v.cpu_pct), mem: num(v.memory_pct), rps: num(v.request_rate), errRate: num(v.error_rate),
      latency: num(v.latency_mean_ms), latencyP95: num(v.latency_p95_ms), noTraffic: !!v.no_traffic, stale: !!v.stale,
      missing: Array.isArray(v.missing) ? v.missing : [],
      fsPolicy: null, fsProposed: null, fsApplied: null,
      hpaProposal: owner === 'hpa' ? num(v.hpa_desired) : null, hpaProposalKind: owner === 'hpa' && num(v.hpa_desired) != null ? 'hpa_status' : null,
    };
  }
  return { t: h.t, elapsed: null, users: null, rps: null, failRps: null, p50: null, p95: null, p99: null, e2eViolation: null, services };
}

export function fromEvent(e: Json): TEvent {
  return { t: e.t, kind: e.kind, message: e.message, service: e.service, frm: num(e.frm) ?? undefined, to: num(e.to) ?? undefined, owner: e.owner };
}

/** Merge new points into a sorted series without duplicates (incremental polling). */
export function mergePoints(prev: TPoint[], add: TPoint[], max = 4000): TPoint[] {
  if (!add.length) return prev;
  const lastT = prev.length ? prev[prev.length - 1].t : -Infinity;
  const fresh = add.filter((p) => p.t > lastT).sort((a, b) => a.t - b.t);
  const out = fresh.length ? prev.concat(fresh) : prev;
  return out.length > max ? out.slice(out.length - max) : out;
}

export function mergeEvents(prev: TEvent[], add: TEvent[], max = 4000): TEvent[] {
  if (!add.length) return prev;
  const lastT = prev.length ? prev[prev.length - 1].t : -Infinity;
  const fresh = add.filter((e) => e.t > lastT);
  const out = fresh.length ? prev.concat(fresh) : prev;
  return out.length > max ? out.slice(out.length - max) : out;
}

/* ------------------------------------------------------------------ selection / aggregation */

export const ALL = '__all__';

export interface View {
  desired: number | null;
  ready: number | null;
  fsPolicy: number | null;
  fsProposed: number | null;
  hpaProposal: number | null;
  hpaProposalKind: SvcPoint['hpaProposalKind'];
  rps: number | null;
  latency: number | null;
  latencyP95: number | null;
  cpu: number | null;
  mem: number | null;
  owner: Owner | 'mixed' | null;
  fsOwned: number;
  hpaOwned: number;
  noTraffic: boolean;
  stale: boolean;
  missing: string[];
}

function sumOrNull(vals: (number | null)[]): number | null {
  if (!vals.length || vals.some((v) => v == null)) return null; // a total with a missing part is not a total
  return (vals as number[]).reduce((a, b) => a + b, 0);
}

function meanOf(vals: (number | null)[]): number | null {
  const v = vals.filter((x): x is number => x != null);
  return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
}

/** Values of one service, or totals over all services (sums for replicas; mean CPU/memory). */
export function viewOf(p: TPoint, service: string): View {
  if (service !== ALL) {
    const s = p.services[service];
    if (!s) {
      return { desired: null, ready: null, fsPolicy: null, fsProposed: null, hpaProposal: null, hpaProposalKind: null, rps: null, latency: null,
        latencyP95: null, cpu: null, mem: null, owner: null, fsOwned: 0, hpaOwned: 0, noTraffic: false, stale: true, missing: ['all'] };
    }
    return { desired: s.desired, ready: s.ready, fsPolicy: s.fsPolicy, fsProposed: s.fsProposed, hpaProposal: s.hpaProposal,
      hpaProposalKind: s.hpaProposalKind, rps: s.rps, latency: s.latency, latencyP95: s.latencyP95, cpu: s.cpu, mem: s.mem,
      owner: s.owner, fsOwned: s.owner === 'flexascale' ? 1 : 0, hpaOwned: s.owner === 'hpa' ? 1 : 0, noTraffic: s.noTraffic,
      stale: s.stale, missing: s.missing };
  }
  const all = Object.values(p.services);
  const owners = new Set(all.map((s) => s.owner));
  const kinds = new Set(all.map((s) => s.hpaProposalKind));
  return {
    desired: sumOrNull(all.map((s) => s.desired)),
    ready: sumOrNull(all.map((s) => s.ready)),
    fsPolicy: sumOrNull(all.map((s) => s.fsPolicy)),
    fsProposed: null, // per-service only: FlexaScale requests apply to the services it owns
    hpaProposal: sumOrNull(all.map((s) => s.hpaProposal)),
    hpaProposalKind: kinds.size === 1 ? (all[0]?.hpaProposalKind ?? null) : kinds.has('rule_estimate') ? 'rule_estimate' : null,
    rps: null,
    latency: null,
    latencyP95: null,
    cpu: meanOf(all.map((s) => s.cpu)),
    mem: meanOf(all.map((s) => s.mem)),
    owner: owners.size === 1 ? (all[0]?.owner ?? null) : all.length ? 'mixed' : null,
    fsOwned: all.filter((s) => s.owner === 'flexascale').length,
    hpaOwned: all.filter((s) => s.owner === 'hpa').length,
    noTraffic: false,
    stale: all.some((s) => s.stale),
    missing: [],
  };
}

/* ------------------------------------------------------------------ observed scaling events */

export interface ScaleMark {
  t: number;
  service: string;
  from: number;
  to: number;
}

/** Desired-replica changes between consecutive samples: the only scaling markers the chart draws. */
export function observedScaling(points: TPoint[], service: string, interval: number): ScaleMark[] {
  const out: ScaleMark[] = [];
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1];
    const b = points[i];
    if (b.t - a.t > GAP_FACTOR * interval) continue; // across a gap the change time is unknown
    const names = service === ALL ? Object.keys(b.services) : [service];
    for (const n of names) {
      const x = a.services[n]?.desired;
      const y = b.services[n]?.desired;
      if (x != null && y != null && x !== y) out.push({ t: b.t, service: n, from: x, to: y });
    }
  }
  return out;
}

/** Ownership segments for one service (or "FlexaScale owns k of n" for all). */
export interface OwnerSeg {
  t0: number;
  t1: number;
  owner: Owner | 'mixed';
  fsShare: number;
}

export function ownerSegments(points: TPoint[], service: string, interval: number): OwnerSeg[] {
  const segs: OwnerSeg[] = [];
  for (let i = 0; i < points.length; i++) {
    const p = points[i];
    const next = points[i + 1];
    const t1 = next && next.t - p.t <= GAP_FACTOR * interval ? next.t : p.t + interval;
    const v = viewOf(p, service);
    if (!v.owner) continue;
    const n = service === ALL ? Object.keys(p.services).length : 1;
    const fsShare = n ? v.fsOwned / n : 0;
    const last = segs[segs.length - 1];
    if (last && last.owner === v.owner && Math.abs(last.fsShare - fsShare) < 1e-9 && Math.abs(last.t1 - p.t) < 1e-6) last.t1 = t1;
    else segs.push({ t0: p.t, t1, owner: v.owner, fsShare });
  }
  return segs;
}

/**
 * SLA violation periods: all services -> the end-to-end p95 above its SLO (the lab's per-sample flag);
 * one service -> its own mean latency above the service SLO. Unknown latency never counts as a violation.
 */
export function violationSpans(points: TPoint[], interval: number, service: string = ALL, sloServiceMs: number | null = null): [number, number][] {
  const spans: [number, number][] = [];
  const violated = (p: TPoint) => {
    if (service === ALL) return !!p.e2eViolation;
    const lat = p.services[service]?.latency;
    return sloServiceMs != null && lat != null && lat > sloServiceMs;
  };
  for (let i = 0; i < points.length; i++) {
    if (!violated(points[i])) continue;
    const next = points[i + 1];
    const t1 = next && next.t - points[i].t <= GAP_FACTOR * interval ? next.t : points[i].t + interval;
    const last = spans[spans.length - 1];
    if (last && Math.abs(last[1] - points[i].t) < 1e-6) last[1] = t1;
    else spans.push([points[i].t, t1]);
  }
  return spans;
}

/** Event-lane markers: traffic phase changes (spikes), applied scale requests, Auto handoffs, safety. */
export const LANE_KINDS: Record<string, { label: string; color: string; glyph: 'bolt' | 'diamond' | 'swap' | 'warn' | 'dot' }> = {
  traffic: { label: 'Workload phase', color: 'var(--s4)', glyph: 'bolt' },
  scale_request: { label: 'FlexaScale scale request', color: 'var(--flexa)', glyph: 'diamond' },
  auto: { label: 'Auto handoff', color: 'var(--auto)', glyph: 'swap' },
  safety: { label: 'Safety intervention', color: 'var(--serious)', glyph: 'warn' },
  ownership: { label: 'Ownership', color: 'var(--muted)', glyph: 'dot' },
};

export function laneEvents(events: TEvent[], service: string): TEvent[] {
  return events.filter((e) => LANE_KINDS[e.kind] && (service === ALL || !e.service || e.service === service));
}

export function fmtClock(t: number): string {
  return new Date(t * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
}

export function fmtRel(t: number, start: number | null): string {
  if (start == null) return '';
  const s = Math.round(t - start);
  const sign = s < 0 ? '−' : '+';
  const a = Math.abs(s);
  return `${sign}${Math.floor(a / 60)}:${String(a % 60).padStart(2, '0')}`;
}
