import { useMemo, useState } from 'react';
import { CONTROLLER_LABEL, Json, OWNER_COLOR, isNativeHpa, TERMINAL, api, fmt, fmtElapsed, seriesColor } from '../api';
import { LineChart, Series } from '../LineChart';
import { Card, Empty, ErrorNote, Icon, Meter, OwnerBadge, Stat, StatusBadge } from '../ui';
import { ScalingTimeline } from '../timeline/ScalingTimeline';
import { feedOfRun, useLiveHistory } from '../timeline/feeds';

const KIND_LABEL: Record<string, string> = {
  preflight: 'Preflight', ownership: 'Ownership', workload: 'Workload', traffic: 'Traffic', metric: 'Metric',
  decision: 'Policy', scale_request: 'Scale request', replicas: 'Replica change', ready: 'Ready', safety: 'Safety',
  auto: 'Auto mode', warning: 'Warning', error: 'Error', experiment: 'Experiment',
};

const CONTROLLER_HELP: Record<string, string> = {
  hpa: 'Kubernetes native HPA scales every service (CPU 70% target). FlexaScale can run in shadow mode and only log what it would do.',
  flexascale: 'FlexaScale takes the controller Lease, freezes each HPA at the current size, then scales with the trained policy. Hands a service back to its HPA when unsure.',
  auto: 'Per service and per step, explainable rules choose FlexaScale or native HPA (health → confidence → SLA risk → efficiency). One owner per Deployment at any time.',
  hpa_fast: 'Native HPA with only its scale-down stabilisation window shortened to 60 s (the earlier tuned reference). Restored after the run.',
  hpa_tuned: 'Native HPA with the calibrated settings of docs/POLICY_V7.md §2: 60 s scale-down window and the CPU target chosen on a separate calibration workload. Restored after the run.',
};

