import { ReactNode, useMemo, useState } from 'react';
import { CONTROLLER_LABEL, Json, deltaDigits, isNativeHpa, OWNER_COLOR, fmt, fmtAgo, fmtElapsed, fmtMoney, fmtSigned } from '../api';
import { Card, Empty, ErrorNote, Icon, Level, Meter, OwnerBadge, Skeleton, Sparkline, Stat, StatusBadge, useHistory } from '../ui';
import { Topology } from '../Topology';
import { ScalingTimeline } from '../timeline/ScalingTimeline';
import { feedOfRun, useLiveHistory } from '../timeline/feeds';

/** Fewer paired runs than this: no verdict, the result is shown as preliminary. */
export const MIN_PAIRS = 6;

export interface Alert {
  level: Level;
  title: string;
  detail: string;
}

/** Cost rate of what is allocated right now: ready replicas x requests x configured prices (an estimate, not a bill). */
export function costRate(services: Json[], cost: Json): { value: number | null; priced: boolean; vcpu: number; gib: number; currency: string } {
  let vcpu = 0;
  let gib = 0;
  for (const s of services) {
    vcpu += (s.ready_replicas || 0) * (s.cpu_request_cores || 0);
    gib += (s.ready_replicas || 0) * ((s.memory_request_bytes || 0) / 2 ** 30);
  }
  const priced = cost?.cpu_per_vcpu_hour != null && cost?.memory_per_gib_hour != null;
  const value = priced ? vcpu * cost.cpu_per_vcpu_hour + gib * cost.memory_per_gib_hour : vcpu + (cost?.memory_weight ?? 0.125) * gib;
  return { value: services.length ? value : null, priced, vcpu, gib, currency: cost?.currency || 'USD' };
}

/** Alerts derived only from observed state; nothing here is simulated. */
export function deriveAlerts(overview: Json, live: Json, active: Json): Alert[] {
  const out: Alert[] = [];
  const c = overview?.cluster;
  if (c && !c.kubectl) out.push({ level: 'critical', title: 'Kubernetes API unreachable', detail: c.error || 'kubectl failed' });
  if (c && c.nodes_total && c.nodes_ready < c.nodes_total) out.push({ level: 'critical', title: 'Node not ready', detail: `${c.nodes_ready}/${c.nodes_total} nodes ready` });
  if (c && !c.prometheus) out.push({ level: 'critical', title: 'Prometheus unreachable', detail: `${c.prometheus_url}: FlexaScale holds every service (no telemetry)` });
  const services: Json[] = (live?.services || []).filter((s: Json) => s.eligible);
  const slo = live?.policy?.slo_latency_ms;
  const running = active && !['completed', 'stopped', 'failed', 'interrupted'].includes(active.state);
  for (const s of services) {
    const m = s.metrics || {};
    if (s.ready_replicas < s.desired_replicas) out.push({ level: 'warning', title: `${s.name}: replicas starting`, detail: `${s.ready_replicas}/${s.desired_replicas} ready` });
    if (slo && m.latency_mean_ms != null && m.latency_mean_ms > slo) out.push({ level: 'critical', title: `${s.name}: latency above SLO`, detail: `${fmt(m.latency_mean_ms)} ms mean > ${slo} ms` });
    else if (m.cpu_pct != null && m.cpu_pct >= 85) out.push({ level: 'serious', title: `${s.name}: CPU pressure`, detail: `${fmt(m.cpu_pct)}% of request (scale-down blocked ≥ 85%)` });
    if (m.error_rate != null && m.request_rate && m.error_rate / m.request_rate > 0.05)
      out.push({ level: 'serious', title: `${s.name}: 5xx errors`, detail: `${fmt((100 * m.error_rate) / m.request_rate, 1)}% of requests` });
    if (s.hpa?.frozen_by && !running) out.push({ level: 'critical', title: `${s.name}: HPA left frozen`, detail: `frozen by ${s.hpa.frozen_by} with no experiment running; run ./scripts/stop_review.sh` });
  }
  const noCpu = services.filter((s) => s.metrics?.cpu_pct == null);
  if (services.length && noCpu.length === services.length)
    out.push({ level: 'critical', title: 'No CPU telemetry for any service', detail: live?.prometheus_error || 'Prometheus returns no recent cAdvisor samples (check the port-forward, scrape targets and the host clock)' });
  else if (noCpu.length)
    out.push({ level: 'warning', title: `CPU telemetry missing for ${noCpu.length} service(s)`, detail: noCpu.map((s) => s.name).join(', ') + ' (FlexaScale holds these services)' });
  const lease = live?.lease;
  if (lease?.holder && !lease.expired && !running) out.push({ level: 'serious', title: 'Controller lease held outside an experiment', detail: `held by ${lease.holder}` });
  if (active?.state === 'failed') out.push({ level: 'serious', title: 'Last experiment failed', detail: active.error || active.id });
  if (active?.cleanup && active.cleanup.safe === false) out.push({ level: 'critical', title: 'Cleanup not verified', detail: 'verify HPA ownership manually (./scripts/stop_review.sh)' });
  const budget = live?.policy?.max_total_replicas;
  const total = services.reduce((a, s) => a + (s.desired_replicas || 0), 0);
  if (budget && total >= budget * 0.9) out.push({ level: 'warning', title: 'Replica budget nearly used', detail: `${total} of ${budget} replicas (FlexaScale scale-ups stop at the budget)` });
  const order: Level[] = ['critical', 'serious', 'warning', 'good', 'unknown'];
  return out.sort((a, b) => order.indexOf(a.level) - order.indexOf(b.level));
}

