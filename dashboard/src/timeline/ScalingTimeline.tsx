import { ReactNode, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { fmt } from '../api';
import { Icon } from '../ui';
import {
  ALL, Feed, GAP_FACTOR, LANE_KINDS, TEvent, TPoint, View, fmtClock, fmtRel, laneEvents, observedScaling, ownerSegments,
  viewOf, violationSpans,
} from './data';

/*
 * Live Autoscaling Timeline.
 *
 * Synchronised panels on one time axis: replicas (desired, ready, FlexaScale and HPA proposals,
 * observed scale-ups/downs), controller ownership, traffic, latency with SLA target and violation
 * periods, and optionally CPU/memory. Live: new samples glide in from the right (a CSS transform on
 * one group, so the chart is never rebuilt or reset); Pause freezes the view while data keeps
 * arriving. Replay: a playhead walks through a saved run and the chart is labelled REPLAY.
 */

const PAD = { l: 52, r: 18 };
const LANE_H = 22;
const AXIS_H = 22;
const GAP = 16;
type Win = number | null | 'run';
const WINDOWS: { label: string; s: Win; help: string }[] = [
  { label: 'Run', s: 'run', help: 'The whole planned run: the chart fills from left to right' },
  { label: '1 min', s: 60, help: 'Last minute, sliding' }, { label: '5 min', s: 300, help: 'Last 5 minutes, sliding' },
  { label: '15 min', s: 900, help: 'Last 15 minutes, sliding' }, { label: 'All', s: null, help: 'Everything recorded' },
];
const SPEEDS = [1, 4, 16];

const C = {
  desired: 'var(--tl-desired)',
  ready: 'var(--tl-ready)',
  fs: 'var(--flexa)',
  hpa: 'var(--hpa)',
  up: 'var(--good)',
  down: 'var(--s2)',
  rps: 'var(--s1)',
  users: 'var(--muted)',
  fail: 'var(--critical)',
  p95: 'var(--s7)',
  p50: 'var(--s5)',
  svcLat: 'var(--s4)',
  cpu: 'var(--s2)',
  mem: 'var(--s3)',
  slo: 'var(--critical)',
};

type Get = (p: TPoint) => number | null;

function niceCeil(v: number, min = 1): number {
  const x = Math.max(v, min);
  const e = Math.pow(10, Math.floor(Math.log10(x)));
  for (const m of [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (m * e >= x) return m * e;
  return 10 * e;
}

function ticks(max: number, n = 4, integer = false): number[] {
  const raw = max / n;
  const e = Math.pow(10, Math.floor(Math.log10(raw || 1)));
  let step = [1, 2, 2.5, 5, 10].map((m) => m * e).find((s) => s >= raw) || raw;
  if (integer) step = Math.max(1, Math.ceil(step));
  const out: number[] = [];
  for (let v = 0; v <= max + 1e-9; v += step) out.push(+v.toFixed(6));
  return out;
}

function timeStep(windowS: number, plotW: number): number {
  const target = windowS / Math.max(3, Math.min(9, plotW / 95));
  return [5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200].find((s) => s >= target) || 7200;
}

/** Path for one series; breaks at nulls and at gaps longer than GAP_FACTOR sample intervals. */
function seriesPath(pts: TPoint[], get: Get, X: (t: number) => number, Y: (v: number) => number, interval: number, step: boolean): string {
  let d = '';
  let open = false;
  let prevT: number | null = null;
  for (const p of pts) {
    const v = get(p);
    if (prevT != null && p.t - prevT > GAP_FACTOR * interval) open = false;
    prevT = p.t;
    if (v == null) {
      open = false;
      continue;
    }
    const x = X(p.t).toFixed(1);
    const y = Y(v).toFixed(1);
    if (!open) {
      d += `M${x},${y}`;
      open = true;
    } else d += step ? `H${x}V${y}` : `L${x},${y}`;
  }
  return d;
}

/** Filled step area under a series (same gap rules). */
function areaPath(pts: TPoint[], get: Get, X: (t: number) => number, Y: (v: number) => number, base: number, interval: number): string {
  let d = '';
  let seg: [number, number][] = [];
  const flush = () => {
    if (seg.length) {
      d += `M${seg[0][0].toFixed(1)},${base}V${seg[0][1].toFixed(1)}`;
      for (let i = 1; i < seg.length; i++) d += `H${seg[i][0].toFixed(1)}V${seg[i][1].toFixed(1)}`;
      d += `V${base}Z`;
    }
    seg = [];
  };
  let prevT: number | null = null;
  for (const p of pts) {
    const v = get(p);
    if (prevT != null && p.t - prevT > GAP_FACTOR * interval) flush();
    prevT = p.t;
    if (v == null) {
      flush();
      continue;
    }
    seg.push([X(p.t), Y(v)]);
  }
  flush();
  return d;
}

function nearestIndex(pts: TPoint[], t: number): number {
  let lo = 0;
  let hi = pts.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (pts[mid].t < t) lo = mid;
    else hi = mid;
  }
  return Math.abs(pts[lo].t - t) <= Math.abs(pts[hi].t - t) ? lo : hi;
}

function Glyph({ kind, x, y, size = 6 }: { kind: string; x: number; y: number; size?: number }) {
  const k = LANE_KINDS[kind];
  const s = size;
  const fill = k?.color || 'var(--muted)';
  switch (k?.glyph) {
    case 'bolt':
      return <path d={`M${x + 1},${y - s}L${x - s * 0.6},${y + 1}H${x}L${x - 1},${y + s}L${x + s * 0.6},${y - 1}H${x}Z`} fill={fill} />;
    case 'diamond':
      return <path d={`M${x},${y - s}L${x + s},${y}L${x},${y + s}L${x - s},${y}Z`} fill={fill} />;
    case 'swap':
      return <g stroke={fill} strokeWidth={1.6} fill="none"><path d={`M${x - s},${y - 2}H${x + s}l-2.5,-2.5M${x + s},${y + 2}H${x - s}l2.5,2.5`} /></g>;
    case 'warn':
      return <path d={`M${x},${y - s}L${x + s},${y + s * 0.8}H${x - s}Z`} fill={fill} />;
    default:
      return <circle cx={x} cy={y} r={s * 0.55} fill={fill} />;
  }
}

function LegendItem({ children, label, title }: { children: ReactNode; label: string; title?: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap" title={title}>
      <svg width="22" height="10" aria-hidden>{children}</svg>
      <span>{label}</span>
    </span>
  );
}

export interface TimelineProps {
  feed: Feed | null;
  compact?: boolean;
  title?: string;
  emptyText?: string;
  /** Show the per-service small multiples (all services, same time axis). */
  strips?: boolean;
}

export function ScalingTimeline({ feed, compact = false, title = 'Live Autoscaling Timeline', emptyText, strips = !compact }: TimelineProps) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(900);
  const [service, setService] = useState<string>(ALL);
  const hasRun = feed?.start != null && !!feed?.duration;
  const [windowPick, setWindowS] = useState<Win>('run');
  const windowS: Win = windowPick === 'run' && !hasRun ? 300 : windowPick;
  const [follow, setFollow] = useState(true);
  const [manualEnd, setManualEnd] = useState<number | null>(null);
  const [showRes, setShowRes] = useState(false);
  const [hoverT, setHoverT] = useState<number | null>(null);
  const [hoverXY, setHoverXY] = useState<{ x: number; y: number } | null>(null);
  const [cursor, setCursor] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(4);
  const [showStrips, setShowStrips] = useState(strips);
  const pausedAt = useRef<number>(0);

  useLayoutEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => setWidth(Math.max(320, Math.floor(entries[0].contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const mode = feed?.mode ?? 'live';
  const replay = mode === 'replay';
  const all = feed?.points ?? [];
  const interval = feed?.interval ?? 5;
  const tFirst = all.length ? all[0].t : 0;
  const tLast = all.length ? all[all.length - 1].t : 0;
  const services = feed?.services ?? [];
  const sel = service !== ALL && !services.includes(service) && services.length ? ALL : service;

  // Replay: a recorded run opens fully drawn and paused; Play restarts it from the beginning.
  const runKey = replay ? `${feed?.label}` : 'live';
  useEffect(() => {
    if (replay) {
      setCursor(tLast || null);
      setPlaying(false);
      setFollow(true);
    } else {
      setCursor(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runKey]);

  useEffect(() => {
    if (!replay || !playing) return;
    let raf = 0;
    let prev = performance.now();
    const tick = (now: number) => {
      const dt = (now - prev) / 1000;
      prev = now;
      setCursor((c) => {
        const next = Math.min(tLast, (c ?? tFirst) + dt * speed);
        if (next >= tLast) setPlaying(false);
        return next;
      });
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [replay, playing, speed, tFirst, tLast]);

  const pts = useMemo(() => (replay && cursor != null ? all.filter((p) => p.t <= cursor + 1e-6) : all), [all, replay, cursor]);
  const head = replay ? (cursor ?? tLast) : tLast;
  const span = Math.max(60, tLast - tFirst);
  // "Run": a fixed axis over the planned load window (plus margins); slides only if the run overruns it.
  const runStart = (feed?.start ?? tFirst) - 10;
  const runEnd = (feed?.start ?? tFirst) + (feed?.duration ?? 300) + 15;
  const win = windowS === 'run' ? Math.max(runEnd, tLast + interval) - runStart : windowS ?? Math.max(60, span + interval);
  const end = windowS === 'run' ? (follow ? Math.max(runEnd, head) : (manualEnd ?? runEnd)) : follow ? Math.max(head, tFirst + Math.min(win, span)) : (manualEnd ?? head);
  const viewEnd = windowS === 'run' ? end : Math.min(Math.max(end, tFirst + 1), Math.max(tLast, tFirst + win));
  const viewStart = viewEnd - win;
  const plotW = Math.max(100, width - PAD.l - PAD.r);
  const k = plotW / win;
  const origin = tFirst;
  const tx = -(viewStart - origin) * k;
  const X = (t: number) => PAD.l + (t - origin) * k;
  const screenX = (t: number) => PAD.l + (t - viewStart) * k;

  // Glide only while following new live data with a fixed window; never when the geometry itself changed.
  const geom = `${width}|${win}|${sel}|${origin}`;
  const prevGeom = useRef(geom);
  const animate = follow && !replay && typeof windowS === 'number' && prevGeom.current === geom;
  useEffect(() => {
    prevGeom.current = geom;
  });

  if (!follow && !replay && pausedAt.current === 0) pausedAt.current = all.length;
  if (follow) pausedAt.current = 0;
  const newWhilePaused = !follow && !replay ? Math.max(0, all.length - pausedAt.current) : 0;

  // ---------------------------------------------------------------- data for the selected view
  const views = useMemo(() => {
    const m = new Map<number, View>();
    for (const p of all) m.set(p.t, viewOf(p, sel));
    return m;
  }, [all, sel]);
  const v = (p: TPoint) => views.get(p.t) as View;
  const marks = useMemo(() => observedScaling(pts, sel, interval), [pts, sel, interval]);
  const owners = useMemo(() => ownerSegments(pts, sel, interval), [pts, sel, interval]);
  const viol = useMemo(() => violationSpans(pts, interval, sel, feed?.sloServiceMs ?? null), [pts, interval, sel, feed?.sloServiceMs]);
  const lane = useMemo(() => laneEvents((feed?.events ?? []).filter((e) => !replay || cursor == null || e.t <= cursor), sel), [feed?.events, sel, replay, cursor]);
  const isSvc = sel !== ALL;
  const hasLocust = all.some((p) => p.rps != null);
  const hasFs = all.some((p) => v(p).fsPolicy != null);
  const hasHpaProp = all.some((p) => v(p).hpaProposal != null);
  const hasRuleEstimate = all.some((p) => v(p).hpaProposalKind === 'rule_estimate');

  // Y domains from the whole loaded run (stable while new points arrive).
  const repMax = useMemo(() => {
    let m = 1;
    for (const p of all) {
      const x = v(p);
      for (const val of [x.desired, x.ready, x.fsPolicy, x.hpaProposal, x.fsProposed]) if (val != null && val > m) m = val;
    }
    return Math.max(isSvc ? 3 : 4, Math.ceil(m * 1.15));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [all, sel, views]);
  const trafficMax = useMemo(() => {
    let m = 1;
    for (const p of all) for (const val of isSvc ? [v(p).rps] : [p.rps, p.failRps]) if (val != null && val > m) m = val;
    return niceCeil(m * 1.1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [all, sel, views]);
  const usersMax = useMemo(() => niceCeil(Math.max(1, ...all.map((p) => p.users ?? 0)) * 1.1), [all]);
  const sloE2e = feed?.sloE2eMs ?? null;
  const sloSvc = feed?.sloServiceMs ?? null;
  const latMax = useMemo(() => {
    let m = isSvc ? (sloSvc ?? 0) * 1.15 : (sloE2e ?? 0) * 1.15;
    for (const p of all) for (const val of isSvc ? [v(p).latency, v(p).latencyP95] : [p.p95, p.p50]) if (val != null && val > m) m = val;
    return niceCeil(Math.max(m, 10) * 1.05);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [all, sel, views, sloE2e, sloSvc]);
  const cpuT = feed?.cpuTargetPct ?? null;
  const resMax = useMemo(() => {
    let m = (cpuT ?? 0) * 1.15;
    for (const p of all) for (const val of [v(p).cpu, v(p).mem]) if (val != null && val > m) m = val;
    return niceCeil(Math.max(m, 20));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [all, sel, views, cpuT]);

  // ---------------------------------------------------------------- layout
  const H_REP = compact ? 150 : 210;
  const H_OWN = 10;
  const H_TRAF = compact ? 70 : 96;
  const H_LAT = compact ? 80 : 112;
  const H_RES = 92;
  const panels: { id: string; h: number; title: string }[] = [
    { id: 'rep', h: H_REP, title: isSvc ? `Replicas · ${sel}` : 'Replicas · all managed services (total)' },
    { id: 'own', h: H_OWN, title: '' },
    { id: 'traf', h: H_TRAF, title: isSvc ? `Requests/s · ${sel} (Prometheus)` : 'Traffic · Locust requests/s and users' },
    { id: 'lat', h: H_LAT, title: isSvc ? `Latency · ${sel} mean and p95 (Prometheus)` : 'End-to-end latency · Locust p50 / p95' },
  ];
  if (showRes) panels.push({ id: 'res', h: H_RES, title: isSvc ? `CPU % of request and memory % · ${sel}` : 'CPU % of request and memory % · mean over services' });
  const top: Record<string, number> = {};
  let y = LANE_H + 6;
  for (const p of panels) {
    top[p.id] = y + (p.title ? 14 : 2);
    y = top[p.id] + p.h + (p.id === 'rep' ? 4 : GAP);
  }
  const plotBottom = y - GAP;
  const totalH = plotBottom + AXIS_H;
  const Yr = (val: number) => top.rep + H_REP - (val / repMax) * H_REP;
  const Yt = (val: number) => top.traf + H_TRAF - (val / trafficMax) * H_TRAF;
  const Yu = (val: number) => top.traf + H_TRAF - (val / usersMax) * H_TRAF;
  const Yl = (val: number) => top.lat + H_LAT - (Math.min(val, latMax) / latMax) * H_LAT;
  const Yc = (val: number) => (top.res ?? 0) + H_RES - (Math.min(val, resMax) / resMax) * H_RES;

  // x ticks (inside the moving group, so labels glide with the data)
  const step = timeStep(win, plotW);
  const base = feed?.start ?? 0;
  const xticks: number[] = [];
  for (let t = Math.ceil((viewStart - step - base) / step) * step + base; t <= viewEnd + 2 * step; t += step) xticks.push(t);

  // ---------------------------------------------------------------- hover
  const hi = hoverT != null && pts.length ? nearestIndex(pts, hoverT) : null;
  const hp = hi != null ? pts[hi] : null;
  const hv = hp ? v(hp) : null;
  const onMove = (e: React.MouseEvent<SVGRectElement>) => {
    const r = (e.currentTarget.ownerSVGElement as SVGSVGElement).getBoundingClientRect();
    const x = e.clientX - r.left;
    setHoverT(viewStart + (x - PAD.l) / k);
    setHoverXY({ x, y: e.clientY - r.top });
  };
  const leave = () => {
    setHoverT(null);
    setHoverXY(null);
  };

  const badge = replay
    ? { text: 'REPLAY', color: 'var(--warning)', help: 'Recorded data of a saved run, not live' }
    : !follow
      ? { text: 'PAUSED', color: 'var(--muted)', help: 'View frozen; live data keeps arriving' }
      : { text: 'LIVE', color: 'var(--good)', help: mode === 'live-history' ? 'Cluster telemetry recorded while the dashboard polls' : 'Experiment samples every 5 s' };

  const lastP = all[all.length - 1];
  const lastV = lastP ? v(lastP) : null;

  // ---------------------------------------------------------------- render
  if (!feed || !all.length) {
    return (
      <section className="card p-5 fade-in" ref={wrapRef}>
        <TimelineHeader title={title} badge={badge} />
        <div className="flex flex-col items-center justify-center text-center gap-2 muted text-sm" style={{ minHeight: compact ? 160 : 260 }}>
          <Icon name="live" size={22} />
          <div className="max-w-md">{emptyText || 'Waiting for the first samples. The timeline draws only recorded Kubernetes state and telemetry.'}</div>
        </div>
      </section>
    );
  }

  const lineProps = { fill: 'none', strokeLinejoin: 'round' as const, strokeLinecap: 'round' as const };
  const dense = (win / interval) * 7 > plotW; // proposal markers only when they do not overlap

  return (
    <section className="card p-4 sm:p-5 fade-in min-w-0" aria-label={title}>
      <TimelineHeader title={title} badge={badge} sub={feed.label}>
        <select className="field !w-auto !py-1 text-sm" value={sel} onChange={(e) => setService(e.target.value)} aria-label="Service">
          <option value={ALL}>All services (total)</option>
          {services.map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
        <div className="seg" role="group" aria-label="Time window">
          {WINDOWS.filter((w) => w.s !== 'run' || hasRun).map((w) => (
            <button key={w.label} aria-pressed={windowS === w.s} title={w.help} onClick={() => { setWindowS(w.s); setFollow(true); }}>{w.label}</button>
          ))}
        </div>
        <button className="btn btn-ghost !px-2.5 !py-1.5 text-xs" aria-pressed={showRes} onClick={() => setShowRes((s) => !s)} title="CPU and memory panel">
          CPU / mem
        </button>
        {replay ? (
          <div className="flex items-center gap-1.5">
            <button className="btn !px-2.5 !py-1.5 text-xs" onClick={() => {
              if ((cursor ?? tLast) >= tLast) setCursor(tFirst);
              setFollow(true);
              setPlaying((p) => !p);
            }} aria-label={playing ? 'Pause replay' : 'Play replay'}>
              <Icon name={playing ? 'stop' : 'play'} size={12} />{playing ? 'Pause' : 'Play'}
            </button>
            <div className="seg" role="group" aria-label="Replay speed">
              {SPEEDS.map((s) => <button key={s} aria-pressed={speed === s} onClick={() => setSpeed(s)}>{s}×</button>)}
            </div>
          </div>
        ) : (
          <button className="btn !px-2.5 !py-1.5 text-xs" onClick={() => {
            if (follow) {
              setManualEnd(viewEnd);
              setFollow(false);
            } else setFollow(true);
          }} aria-label={follow ? 'Pause the timeline' : 'Resume live'}>
            <Icon name={follow ? 'stop' : 'play'} size={12} />{follow ? 'Pause' : newWhilePaused ? `Live (+${newWhilePaused})` : 'Live'}
          </button>
        )}
      </TimelineHeader>

      <div ref={wrapRef} className="relative select-none" onMouseLeave={leave}>
        <svg width={width} height={totalH} role="img" aria-label={`${title}: ${isSvc ? sel : 'all services'}, ${pts.length} samples`}>
          <defs>
            <clipPath id="tl-clip"><rect x={PAD.l} y={0} width={plotW} height={totalH} /></clipPath>
            <pattern id="tl-viol" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <rect width="6" height="6" fill="var(--critical)" opacity="0.08" />
              <line x1="0" y1="0" x2="0" y2="6" stroke="var(--critical)" strokeWidth="1.4" opacity="0.28" />
            </pattern>
          </defs>

          {/* panel frames, titles and static y axes */}
          {panels.map((p) => (
            <g key={p.id}>
              {p.title && <text x={PAD.l} y={top[p.id] - 4} className="tl-title">{p.title}</text>}
              {p.id !== 'own' && <rect x={PAD.l} y={top[p.id]} width={plotW} height={p.h} fill="var(--tl-panel)" rx={6} />}
            </g>
          ))}
          {ticks(repMax, compact ? 3 : 5, true).map((t) => (
            <g key={`r${t}`}>
              <line x1={PAD.l} x2={PAD.l + plotW} y1={Yr(t)} y2={Yr(t)} stroke="var(--grid)" strokeDasharray={t ? '2 4' : undefined} />
              <text x={PAD.l - 8} y={Yr(t) + 3.5} textAnchor="end" className="tl-axis">{t}</text>
            </g>
          ))}
          {ticks(trafficMax, 2).map((t) => (
            <g key={`t${t}`}>
              <line x1={PAD.l} x2={PAD.l + plotW} y1={Yt(t)} y2={Yt(t)} stroke="var(--grid)" strokeDasharray={t ? '2 4' : undefined} />
              <text x={PAD.l - 8} y={Yt(t) + 3.5} textAnchor="end" className="tl-axis">{fmt(t, t < 10 && t % 1 ? 1 : 0)}</text>
            </g>
          ))}
          {ticks(latMax, 2).map((t) => (
            <g key={`l${t}`}>
              <line x1={PAD.l} x2={PAD.l + plotW} y1={Yl(t)} y2={Yl(t)} stroke="var(--grid)" strokeDasharray={t ? '2 4' : undefined} />
              <text x={PAD.l - 8} y={Yl(t) + 3.5} textAnchor="end" className="tl-axis">{t >= 1000 ? `${fmt(t / 1000, 1)}s` : fmt(t)}</text>
            </g>
          ))}
          {showRes && ticks(resMax, 2).map((t) => (
            <g key={`c${t}`}>
              <line x1={PAD.l} x2={PAD.l + plotW} y1={Yc(t)} y2={Yc(t)} stroke="var(--grid)" strokeDasharray={t ? '2 4' : undefined} />
              <text x={PAD.l - 8} y={Yc(t) + 3.5} textAnchor="end" className="tl-axis">{fmt(t)}%</text>
            </g>
          ))}
          <text x={PAD.l - 8} y={top.own + 8} textAnchor="end" className="tl-axis">owner</text>
          <text x={PAD.l - 8} y={LANE_H / 2 + 4} textAnchor="end" className="tl-axis">events</text>

          {/* moving content */}
          <g clipPath="url(#tl-clip)">
            <g style={{ transform: `translateX(${tx}px)`, transition: animate ? `transform ${Math.min(1.2, interval * 0.8)}s linear` : 'none' }}>
              {/* SLA violation periods */}
              {viol.map(([a, b], i) => (
                <g key={`v${i}`}>
                  <rect x={X(a)} y={top.lat} width={Math.max(1, X(b) - X(a))} height={H_LAT} fill="url(#tl-viol)" />
                  <rect x={X(a)} y={LANE_H - 3} width={Math.max(1, X(b) - X(a))} height={3} fill="var(--critical)" opacity={0.7} />
                </g>
              ))}
              {/* ownership strip */}
              {owners.map((s, i) => {
                const w = Math.max(0.5, X(s.t1) - X(s.t0));
                if (s.owner === 'mixed' || (!isSvc && s.owner !== 'reset' && s.owner !== 'none')) {
                  return (
                    <g key={`o${i}`}>
                      <rect x={X(s.t0)} y={top.own} width={w} height={H_OWN} fill={C.hpa} opacity={0.55} />
                      <rect x={X(s.t0)} y={top.own} width={w} height={H_OWN * s.fsShare} fill={C.fs} />
                    </g>
                  );
                }
                const col = s.owner === 'flexascale' ? C.fs : s.owner === 'hpa' ? C.hpa : 'var(--surface-3)';
                return <rect key={`o${i}`} x={X(s.t0)} y={top.own} width={w} height={H_OWN} fill={col} opacity={s.owner === 'hpa' ? 0.75 : 1} />;
              })}

              {/* replicas */}
              <path d={areaPath(pts, (p) => v(p).ready, X, Yr, top.rep + H_REP, interval)} fill={C.ready} opacity={0.16} />
              <path d={seriesPath(pts, (p) => v(p).ready, X, Yr, interval, true)} stroke={C.ready} strokeWidth={1.6} {...lineProps} />
              <path d={seriesPath(pts, (p) => v(p).desired, X, Yr, interval, true)} stroke={C.desired} strokeWidth={2.4} {...lineProps} />
              {hasHpaProp && <path d={seriesPath(pts, (p) => v(p).hpaProposal, X, Yr, interval, true)} stroke={C.hpa} strokeWidth={1.6} strokeDasharray="1.5 3.5" {...lineProps} />}
              {hasFs && <path d={seriesPath(pts, (p) => v(p).fsPolicy, X, Yr, interval, true)} stroke={C.fs} strokeWidth={1.8} strokeDasharray="6 4" {...lineProps} />}
              {hasFs && !dense && pts.map((p) => {
                const val = v(p).fsPolicy;
                return val == null ? null : <circle key={`f${p.t}`} cx={X(p.t)} cy={Yr(val)} r={2.6} fill="var(--surface)" stroke={C.fs} strokeWidth={1.4} />;
              })}
              {isSvc && pts.map((p) => {
                const val = v(p).fsProposed;
                return val == null || !p.services[sel]?.fsApplied ? null
                  : <circle key={`a${p.t}`} cx={X(p.t)} cy={Yr(val)} r={3.4} fill={C.fs} />;
              })}
              {/* observed scale-ups / scale-downs (only where two consecutive samples differ) */}
              {marks.map((m, i) => {
                const yv = isSvc ? m.to : (v(pts.find((p) => p.t === m.t) as TPoint).desired ?? m.to);
                const up = m.to > m.from;
                const cx = X(m.t);
                const cy = Yr(yv) + (up ? -9 : 9);
                return (
                  <path key={`m${i}`} d={up ? `M${cx},${cy - 4}l4.5,7h-9z` : `M${cx},${cy + 4}l4.5,-7h-9z`} fill={up ? C.up : C.down} stroke="var(--surface)" strokeWidth={0.8}>
                    <title>{`${m.service}: ${m.from} → ${m.to} desired replicas (observed)`}</title>
                  </path>
                );
              })}

              {/* traffic */}
              {isSvc ? (
                <path d={seriesPath(pts, (p) => v(p).rps, X, Yt, interval, false)} stroke={C.rps} strokeWidth={1.8} {...lineProps} />
              ) : (
                <>
                  <path d={areaPath(pts, (p) => p.rps, X, Yt, top.traf + H_TRAF, interval)} fill={C.rps} opacity={0.14} />
                  <path d={seriesPath(pts, (p) => p.users, X, Yu, interval, true)} stroke={C.users} strokeWidth={1.2} strokeDasharray="3 3" {...lineProps} />
                  <path d={seriesPath(pts, (p) => p.rps, X, Yt, interval, false)} stroke={C.rps} strokeWidth={1.8} {...lineProps} />
                  <path d={seriesPath(pts, (p) => p.failRps, X, Yt, interval, false)} stroke={C.fail} strokeWidth={1.4} {...lineProps} />
                </>
              )}

              {/* latency */}
              {isSvc ? (
                <>
                  <path d={seriesPath(pts, (p) => v(p).latencyP95, X, Yl, interval, false)} stroke={C.p95} strokeWidth={1.4} opacity={0.85} {...lineProps} />
                  <path d={seriesPath(pts, (p) => v(p).latency, X, Yl, interval, false)} stroke={C.svcLat} strokeWidth={1.9} {...lineProps} />
                </>
              ) : (
                <>
                  <path d={seriesPath(pts, (p) => p.p50, X, Yl, interval, false)} stroke={C.p50} strokeWidth={1.4} {...lineProps} />
                  <path d={seriesPath(pts, (p) => p.p95, X, Yl, interval, false)} stroke={C.p95} strokeWidth={1.9} {...lineProps} />
                </>
              )}

              {/* resources */}
              {showRes && (
                <>
                  <path d={seriesPath(pts, (p) => v(p).cpu, X, Yc, interval, false)} stroke={C.cpu} strokeWidth={1.8} {...lineProps} />
                  <path d={seriesPath(pts, (p) => v(p).mem, X, Yc, interval, false)} stroke={C.mem} strokeWidth={1.5} {...lineProps} />
                </>
              )}

              {/* live leading edge */}
              {!replay && follow && lastV?.desired != null && (
                <circle cx={X(tLast)} cy={Yr(lastV.desired)} r={4} fill="var(--tl-desired)" className="tl-edge" />
              )}

              {/* event lane */}
              {lane.map((e, i) => <g key={`e${i}`}><Glyph kind={e.kind} x={X(e.t)} y={LANE_H / 2} /><title>{e.message}</title></g>)}

              {/* x axis */}
              {xticks.map((t) => (
                <g key={`x${t}`}>
                  <line x1={X(t)} x2={X(t)} y1={plotBottom} y2={plotBottom + 4} stroke="var(--axis)" />
                  <text x={X(t)} y={plotBottom + 15} textAnchor="middle" className="tl-axis">{feed.start != null ? fmtRel(t, feed.start) : fmtClock(t).slice(0, step >= 60 ? 5 : 8)}</text>
                </g>
              ))}
            </g>
          </g>

          {/* fixed overlays: SLA lines and targets */}
          {!isSvc && sloE2e != null && hasLocust && (
            <g>
              <line x1={PAD.l} x2={PAD.l + plotW} y1={Yl(sloE2e)} y2={Yl(sloE2e)} stroke={C.slo} strokeDasharray="5 4" strokeWidth={1.2} />
              <text x={PAD.l + plotW - 4} y={Yl(sloE2e) - 4} textAnchor="end" className="tl-axis" style={{ fill: 'var(--critical)' }}>SLA p95 {fmt(sloE2e)} ms</text>
            </g>
          )}
          {isSvc && sloSvc != null && (
            <g>
              <line x1={PAD.l} x2={PAD.l + plotW} y1={Yl(sloSvc)} y2={Yl(sloSvc)} stroke={C.slo} strokeDasharray="5 4" strokeWidth={1.2} />
              <text x={PAD.l + plotW - 4} y={Yl(sloSvc) - 4} textAnchor="end" className="tl-axis" style={{ fill: 'var(--critical)' }}>service SLO mean {fmt(sloSvc)} ms</text>
            </g>
          )}
          {showRes && cpuT != null && (
            <g>
              <line x1={PAD.l} x2={PAD.l + plotW} y1={Yc(cpuT)} y2={Yc(cpuT)} stroke={C.cpu} strokeDasharray="5 4" strokeWidth={1} opacity={0.8} />
              <text x={PAD.l + plotW - 4} y={Yc(cpuT) - 4} textAnchor="end" className="tl-axis">HPA CPU target {fmt(cpuT)}%</text>
            </g>
          )}
          {!hasLocust && !isSvc && (
            <text x={PAD.l + plotW / 2} y={top.traf + H_TRAF / 2 + 4} textAnchor="middle" className="tl-axis">
              No Locust workload in this feed: select a service for its Prometheus request rate and latency
            </text>
          )}
          {replay && cursor != null && cursor < tLast && (
            <line x1={screenX(cursor)} x2={screenX(cursor)} y1={4} y2={plotBottom} stroke="var(--warning)" strokeWidth={1.2} />
          )}

          {/* crosshair */}
          {hp && (
            <line x1={screenX(hp.t)} x2={screenX(hp.t)} y1={2} y2={plotBottom} stroke="var(--ink-2)" strokeWidth={1} opacity={0.6} />
          )}
          <rect x={PAD.l} y={0} width={plotW} height={plotBottom} fill="transparent" onMouseMove={onMove} onMouseLeave={leave} style={{ cursor: 'crosshair' }} />
        </svg>

        {hp && hv && hoverXY && (
          <Tooltip x={hoverXY.x} y={hoverXY.y} width={width} p={hp} v={hv} sel={sel} start={feed.start}
            events={(feed.events || []).filter((e) => Math.abs(e.t - hp.t) <= interval * 0.6 && (sel === ALL || !e.service || e.service === sel))}
            marks={marks.filter((m) => m.t === hp.t)} />
        )}
      </div>

      {/* overview / brush */}
      {!compact && tLast - tFirst > win * 1.02 && (
        <Brush points={all} sel={sel} views={views} width={width} viewStart={viewStart} viewEnd={viewEnd} tFirst={tFirst} tLast={tLast} interval={interval}
          onMove={(e) => { setManualEnd(e); setFollow(false); if (replay) setPlaying(false); }} />
      )}
      {replay && (
        <div className="flex items-center gap-3 mt-2 text-xs">
          <span className="muted tnum w-16">{fmtRel(cursor ?? tFirst, feed.start)}</span>
          <input type="range" className="flex-1 accent-[var(--warning)]" min={tFirst} max={tLast} step={interval / 5} value={cursor ?? tLast}
            onChange={(e) => { setCursor(Number(e.target.value)); setFollow(true); }} aria-label="Replay position" />
          <span className="muted tnum w-16 text-right">{fmtRel(tLast, feed.start)}</span>
        </div>
      )}

      <div className="flex flex-wrap gap-x-4 gap-y-1.5 mt-3 text-xs ink2">
        <LegendItem label="Desired (spec.replicas)"><line x1="1" x2="21" y1="5" y2="5" stroke={C.desired} strokeWidth="2.4" /></LegendItem>
        <LegendItem label="Ready (status.readyReplicas)"><rect x="1" y="2" width="20" height="7" fill={C.ready} opacity="0.25" /><line x1="1" x2="21" y1="2" y2="2" stroke={C.ready} strokeWidth="1.6" /></LegendItem>
        <LegendItem label="FlexaScale proposal (policy, not an action)" title="The policy's proposal before safety guards; a filled dot marks a scale request FlexaScale actually sent">
          <line x1="1" x2="21" y1="5" y2="5" stroke={C.fs} strokeWidth="1.8" strokeDasharray="6 4" /><circle cx="11" cy="5" r="2.6" fill="var(--surface)" stroke={C.fs} strokeWidth="1.4" />
        </LegendItem>
        <LegendItem label={hasRuleEstimate ? 'HPA proposal (status, or rule estimate while frozen)' : 'HPA proposal (status.desiredReplicas)'}
          title="While HPA owns a service: its own status.desiredReplicas. While FlexaScale owns it: the HPA rule ceil(n·cpu/target) on the same telemetry, an estimate">
          <line x1="1" x2="21" y1="5" y2="5" stroke={C.hpa} strokeWidth="1.6" strokeDasharray="1.5 3.5" />
        </LegendItem>
        <LegendItem label="Scale-up / down (observed)"><path d="M6,1l4.5,7h-9z" fill={C.up} /><path d="M16,9l4.5,-7h-9z" fill={C.down} /></LegendItem>
        <LegendItem label="Owner: HPA / FlexaScale"><rect x="1" y="2" width="10" height="7" fill={C.hpa} opacity="0.75" /><rect x="11" y="2" width="10" height="7" fill={C.fs} /></LegendItem>
        <LegendItem label={isSvc ? 'Service SLO violated (mean latency)' : 'End-to-end SLA violated (p95)'}><rect x="1" y="1" width="20" height="8" fill="url(#tl-viol)" stroke="var(--critical)" strokeOpacity="0.4" /></LegendItem>
        {Object.entries(LANE_KINDS).filter(([k]) => k !== 'ownership').map(([k, d]) => (
          <LegendItem key={k} label={d.label}><Glyph kind={k} x={11} y={5} size={4.5} /></LegendItem>
        ))}
        <span className="muted">Gaps = no telemetry recorded. Nothing between samples is interpolated.</span>
      </div>

      {showStrips && services.length > 1 && (
        <ServiceStrips points={pts} all={all} services={services} width={width} X={X} tx={tx} animate={animate} interval={interval}
          plotW={plotW} selected={sel} onSelect={(n) => setService(n === sel ? ALL : n)} />
      )}
      {strips && services.length > 1 && (
        <button className="btn btn-ghost text-xs mt-2 !px-2 !py-1" onClick={() => setShowStrips((s) => !s)}>
          {showStrips ? 'Hide per-service replicas' : `Show per-service replicas (${services.length} services)`}
        </button>
      )}
      {lastV && !replay && (
        <div className="sr-only" aria-live="polite">{`${isSvc ? sel : 'Total'}: ${lastV.ready ?? 'unknown'} of ${lastV.desired ?? 'unknown'} replicas ready`}</div>
      )}
    </section>
  );
}

function TimelineHeader({ title, badge, sub, children }: { title: string; badge: { text: string; color: string; help: string }; sub?: string; children?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-start justify-between gap-3 mb-3">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <h2 className="font-semibold text-[15px] leading-snug">{title}</h2>
          <span className="tl-badge" style={{ color: badge.color, borderColor: badge.color }} title={badge.help}>
            {badge.text === 'LIVE' && <span className="dot dot-live" style={{ background: badge.color, color: badge.color, width: 6, height: 6 }} />}
            {badge.text}
          </span>
        </div>
        {sub && <div className="text-xs muted truncate mt-0.5" title={sub}>{sub}</div>}
      </div>
      {children && <div className="flex items-center gap-2 flex-wrap">{children}</div>}
    </header>
  );
}

function valueOrState(val: number | null, digits: number, unit: string, opts: { missing?: boolean; noTraffic?: boolean; stale?: boolean }) {
  if (val != null) return <span className="tnum">{fmt(val, digits)}{unit}{opts.stale ? <span className="muted"> (stale)</span> : null}</span>;
  if (opts.noTraffic) return <span className="muted">no requests</span>;
  return <span className="muted">{opts.missing ? 'missing' : '—'}</span>;
}

function Tooltip({ x, y, width, p, v, sel, start, events, marks }: {
  x: number; y: number; width: number; p: TPoint; v: View; sel: string; start: number | null; events: TEvent[]; marks: { service: string; from: number; to: number }[];
}) {
  const left = x > width - 300 ? x - 292 : x + 14;
  const isSvc = sel !== ALL;
  const miss = (f: string) => v.missing.includes(f) || v.missing.includes('all');
  const rows: [string, ReactNode, string?][] = [
    ['Desired', v.desired ?? <span className="muted">—</span>, 'var(--tl-desired)'],
    ['Ready', v.ready ?? <span className="muted">—</span>, 'var(--tl-ready)'],
    ['FlexaScale proposal', v.fsPolicy ?? <span className="muted">none</span>, 'var(--flexa)'],
    ...(isSvc ? [['FlexaScale requested', v.fsProposed ?? <span className="muted">—</span>, 'var(--flexa)'] as [string, ReactNode, string]] : []),
    [v.hpaProposalKind === 'rule_estimate' ? 'HPA rule (estimate)' : 'HPA proposal', v.hpaProposal ?? <span className="muted">—</span>, 'var(--hpa)'],
    ['Owner', v.owner === 'mixed' ? `FlexaScale ${v.fsOwned}, HPA ${v.hpaOwned}` : v.owner === 'flexascale' ? 'FlexaScale' : v.owner === 'hpa' ? 'Native HPA' : v.owner === 'reset' ? 'Reset hold' : v.owner ?? '—'],
  ];
  if (isSvc) {
    rows.push(['Requests/s', valueOrState(v.rps, 2, '', { missing: miss('request_rate'), noTraffic: v.noTraffic, stale: v.stale })]);
    rows.push(['Latency mean / p95', <span key="l">{valueOrState(v.latency, 1, ' ms', { missing: miss('latency'), noTraffic: v.noTraffic })} / {v.latencyP95Capped ? '≥ ' : ''}{valueOrState(v.latencyP95, 0, ' ms', { noTraffic: v.noTraffic })}</span>]);
    rows.push(['CPU / memory', <span key="c">{valueOrState(v.cpu, 0, '%', { missing: miss('cpu'), stale: v.stale })} / {valueOrState(v.mem, 0, '%', { missing: miss('memory') })}</span>]);
  } else {
    rows.push(['Users / req/s', p.users != null || p.rps != null ? <span className="tnum">{fmt(p.users)} / {fmt(p.rps, 1)}</span> : <span className="muted">no workload</span>]);
    rows.push(['p50 / p90 / p95 / p99', p.p95 != null ? <span className="tnum">{fmt(p.p50)} / {fmt(p.p90)} / {fmt(p.p95)} / {fmt(p.p99)} ms{p.e2eViolation ? <b style={{ color: 'var(--critical)' }}> SLA violated</b> : null}</span> : <span className="muted">—</span>]);
    rows.push(['Mean CPU / memory', <span key="c">{valueOrState(v.cpu, 0, '%', {})} / {valueOrState(v.mem, 0, '%', {})}</span>]);
  }
  return (
    <div className="tl-tip" style={{ left, top: Math.max(4, y - 30) }} role="tooltip">
      <div className="flex items-baseline justify-between gap-3 mb-1.5">
        <b className="tnum">{fmtClock(p.t)}</b>
        <span className="muted tnum">{start != null ? fmtRel(p.t, start) : ''}</span>
      </div>
      <table className="w-full text-xs">
        <tbody>
          {rows.map(([k, val, col]) => (
            <tr key={k}>
              <td className="pr-3 py-[1px] muted whitespace-nowrap">{col && <span className="inline-block w-2 h-2 rounded-full mr-1.5 align-middle" style={{ background: col }} />}{k}</td>
              <td className="py-[1px] text-right whitespace-nowrap">{val}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {marks.length > 0 && (
        <div className="mt-1.5 pt-1.5 border-t text-xs" style={{ borderColor: 'var(--border)' }}>
          {marks.slice(0, 6).map((m) => <div key={m.service}><span style={{ color: m.to > m.from ? 'var(--good)' : 'var(--s2)' }}>{m.to > m.from ? '▲' : '▼'}</span> {m.service} {m.from} → {m.to}</div>)}
          {marks.length > 6 && <div className="muted">+{marks.length - 6} more</div>}
        </div>
      )}
      {events.length > 0 && (
        <div className="mt-1.5 pt-1.5 border-t text-xs space-y-0.5" style={{ borderColor: 'var(--border)' }}>
          {events.slice(0, 4).map((e, i) => <div key={i} className="ink2 leading-snug">{e.message}</div>)}
          {events.length > 4 && <div className="muted">+{events.length - 4} more events</div>}
        </div>
      )}
    </div>
  );
}

function Brush({ points, sel, views, width, viewStart, viewEnd, tFirst, tLast, interval, onMove }: {
  points: TPoint[]; sel: string; views: Map<number, View>; width: number; viewStart: number; viewEnd: number; tFirst: number; tLast: number; interval: number; onMove: (end: number) => void;
}) {
  const h = 34;
  const plotW = Math.max(100, width - PAD.l - PAD.r);
  const span = Math.max(1, tLast - tFirst);
  const X = (t: number) => PAD.l + ((t - tFirst) / span) * plotW;
  let m = 1;
  for (const p of points) m = Math.max(m, views.get(p.t)?.desired ?? 0);
  const Y = (val: number) => h - 3 - (val / m) * (h - 8);
  const drag = useRef<{ dx: number } | null>(null);
  const toT = (clientX: number, el: SVGSVGElement) => tFirst + ((clientX - el.getBoundingClientRect().left - PAD.l) / plotW) * span;
  const win = viewEnd - viewStart;
  return (
    <svg width={width} height={h} className="mt-1" aria-label="Timeline overview: drag the window to inspect history"
      onMouseDown={(e) => {
        const t = toT(e.clientX, e.currentTarget);
        if (t >= viewStart && t <= viewEnd) drag.current = { dx: viewEnd - t };
        else onMove(Math.min(tLast, Math.max(tFirst + win, t + win / 2)));
      }}
      onMouseMove={(e) => drag.current && onMove(Math.min(tLast, Math.max(tFirst + win, toT(e.clientX, e.currentTarget) + drag.current.dx)))}
      onMouseUp={() => (drag.current = null)} onMouseLeave={() => (drag.current = null)}>
      <rect x={PAD.l} y={1} width={plotW} height={h - 2} rx={5} fill="var(--tl-panel)" />
      <path d={seriesPath(points, (p) => views.get(p.t)?.desired ?? null, X, Y, interval, true)} stroke="var(--tl-desired)" strokeWidth={1.2} fill="none" opacity={0.7} />
      <rect x={X(Math.max(tFirst, viewStart))} y={1} width={Math.max(6, X(Math.min(tLast, viewEnd)) - X(Math.max(tFirst, viewStart)))} height={h - 2} rx={5}
        fill="var(--accent-soft)" stroke="var(--accent)" strokeWidth={1.2} style={{ cursor: 'grab' }} />
      <text x={PAD.l - 8} y={h / 2 + 4} textAnchor="end" className="tl-axis">{sel === ALL ? 'all' : 'svc'}</text>
    </svg>
  );
}

function ServiceStrips({ points, all, services, width, X, tx, animate, interval, plotW, selected, onSelect }: {
  points: TPoint[]; all: TPoint[]; services: string[]; width: number; X: (t: number) => number; tx: number; animate: boolean; interval: number;
  plotW: number; selected: string; onSelect: (n: string) => void;
}) {
  const rowH = 24;
  const h = services.length * rowH + 4;
  const maxBy = useMemo(() => {
    const m: Record<string, number> = {};
    for (const n of services) {
      let x = 1;
      for (const p of all) x = Math.max(x, p.services[n]?.desired ?? 0, p.services[n]?.ready ?? 0);
      m[n] = x;
    }
    return m;
  }, [all, services]);
  const last = points[points.length - 1];
  return (
    <div className="mt-4">
      <div className="eyebrow mb-1.5">Per-service replicas · same time axis · click a service to focus</div>
      <div className="max-h-[420px] overflow-y-auto scroll-thin">
        <svg width={width} height={h} aria-label="Replicas of every service over time">
          <defs><clipPath id="tl-strip-clip"><rect x={PAD.l + 92} y={0} width={plotW - 92} height={h} /></clipPath></defs>
          {services.map((n, i) => {
            const y0 = i * rowH + 2;
            const s = last?.services[n];
            const owner = s?.owner;
            return (
              <g key={n} onClick={() => onSelect(n)} style={{ cursor: 'pointer' }}>
                <rect x={0} y={y0} width={width} height={rowH - 2} rx={4} fill={selected === n ? 'var(--accent-soft)' : i % 2 ? 'transparent' : 'var(--tl-panel)'} />
                <circle cx={8} cy={y0 + rowH / 2 - 1} r={3.5} fill={owner === 'flexascale' ? 'var(--flexa)' : owner === 'hpa' ? 'var(--hpa)' : 'var(--muted)'} />
                <text x={16} y={y0 + rowH / 2 + 3} className="tl-strip-label">{n.replace(/-service$/, '')}</text>
                <text x={PAD.l + 86} y={y0 + rowH / 2 + 3} textAnchor="end" className="tl-axis tnum">{s ? `${s.ready ?? '—'}/${s.desired ?? '—'}` : '—'}</text>
              </g>
            );
          })}
          <g clipPath="url(#tl-strip-clip)" style={{ pointerEvents: 'none' }}>
            <g style={{ transform: `translateX(${tx}px)`, transition: animate ? `transform ${Math.min(1.2, interval * 0.8)}s linear` : 'none' }}>
              {services.map((n, i) => {
                const y0 = i * rowH + 2;
                const Y = (val: number) => y0 + rowH - 5 - (val / maxBy[n]) * (rowH - 9);
                return (
                  <g key={n}>
                    <path d={areaPath(points, (p) => p.services[n]?.ready ?? null, X, Y, y0 + rowH - 5, interval)} fill="var(--tl-ready)" opacity={0.2} />
                    <path d={seriesPath(points, (p) => p.services[n]?.desired ?? null, X, Y, interval, true)} stroke="var(--tl-desired)" strokeWidth={1.4} fill="none" />
                    {observedScaling(points, n, interval).map((m, j) => (
                      <circle key={j} cx={X(m.t)} cy={Y(m.to)} r={2.2} fill={m.to > m.from ? 'var(--good)' : 'var(--s2)'} />
                    ))}
                  </g>
                );
              })}
            </g>
          </g>
        </svg>
      </div>
    </div>
  );
}