export function LiveLab({ meta, live, liveErr, active, app, shopUrl, grafana, prometheus, reloadActive }: {
  meta: Json; live: Json; liveErr: string | null; active: Json; app: string; shopUrl?: string; grafana?: string; prometheus?: string; reloadActive: () => void;
}) {
  const scenarios: Record<string, Json> = meta?.scenarios || {};
  const controllers: string[] = meta?.controllers || ['hpa', 'flexascale'];
  const variants: string[] = meta?.variants?.[app] || [];
  const limits = meta?.limits || { users: [1, 500], spawn_rate: [0.1, 100], duration: [30, 3600] };
  const exp = active && active.request?.app === app ? active : null;
  const running = !!exp && !TERMINAL.includes(exp.state);

  const [controller, setController] = useState('hpa');
  const [variant, setVariant] = useState('');
  const [scenario, setScenario] = useState('flash_sale');
  const [users, setUsers] = useState(25);
  const [spawn, setSpawn] = useState(5);
  const [duration, setDuration] = useState(300);
  const [reset, setReset] = useState(true);
  const [shadow, setShadow] = useState(true);
  const [busy, setBusy] = useState(false);
  const [actionErr, setActionErr] = useState<string | null>(null);
  const [confirmStop, setConfirmStop] = useState(false);
  // Runs started elsewhere (e.g. the benchmark batch script) keep Stop locked until the viewer unlocks it.
  const [startedHere, setStartedHere] = useState<string | null>(null);
  const [unlocked, setUnlocked] = useState(false);
  const foreign = running && exp?.id !== startedHere;
  const stopLocked = foreign && !unlocked;
  const emptyText = running ? (exp.state === 'running' ? 'Waiting for the first samples…' : 'Preparing a comparable start: no load yet.') : undefined;

  async function start() {
    setBusy(true);
    setActionErr(null);
    try {
      const res = await api.start({ app, controller, scenario, users, spawn_rate: spawn, duration, reset_replicas: reset, shadow,
        ...(variant ? { policy_variant: variant } : {}) });
      setStartedHere(res?.id || null);
      reloadActive();
    } catch (e: unknown) {
      setActionErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  async function stop() {
    setBusy(true);
    setConfirmStop(false);
    try {
      await api.stop();
      reloadActive();
    } catch (e: unknown) {
      setActionErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const services: Json[] = (live?.services || []).filter((s: Json) => s.eligible);
  const names: string[] = services.map((s) => s.name).sort();
  const colorOf = (n: string) => seriesColor(Math.max(0, names.indexOf(n)));
  const samples: Json[] = exp?.samples || [];
  const last = samples[samples.length - 1];
  const x = samples.map((s) => s.elapsed);
  const slo = exp?.slo?.e2e_p95_ms;
  const [picked, setPicked] = useState<string[]>([]);
  const shown = picked.length ? names.filter((n) => picked.includes(n)) : names.slice(0, 8);
  const svcSeries = (field: string): Series[] =>
    shown.map((n) => ({ key: n, label: n.replace(/-service$/, ''), color: colorOf(n), values: samples.map((s) => s.services?.[n]?.[field] ?? null) }));
  const totalDesired = services.reduce((a, s) => a + (s.desired_replicas || 0), 0);
  const totalReady = services.reduce((a, s) => a + (s.ready_replicas || 0), 0);
  const fin = exp?.summary?.workload;
  const lowSample = (last?.total_requests ?? 0) < 100;
  const autoState: Record<string, Json> = exp?.auto_state || {};
  const owners = useMemo(() => services.reduce((acc: Record<string, number>, s) => ((acc[s.owner] = (acc[s.owner] || 0) + 1), acc), {}), [services]);
  const histFeed = useLiveHistory(app, !exp, 5000, live);
  const runFeed = useMemo(() => feedOfRun(exp, running ? 'live' : 'replay'), [exp, running]);
  const feed = exp ? runFeed : histFeed;

  return (
    <div className="grid gap-4 xl:grid-cols-[360px_1fr]">
      <aside className="space-y-4">
        <Card eyebrow="Experiment" title="Run a live comparison">
          <div className="space-y-4">
            <div>
              <div className="eyebrow mb-1.5">Autoscaling mode</div>
              <div className="grid grid-cols-2 gap-1.5" role="group" aria-label="Autoscaling mode">
                {controllers.map((k) => (
                  <button key={k} className={`mode-tile ${k === 'hpa' || k === 'flexascale' || k === 'auto' ? '' : 'mode-tile-ref'}`} aria-pressed={controller === k} disabled={running} onClick={() => setController(k)}
                    style={{ ['--tile' as string]: isNativeHpa(k) ? 'var(--hpa)' : k === 'auto' ? 'var(--auto)' : 'var(--flexa)' }}>
                    <span className="dot" style={{ background: 'var(--tile)' }} />
                    <span className="truncate">{CONTROLLER_LABEL[k] || k}</span>
                  </button>
                ))}
              </div>
              <p className="text-xs ink2 mt-2 leading-relaxed">{CONTROLLER_HELP[controller]}</p>
            </div>
            {variants.length > 0 && (
              <label className="block">
                <span className="eyebrow">FlexaScale policy</span>
                <select className="field mt-1.5" value={variant} disabled={running} onChange={(e) => setVariant(e.target.value)}>
                  <option value="">Default policy of this application</option>
                  {variants.map((v) => <option key={v} value={v}>{v}</option>)}
                </select>
                <span className="text-xs ink2 block mt-1.5">Used by FlexaScale and Auto runs, and by shadow mode in native-HPA runs (config/lab.yaml variants).</span>
              </label>
            )}
            <label className="block">
              <span className="eyebrow">Workload scenario (Locust)</span>
              <select className="field mt-1.5" value={scenario} disabled={running} onChange={(e) => setScenario(e.target.value)}>
                {Object.entries(scenarios).map(([k, v]) => <option key={k} value={k}>{v.title}</option>)}
              </select>
              <span className="text-xs ink2 block mt-1.5">{scenarios[scenario]?.description}</span>
            </label>
            <div className="grid grid-cols-3 gap-2">
              {[
                ['Peak users', users, setUsers, limits.users, 1],
                ['Spawn / s', spawn, setSpawn, limits.spawn_rate, 0.5],
                ['Duration s', duration, setDuration, limits.duration, 30],
              ].map(([label, val, set, lim, step]: Json) => (
                <label key={label}>
                  <span className="eyebrow">{label}</span>
                  <input className="field mt-1.5 tnum" type="number" min={lim[0]} max={lim[1]} step={step} value={val} disabled={running}
                    onChange={(e) => set(Number(e.target.value))} />
                </label>
              ))}
            </div>
            {users > 40 && <p className="text-xs" style={{ color: 'var(--serious)' }}>Above ~40 users the single Minikube node can run out of memory; comparisons used 25.</p>}
            <label className="flex items-start gap-2 text-sm">
              <input type="checkbox" className="mt-1" checked={reset} disabled={running} onChange={(e) => setReset(e.target.checked)} />
              <span>Comparable start <span className="block text-xs muted">reset application data and scale every service to its minimum first</span></span>
            </label>
            {isNativeHpa(controller) && (
              <label className="flex items-start gap-2 text-sm">
                <input type="checkbox" className="mt-1" checked={shadow} disabled={running} onChange={(e) => setShadow(e.target.checked)} />
                <span>FlexaScale shadow mode <span className="block text-xs muted">log proposals only, change nothing</span></span>
              </label>
            )}
            <div className="flex gap-2">
              <button className="btn btn-primary flex-1" disabled={running || busy} onClick={start}><Icon name="play" size={14} />{busy && !running ? 'Starting…' : 'Start'}</button>
              {!confirmStop ? (
                <button className="btn btn-danger flex-1" disabled={!running || busy || stopLocked} onClick={() => setConfirmStop(true)}
                  title={stopLocked ? 'Locked: this run was not started from this page' : undefined}><Icon name="stop" size={14} />Stop</button>
              ) : (
                <button className="btn btn-danger flex-1" onClick={stop} autoFocus onBlur={() => setTimeout(() => setConfirmStop(false), 200)}>Confirm stop</button>
              )}
            </div>
            {foreign && (
              <label className="flex items-start gap-2 text-xs card-flat p-2.5" style={{ borderColor: 'var(--warning)' }}>
                <input type="checkbox" className="mt-0.5" checked={unlocked} onChange={(e) => setUnlocked(e.target.checked)} />
                <span>This run was started elsewhere (for example by the benchmark batch). Stop is locked so it cannot be ended by accident. Tick to unlock.</span>
              </label>
            )}
            <p className="text-xs muted">Stop ends Locust and the operator and always restores HPA ownership (verified).</p>
            <ErrorNote error={actionErr} />
          </div>
        </Card>

        <Card eyebrow="Open alongside" title="Application & observability">
          <div className="space-y-2 text-sm">
            {shopUrl ? (
              <a className="btn w-full justify-between" href={shopUrl} target="_blank" rel="noreferrer">Shopping application <Icon name="external" size={14} /></a>
            ) : <span className="muted block">Application URL resolves when an experiment starts.</span>}
            {grafana && <a className="btn w-full justify-between" href={grafana} target="_blank" rel="noreferrer">Grafana <Icon name="external" size={14} /></a>}
            {prometheus && <a className="btn w-full justify-between" href={prometheus} target="_blank" rel="noreferrer">Prometheus <Icon name="external" size={14} /></a>}
            <p className="text-xs muted">Browsing the shop by hand adds to the Locust load. Demo login: demo@flexascale.io.</p>
          </div>
        </Card>

        <Card eyebrow="Controller ownership" title={live?.lease?.holder && !live?.lease?.expired ? 'Lease held by FlexaScale' : 'Lease free'}>
          <div className="flex flex-wrap gap-2 mb-2">
            {Object.entries(owners).map(([k, v]) => <span key={k} className="inline-flex items-center gap-1"><OwnerBadge owner={k} /><span className="tnum ink2 text-sm">×{v as number}</span></span>)}
          </div>
          {live?.operator ? (
            <div className="text-xs ink2 space-y-0.5">
              <div>Operator: <b>{live.operator.effective_mode}</b>{live.operator.auto ? ' · Auto arbitration' : ''} · step {live.operator.step}</div>
              <div className="truncate" title={live.operator.model?.model_path}>{live.operator.model ? `Model ${String(live.operator.model.model_path).split('/').slice(-3).join('/')}` : 'NO MODEL (CPU heuristic)'}</div>
            </div>
          ) : <div className="text-xs muted">No operator running.</div>}
          <p className="text-xs muted mt-2">A FlexaScale-owned service has its HPA frozen at min = max; the original bounds are restored on hand-back.</p>
        </Card>
      </aside>

      <main className="space-y-4 min-w-0">
        <ErrorNote error={liveErr} what="Live telemetry" />
        <Card pad>
          <div className="flex flex-wrap items-center gap-3 justify-between">
            <div className="min-w-0">
              <div className="eyebrow">{running ? 'Running' : 'Current / last experiment'}</div>
              <div className="font-semibold truncate">{exp ? exp.id : 'none yet'}</div>
              {exp && <div className="text-xs ink2">{CONTROLLER_LABEL[exp.request.controller] || exp.request.controller} · {scenarios[exp.request.scenario]?.title || exp.request.scenario} · {exp.request.users} users · {exp.request.duration}s</div>}
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              {exp && <StatusBadge level={exp.state === 'failed' ? 'critical' : running ? 'good' : exp.state === 'completed' ? 'good' : 'warning'} label={exp.state} />}
              {exp?.summary?.preliminary && <StatusBadge level="warning" label="preliminary" />}
            </div>
          </div>
          {exp && <div className="mt-3"><Meter value={last?.elapsed || 0} max={exp.request.duration} label="progress" /></div>}
          {exp?.error && <div className="mt-3"><ErrorNote error={exp.error} /></div>}
        </Card>

        <div className="grid gap-3 grid-cols-2 md:grid-cols-4 2xl:grid-cols-7">
          <Stat label="Elapsed" value={exp ? fmtElapsed(last?.elapsed ?? null) : '—'} sub={exp ? `of ${fmtElapsed(exp.request.duration)}` : undefined} />
          <Stat label="Users" value={fmt(last?.users)} />
          <Stat label="Throughput" value={fmt(last?.rps, 1)} sub="req/s, 10 s window" />
          <Stat label="Error rate" value={last?.rps ? fmt((100 * (last.fail_rps || 0)) / last.rps, 1, '%') : '—'} sub={`${fmt(last?.total_failures)} of ${fmt(last?.total_requests)}`} />
          <Stat label="p50 / p95" value={last?.p95_ms != null ? `${fmt(last.p50_ms)} / ${fmt(last.p95_ms)}` : '—'} sub={lowSample && last ? 'few samples: indicative' : `p99 ${fmt(last?.p99_ms)} ms`} />
          <Stat label="Replicas" value={`${totalReady} / ${totalDesired}`} sub="ready / desired" />
          <Stat label="E2E SLA" value={last?.p95_ms == null ? '—' : last.e2e_slo_violation ? 'Violated' : 'Met'}
            level={last?.p95_ms == null ? undefined : last.e2e_slo_violation ? 'critical' : 'good'} sub={slo ? `p95 ≤ ${fmt(slo)} ms` : undefined} />
        </div>

        {fin && (
          <Card eyebrow={`Whole-run result${exp.summary.preliminary ? ' (preliminary)' : ''}`} title={`${fmt(fin.throughput_rps, 2)} req/s · p95 ${fmt(fin.p95_ms)} ms · failures ${fmt(fin.failure_rate_pct, 2)}%`}>
            <div className="text-sm ink2 tnum flex flex-wrap gap-x-5 gap-y-1">
              <span>{fmt(fin.total_requests)} requests</span><span>p50 {fmt(fin.p50_ms)} ms</span><span>p99 {fmt(fin.p99_ms)} ms</span>
              <span>replica-hours {fmt(exp.summary.resources?.replica_hours, 4)}</span>
              <span>{exp.summary.resources?.cost_model === 'priced'
                ? `estimated ${exp.summary.resources?.cost_currency} ${fmt(exp.summary.resources?.estimated_cost, 5)} (list prices, not a bill)`
                : `cost proxy ${fmt(exp.summary.resources?.resource_cost_proxy, 5)}`}</span>
            </div>
            {exp.cleanup && (
              <div className="mt-2"><StatusBadge level={exp.cleanup.safe ? 'good' : 'critical'} label={exp.cleanup.safe ? 'Cleanup verified: HPA ownership restored' : 'Cleanup not verified: check ownership'} /></div>
            )}
          </Card>
        )}

        <ScalingTimeline feed={feed}
          emptyText={exp ? emptyText : 'No experiment yet: the timeline starts recording live cluster state as soon as this page polls it. Start a run to add Locust traffic, latency and policy decisions.'} />

        {exp?.request?.controller === 'auto' && <AutoDecisions state={autoState} running={running} />}
        {exp && <PolicyPanel events={exp.events || []} controller={exp.request.controller} shadow={exp.request.shadow} />}

        <div className="grid gap-4 2xl:grid-cols-2">
          <LineChart title="CPU per service" unit="% of request (HPA semantics)" x={x} empty={emptyText} reference={{ value: live?.policy?.cpu_target_pct || 70, label: 'target' }} series={svcSeries('cpu_pct')} />
          <LineChart title="Memory per service" unit="% of limit" x={x} empty={emptyText} series={svcSeries('memory_pct')} />
        </div>
        {names.length > 8 && (
          <div className="flex flex-wrap items-center gap-1.5 text-xs">
            <span className="muted mr-1">Per-service charts show {picked.length ? 'the selected' : 'the first 8'} services (at most 8 colours):</span>
            {names.map((n) => (
              <button key={n} className="pill" aria-pressed={picked.includes(n)} style={{ opacity: !picked.length || picked.includes(n) ? 1 : 0.5 }}
                onClick={() => setPicked((p) => (p.includes(n) ? p.filter((x) => x !== n) : p.length >= 8 ? p : [...p, n]))}>
                {n.replace(/-service$/, '')}
              </button>
            ))}
            {picked.length > 0 && <button className="pill" onClick={() => setPicked([])}>reset</button>}
          </div>
        )}

        <Card eyebrow="Services" title="Live per-service state (5 s refresh)" pad={false}>
          <div className="overflow-x-auto scroll-thin">
            <table className="data w-full text-sm tnum">
              <thead><tr><th>Service</th><th>Owner</th><th>Ready / desired</th><th>HPA min–max</th><th>CPU % req</th><th>Mem %</th><th>Req/s</th><th>Mean ms</th><th>p95 ms</th><th>Telemetry</th></tr></thead>
              <tbody>
                {services.map((s) => {
                  const m = s.metrics || {};
                  return (
                    <tr key={s.name}>
                      <td><span className="inline-block w-2 h-2 rounded-full mr-2 align-middle" style={{ background: OWNER_COLOR[s.owner] }} />{s.name}</td>
                      <td><OwnerBadge owner={s.owner} compact /></td>
                      <td>{s.ready_replicas} / {s.desired_replicas}</td>
                      <td>{s.hpa ? `${s.hpa.min_replicas}–${s.hpa.max_replicas}${s.hpa.original_min_replicas != null ? ` (frozen; was ${s.hpa.original_min_replicas}–${s.hpa.original_max_replicas})` : ''}` : 'no HPA'}</td>
                      <td>{fmt(m.cpu_pct, 1)}</td><td>{fmt(m.memory_pct, 1)}</td><td>{fmt(m.request_rate, 2)}</td>
                      <td>{fmt(m.latency_mean_ms, 1)}</td><td>{fmt(m.latency_p95_ms, 0)}</td>
                      <td className="text-xs">{m.stale ? <StatusBadge level="critical" label="stale" /> : m.missing?.length ? <span className="muted">missing {m.missing.join(', ')}</span> : <StatusBadge level="good" label="ok" />}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {!services.length && <Empty>No services discovered yet.</Empty>}
          </div>
        </Card>

        <EventLog events={exp?.events || []} />
      </main>
    </div>
  );
}

function AutoDecisions({ state, running }: { state: Record<string, Json>; running: boolean }) {
  const rows = Object.entries(state).sort(([a], [b]) => a.localeCompare(b));
  const counts = rows.reduce((acc: Record<string, number>, [, d]) => ((acc[d.rule] = (acc[d.rule] || 0) + 1), acc), {});
  return (
    <Card eyebrow="Auto mode" title={running ? 'Who owns each service right now, and why' : 'Final ownership decisions'}
      actions={<div className="flex flex-wrap gap-1.5">{Object.entries(counts).map(([r, n]) => <span key={r} className="pill">{r.replace(/_/g, ' ')} ×{n as number}</span>)}</div>}>
      {rows.length === 0 ? <Empty height={100}>Waiting for the first operator step…</Empty> : (
        <div className="overflow-x-auto scroll-thin">
          <table className="data w-full text-sm">
            <thead><tr><th>Service</th><th>Owner</th><th>Rule</th><th>Reason</th><th className="text-right">FlexaScale → / HPA →</th></tr></thead>
            <tbody>
              {rows.map(([svc, d]) => (
                <tr key={svc}>
                  <td>{svc}</td>
                  <td><OwnerBadge owner={d.owner} compact /></td>
                  <td><span className="pill">{d.rule.replace(/_/g, ' ')}</span></td>
                  <td className="ink2 whitespace-normal min-w-[260px]">{d.reason}</td>
                  <td className="text-right tnum">{d.flexascale_proposal ?? '—'} / {d.hpa_recommendation ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function EventLog({ events }: { events: Json[] }) {
  const kinds = Array.from(new Set(events.map((e) => e.kind)));
  const [hidden, setHidden] = useState<string[]>(['metric']);
  const shown = events.filter((e) => !hidden.includes(e.kind)).slice().reverse();
  return (
    <Card eyebrow="Event log" title="Scaling & ownership events"
      actions={<div className="flex flex-wrap gap-1.5">{kinds.map((k) => (
        <button key={k} className="pill" aria-pressed={!hidden.includes(k)} style={{ opacity: hidden.includes(k) ? 0.45 : 1 }}
          onClick={() => setHidden((h) => (h.includes(k) ? h.filter((x) => x !== k) : [...h, k]))}>{KIND_LABEL[k] || k}</button>
      ))}</div>}>
      <p className="text-xs muted mb-3">“Policy” = what the model proposed · “Scale request” = a change FlexaScale sent · “Replica change” / “Ready” = what Kubernetes did.</p>
      {shown.length === 0 ? <Empty height={100}>No events yet.</Empty> : (
        <ol className="space-y-1.5 max-h-[440px] overflow-y-auto scroll-thin text-sm pr-1">
          {shown.map((e, i) => (
            <li key={i} className="flex gap-3 items-baseline">
              <span className="tnum muted w-12 shrink-0 text-right text-xs">{fmtElapsed(e.elapsed)}</span>
              <span className="pill shrink-0 w-28 justify-center">{KIND_LABEL[e.kind] || e.kind}</span>
              <span className="ink2 break-words min-w-0">{e.message}</span>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}

/** Proposals vs applied actions vs safety interventions, from the run's logged events. */
function PolicyPanel({ events, controller, shadow }: { events: Json[]; controller: string; shadow: boolean }) {
  const proposals = events.filter((e) => e.kind === 'decision');
  const applied = events.filter((e) => e.kind === 'scale_request');
  const safety = events.filter((e) => e.kind === 'safety' || (e.kind === 'auto' && e.owner === 'hpa'));
  if (isNativeHpa(controller) && !shadow) return null;
  const recent = [...proposals.slice(-4), ...applied.slice(-6), ...safety.slice(-4)].sort((a, b) => (a.t || 0) - (b.t || 0)).slice(-10).reverse();
  const tag: Record<string, [string, string]> = { decision: ['Proposed', 'var(--muted)'], scale_request: ['Applied', 'var(--flexa)'], safety: ['Safety', 'var(--serious)'], auto: ['→ HPA', 'var(--hpa)'] };
  return (
    <Card eyebrow={isNativeHpa(controller) ? 'FlexaScale shadow mode' : 'FlexaScale policy'} title={isNativeHpa(controller) ? 'What FlexaScale would have done (nothing applied)' : 'Policy proposals, applied actions and safety interventions'}>
      <div className="grid grid-cols-3 gap-3 mb-4">
        {[
          ['Proposal batches', proposals.length, 'policy output (not an action)'],
          ['Applied scale requests', applied.length, isNativeHpa(controller) ? 'shadow: always 0' : 'sent to Kubernetes'],
          ['Safety interventions', safety.length, 'blocked changes and hand-backs to HPA'],
        ].map(([k, v, sub]) => (
          <div key={String(k)} className="card-flat p-3 min-w-0">
            <div className="eyebrow truncate">{k}</div>
            <div className="text-2xl font-semibold tnum mt-1">{fmt(v as number)}</div>
            <div className="text-xs muted truncate">{sub}</div>
          </div>
        ))}
      </div>
      {recent.length === 0 ? <Empty height={80}>No policy activity yet.</Empty> : (
        <ol className="space-y-1.5 text-sm">
          {recent.map((e, i) => (
            <li key={i} className="flex gap-3 items-baseline min-w-0">
              <span className="tnum muted w-12 shrink-0 text-right text-xs">{fmtElapsed(e.elapsed)}</span>
              <span className="pill shrink-0 w-20 justify-center"><span className="dot" style={{ background: tag[e.kind][1] }} />{tag[e.kind][0]}</span>
              <span className="ink2 min-w-0 break-words">{e.message}</span>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}