export function Overview({ overview, live, liveErr, active, app, bench, onNavigate }: {
  overview: Json; live: Json; liveErr: string | null; active: Json; app: string; bench: Json; onNavigate: (p: string) => void;
}) {
  const [sel, setSel] = useState<string | null>(null);
  const services: Json[] = (live?.services || []).filter((s: Json) => s.eligible);
  const policy = live?.policy || {};
  const cluster = overview?.cluster;
  const exp = active && active.request?.app === app ? active : null;
  const running = exp && !['completed', 'stopped', 'failed', 'interrupted'].includes(exp.state);
  const last = exp?.samples?.[exp.samples.length - 1];
  const alerts = useMemo(() => deriveAlerts(overview, live, active), [overview, live, active]);
  const rate = costRate(services, policy.cost);
  const totalReady = services.reduce((a, s) => a + (s.ready_replicas || 0), 0);
  const totalDesired = services.reduce((a, s) => a + (s.desired_replicas || 0), 0);
  const owners = services.reduce((acc: Record<string, number>, s) => ((acc[s.owner] = (acc[s.owner] || 0) + 1), acc), {});
  const cpuVals = services.map((s) => s.metrics?.cpu_pct).filter((v: number | null) => v != null) as number[];
  const avgCpu = cpuVals.length ? cpuVals.reduce((a, b) => a + b, 0) / cpuVals.length : null;
  const replicaHist = useHistory<number>(services.length ? totalReady : null, live?.timestamp, 90);
  const costHist = useHistory<number>(rate.value, live?.timestamp, 90);
  const slo = exp?.slo?.e2e_p95_ms;
  const slaLevel: Level = !running || last?.p95_ms == null ? 'unknown' : last.e2e_slo_violation ? 'critical' : 'good';
  // Headline = the deployed comparison (Auto, else the newest FlexaScale model); the tuned-HPA reference is not a FlexaScale result.
  const fsModels = (bench?.models || []).filter((m: Json) => !String(m.model).startsWith('Native HPA'));
  const verdict = fsModels.find((m: Json) => String(m.model).includes('Auto')) || fsModels[0];
  const sNode = sel ? services.find((s) => s.name === sel) : null;
  const histFeed = useLiveHistory(app, !exp, 5000, live);
  const runFeed = useMemo(() => feedOfRun(exp, running ? 'live' : 'replay'), [exp, running]);
  const feed = exp ? runFeed : histFeed;

  if (!live && !liveErr) {
    return (
      <div className="grid gap-4 grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 8 }, (_, i) => <div key={i} className="card p-4 space-y-3"><Skeleton h={10} w="40%" /><Skeleton h={26} w="60%" /><Skeleton h={10} w="70%" /></div>)}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <ErrorNote error={liveErr} what="Live telemetry" />

      <div className="grid gap-3 grid-cols-2 lg:grid-cols-3 2xl:grid-cols-6">
        <Stat label="Active controller" icon="shield" accent={exp ? (isNativeHpa(exp.request.controller) ? 'var(--hpa)' : exp.request.controller === 'auto' ? 'var(--auto)' : 'var(--flexa)') : undefined}
          value={running ? CONTROLLER_LABEL[exp.request.controller] || exp.request.controller : 'Native HPA'}
          sub={running ? `${exp.request.scenario.replace(/_/g, ' ')} · ${fmtElapsed(last?.elapsed)} of ${fmtElapsed(exp.request.duration)}` : 'no experiment running; HPAs own scaling'}
          level={running ? 'good' : undefined} />
        <Stat label="Cluster" icon="server" value={cluster ? `${cluster.nodes_ready}/${cluster.nodes_total} node` : '—'}
          level={!cluster ? 'unknown' : cluster.kubectl && cluster.prometheus && cluster.nodes_ready === cluster.nodes_total ? 'good' : 'critical'}
          sub={cluster ? `${cluster.context} · Prometheus ${cluster.prometheus ? 'up' : 'down'}` : 'loading'} />
        <Stat label="End-to-end SLA" icon="clock" level={slaLevel}
          value={running && last?.p95_ms != null ? `${fmt(last.p95_ms)} ms` : '—'}
          sub={running ? `p95 (10 s window) · target ≤ ${fmt(slo)} ms` : 'measured during experiments (Locust p95)'} />
        <Stat label="Replicas" icon="layers" value={`${totalReady}`}
          sub={<span className="inline-flex items-center gap-2">ready of {totalDesired} desired{policy.max_total_replicas ? ` · budget ${policy.max_total_replicas}` : ''} <Sparkline values={replicaHist} width={60} height={16} /></span>} />
        <Stat label="Mean CPU" icon="live" value={avgCpu == null ? '—' : `${fmt(avgCpu)}%`} sub={`of request, ${cpuVals.length}/${services.length} services reporting`} />
        <Stat label={rate.priced ? 'Estimated cost rate' : 'Resource-cost proxy'} icon="cost"
          value={rate.value == null ? '—' : rate.priced ? `${fmtMoney(rate.value, rate.currency, 3)}/h` : `${fmt(rate.value, 2)}/h`}
          hint={rate.priced ? policy.cost?.label || 'configured prices' : 'vCPU-h + 0.125 × GiB-h; set prices in the policy to see money'}
          sub={<span className="inline-flex items-center gap-2">{fmt(rate.vcpu, 1)} vCPU · {fmt(rate.gib, 1)} GiB allocated <Sparkline values={costHist} width={50} height={16} /></span>} />
      </div>

      <WorkloadStrip exp={exp} running={!!running} last={last} services={services} />

      <ScalingTimeline feed={feed} compact strips={false}
        emptyText="Recording live cluster state from now on (5 s). Start an experiment in the Live lab for traffic, latency and policy decisions." />

      <div className="grid gap-4 xl:grid-cols-[1fr_380px]">
        <Card eyebrow="Application topology" title={`${services.length} services · ${live?.namespace || ''}`}
          actions={<div className="flex items-center gap-2 text-xs">{Object.entries(owners).map(([o, n]) => <span key={o} className="inline-flex items-center gap-1"><OwnerBadge owner={o} compact /><span className="tnum ink2">×{n as number}</span></span>)}</div>}>
          {services.length ? (
            <Topology services={services} edges={policy.topology || []} slo={policy.slo_latency_ms} onSelect={(n) => setSel(sel === n ? null : n)} selected={sel} />
          ) : (
            <Empty icon="layers">No eligible services discovered in {live?.namespace}.</Empty>
          )}
          {sNode && (
            <div className="card-flat mt-3 p-3 grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3 text-sm fade-in">
              <div className="col-span-2 sm:col-span-4 lg:col-span-1 font-semibold flex items-center gap-2"><span className="dot" style={{ background: OWNER_COLOR[sNode.owner] }} />{sNode.name}</div>
              {[
                ['Owner', <OwnerBadge key="o" owner={sNode.owner} compact />],
                ['Replicas', `${sNode.ready_replicas} / ${sNode.desired_replicas}`],
                ['HPA range', sNode.hpa ? `${sNode.hpa.min_replicas}–${sNode.hpa.max_replicas}` : 'no HPA'],
                ['CPU', `${fmt(sNode.metrics?.cpu_pct)}%`],
                ['Req/s', fmt(sNode.metrics?.request_rate, 2)],
                ['Latency mean / p95', `${fmt(sNode.metrics?.latency_mean_ms)} / ${fmt(sNode.metrics?.latency_p95_ms)} ms`],
              ].map(([k, v]) => (
                <div key={String(k)} className="min-w-0"><div className="eyebrow">{k}</div><div className="tnum truncate">{v}</div></div>
              ))}
            </div>
          )}
        </Card>

        <Card eyebrow="Alerts" title={alerts.length ? `${alerts.length} active` : 'All clear'}
          actions={<StatusBadge level={alerts[0]?.level || 'good'} label={alerts.length ? alerts[0].level : 'healthy'} />}>
          {alerts.length === 0 ? (
            <Empty icon="check" height={120}>Cluster reachable, CPU telemetry for every service, no service over its SLO, no frozen HPA left behind.</Empty>
          ) : (
            <ul className="space-y-2 max-h-[360px] overflow-y-auto scroll-thin pr-1">
              {alerts.map((a, i) => (
                <li key={i} className="card-flat p-2.5 flex gap-2.5 text-sm">
                  <Icon name={a.level === 'critical' ? 'error' : 'alert'} size={16} style={{ color: `var(--${a.level})` }} className="mt-0.5 shrink-0" />
                  <div className="min-w-0"><div className="font-semibold">{a.title}</div><div className="text-xs ink2 break-words">{a.detail}</div></div>
                </li>
              ))}
            </ul>
          )}
          <p className="text-xs muted mt-3">Derived from live Kubernetes and Prometheus state every 5 s.</p>
          <RecentEvents events={exp?.events || []} />
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card eyebrow="Benchmark verdict" title={verdict ? `FlexaScale ${verdict.model} vs native HPA` : 'No paired benchmark yet'}
          actions={<button className="btn btn-ghost text-xs" onClick={() => onNavigate('compare')}>Details <Icon name="external" size={13} /></button>}>
          {verdict ? (
            <div className="space-y-3">
              <div className="grid grid-cols-3 gap-3">
                {[
                  ['Replica-hours', verdict.pooled?.replica_hours_pct, '%'],
                  ['p95 latency', verdict.pooled?.p95_pct, '%'],
                  ['Failure rate', verdict.pooled?.failure_pp, ' pp'],
                ].map(([k, v, u]: Json) => (
                  <div key={k} className="card-flat p-3 min-w-0">
                    <div className="eyebrow">{k}</div>
                    <div className="text-xl font-semibold tnum mt-1">{v ? fmtSigned(v.mean, deltaDigits(u), u) : '—'}</div>
                    <div className="text-xs muted tnum">{v?.ci95 != null ? `95% CI ${fmtSigned(v.ci95[0], deltaDigits(u))} … ${fmtSigned(v.ci95[1], deltaDigits(u))}` : 'needs ≥ 2 pairs'}</div>
                  </div>
                ))}
              </div>
              <div className="text-sm flex flex-wrap items-start gap-2">
                <StatusBadge level={verdict.n_pairs < MIN_PAIRS ? 'warning' : verdict.verdict_level} label={verdict.n_pairs < MIN_PAIRS ? `Preliminary · ${verdict.n_pairs} pair${verdict.n_pairs === 1 ? '' : 's'}` : verdict.verdict} />
                {running && !isNativeHpa(exp?.request?.controller) && <span className="pill">batch in progress</span>}
                <span className="ink2">{verdict.n_pairs} paired runs · {verdict.scenarios} scenarios · negative = FlexaScale lower than HPA · cost basis: {verdict.cost_basis}.</span>
              </div>
            </div>
          ) : (
            <Empty icon="compare" height={120}>Run the same scenario once with each controller (Live lab), or the batch script, to get a paired comparison.</Empty>
          )}
        </Card>

        <Card eyebrow="Cost per experiment" title="Replica-hours by run (recorded experiments)"
          actions={<span className="text-xs muted">{rate.priced ? `prices: ${policy.cost?.label || 'configured'}` : 'proxy units'}</span>}>
          <RunCostChart runs={bench?.recent || []} />
        </Card>
      </div>

      {exp && (
        <Card eyebrow={running ? 'Running now' : 'Last experiment'} title={exp.id}
          actions={<button className="btn text-xs" onClick={() => onNavigate('live')}>Open live lab <Icon name="live" size={13} /></button>}>
          <div className="text-sm ink2 flex flex-wrap gap-x-5 gap-y-1">
            <span>{CONTROLLER_LABEL[exp.request.controller]} · {exp.request.scenario.replace(/_/g, ' ')} · {exp.request.users} users · {exp.request.duration} s</span>
            <span>state <b className="text-[var(--ink)]">{exp.state}</b></span>
            {exp.ended_at && <span>ended {fmtAgo(exp.ended_at)}</span>}
            {exp.summary?.workload && <span className="tnum">{fmt(exp.summary.workload.throughput_rps, 2)} req/s · p95 {fmt(exp.summary.workload.p95_ms)} ms · failures {fmt(exp.summary.workload.failure_rate_pct, 1)}% · {fmt(exp.summary.resources?.replica_hours, 3)} replica-h</span>}
          </div>
          {running && <div className="mt-3"><Meter value={last?.elapsed || 0} max={exp.request.duration} label="progress" /></div>}
        </Card>
      )}
    </div>
  );
}

function RunCostChart({ runs }: { runs: Json[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const data = runs.filter((r) => r.replica_hours != null).slice(-30);
  if (data.length < 2) return <Empty icon="cost" height={160}>Complete at least two experiments to see the trend.</Empty>;
  const W = 560, H = 180, L = 40, R = 10, T = 10, B = 26;
  const max = Math.max(...data.map((r) => r.replica_hours)) * 1.1;
  const x = (i: number) => L + ((i + 0.5) / data.length) * (W - L - R);
  const y = (v: number) => T + (H - T - B) * (1 - v / max);
  const bw = Math.max(4, ((W - L - R) / data.length) * 0.6);
  const ticks = [0, 0.5, 1].map((f) => f * max);
  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" role="img" aria-label="Replica-hours per run" onMouseLeave={() => setHover(null)}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={L} x2={W - R} y1={y(t)} y2={y(t)} stroke="var(--grid)" />
            <text x={L - 6} y={y(t) + 4} textAnchor="end" fontSize={10} fill="var(--muted)" className="tnum">{fmt(t, 1)}</text>
          </g>
        ))}
        {data.map((r, i) => (
          <g key={r.id} onMouseEnter={() => setHover(i)}>
            <rect x={x(i) - bw / 2 - 2} y={T} width={bw + 4} height={H - T - B} fill="transparent" />
            <rect x={x(i) - bw / 2} y={y(r.replica_hours)} width={bw} height={Math.max(1, y(0) - y(r.replica_hours))} rx={Math.min(4, bw / 2)}
              fill={isNativeHpa(r.controller) ? 'var(--hpa)' : 'var(--flexa)'} opacity={hover === null || hover === i ? 1 : 0.45} />
          </g>
        ))}
        <line x1={L} x2={W - R} y1={y(0)} y2={y(0)} stroke="var(--axis)" />
        <text x={L} y={H - 8} fontSize={10} fill="var(--muted)">older</text>
        <text x={W - R} y={H - 8} fontSize={10} fill="var(--muted)" textAnchor="end">newer</text>
      </svg>
      <div className="flex gap-4 text-xs ink2 mt-1">
        <span className="inline-flex items-center gap-1.5"><span className="dot" style={{ background: 'var(--hpa)' }} />Native HPA</span>
        <span className="inline-flex items-center gap-1.5"><span className="dot" style={{ background: 'var(--flexa)' }} />FlexaScale / Auto</span>
      </div>
      {hover !== null && (
        <div className="absolute top-0 right-0 card px-3 py-2 text-xs pointer-events-none">
          <div className="font-semibold">{data[hover].scenario?.replace(/_/g, ' ')} · {CONTROLLER_LABEL[data[hover].controller]}</div>
          <div className="tnum ink2">{fmt(data[hover].replica_hours, 3)} replica-h · p95 {fmt(data[hover].p95_ms)} ms</div>
          <div className="muted">{data[hover].id}</div>
        </div>
      )}
    </div>
  );
}

const EVENT_KINDS: Record<string, string> = { scale_request: 'Scale', replicas: 'Replicas', auto: 'Owner', safety: 'Safety', ownership: 'Ownership' };

function RecentEvents({ events }: { events: Json[] }) {
  const recent = events.filter((e) => EVENT_KINDS[e.kind]).slice(-6).reverse();
  return (
    <div className="mt-4 pt-4 border-t" style={{ borderColor: 'var(--grid)' }}>
      <div className="eyebrow mb-2">Recent scaling & ownership events</div>
      {recent.length === 0 ? (
        <div className="text-xs muted">None in the current or last experiment.</div>
      ) : (
        <ol className="space-y-1.5 text-xs">
          {recent.map((e, i) => (
            <li key={i} className="flex gap-2 items-baseline min-w-0">
              <span className="tnum muted w-10 shrink-0 text-right">{fmtElapsed(e.elapsed)}</span>
              <span className="pill !py-0 !px-2 shrink-0">{EVENT_KINDS[e.kind]}</span>
              <span className="ink2 truncate" title={e.message}>{e.message}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

/** The workload right now, from the running experiment's latest Locust sample; idle otherwise (never zeros). */
function WorkloadStrip({ exp, running: active, last, services }: { exp: Json; running: boolean; last: Json; services: Json[] }) {
  const running = active && exp?.state === 'running' && last != null;
  const mem = services.map((s) => s.metrics?.memory_pct).filter((v: number | null) => v != null) as number[];
  const avgMem = mem.length ? mem.reduce((a, b) => a + b, 0) / mem.length : null;
  const errPct = last?.rps ? (100 * (last.fail_rps || 0)) / last.rps : null;
  const slo = exp?.slo?.e2e_p95_ms;
  const violated = (exp?.samples || []).filter((s: Json) => s.e2e_slo_violation).length;
  const total = (exp?.samples || []).filter((s: Json) => s.p95_ms != null).length;
  const cell = (k: string, v: ReactNode, sub?: ReactNode, level?: 'critical' | 'serious' | null) => (
    <div className="min-w-0 px-4 py-3 border-r last:border-r-0" style={{ borderColor: 'var(--grid)' }}>
      <div className="eyebrow truncate">{k}</div>
      <div className="text-xl font-semibold tnum mt-1 flex items-center gap-1.5">
        {level && <Icon name={level === 'critical' ? 'error' : 'alert'} size={15} style={{ color: `var(--${level})` }} />}
        <span className="truncate">{v}</span>
      </div>
      {sub && <div className="text-xs muted truncate mt-0.5">{sub}</div>}
    </div>
  );
  return (
    <section className="card fade-in overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-2 px-4 pt-3">
        <span className="eyebrow">Workload now {running ? '· Locust, 10 s window' : ''}</span>
        {!running && <span className="text-xs muted">{active ? 'Experiment preparing (comparable start): no load yet.' : 'Idle: no load generator running. Start a scenario in the Live lab.'}</span>}
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-7">
        {cell('Throughput', running && last?.rps != null ? `${fmt(last.rps, 1)} req/s` : '—', running ? `${fmt(last?.users)} virtual users` : active ? 'preparing' : 'idle')}
        {cell('p50 latency', running && last?.p50_ms != null ? `${fmt(last.p50_ms)} ms` : '—')}
        {cell('p95 latency', running && last?.p95_ms != null ? `${fmt(last.p95_ms)} ms` : '—', slo ? `SLO ≤ ${fmt(slo)} ms` : undefined, running && last?.e2e_slo_violation ? 'critical' : null)}
        {cell('p99 latency', running && last?.p99_ms != null ? `${fmt(last.p99_ms)} ms` : '—')}
        {cell('Error rate', running && errPct != null ? `${fmt(errPct, 1)}%` : '—', running && last?.total_requests != null ? `${fmt(last.total_failures)} of ${fmt(last.total_requests)}` : undefined,
          running && errPct != null && errPct > 5 ? 'serious' : null)}
        {cell('SLA time violated', running && total ? `${fmt((100 * violated) / total)}%` : '—', running && total ? `${violated} of ${total} samples (5 s)` : undefined, running && total && violated / total > 0.1 ? 'serious' : null)}
        {cell('Mean memory', avgMem == null ? '—' : `${fmt(avgMem)}%`, `of limit, ${mem.length}/${services.length} services`)}
      </div>
    </section>
  );
}
