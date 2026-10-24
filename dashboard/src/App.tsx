import { useCallback, useEffect, useMemo, useState } from 'react';
import { api, fmt, fmtElapsed, seriesColor, Json } from './api';
import { LineChart, Series } from './LineChart';

const TERMINAL = ['completed', 'stopped', 'failed', 'interrupted'];
const KIND_LABEL: Record<string, string> = {
  preflight: 'Preflight',
  ownership: 'Ownership',
  workload: 'Workload',
  traffic: 'Traffic',
  metric: 'Metric',
  decision: 'Policy',
  scale_request: 'Scale request',
  replicas: 'Replica change',
  ready: 'Ready',
  safety: 'Safety',
  warning: 'Warning',
  error: 'Error',
  experiment: 'Experiment',
};

function usePoll<T>(fn: () => Promise<T>, ms: number, deps: unknown[] = []): [T | null, string | null, () => void] {
  const [data, setData] = useState<T | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(() => {
    fn().then(
      (d) => {
        setData(d);
        setErr(null);
      },
      (e) => setErr(String(e.message || e)),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => {
    load();
    const id = window.setInterval(load, ms);
    return () => window.clearInterval(id);
  }, [load, ms]);
  return [data, err, load];
}

function Status({ ok, label, detail }: { ok: boolean | null; label: string; detail?: string }) {
  const color = ok === null ? 'var(--muted)' : ok ? 'var(--good)' : 'var(--critical)';
  return (
    <span className="pill" title={detail}>
      <span className="dot" style={{ background: color }} />
      {label}
      <span className="muted">{ok === null ? 'unknown' : ok ? 'ok' : 'down'}</span>
    </span>
  );
}

function Tile({ label, value, sub, warn }: { label: string; value: string; sub?: string; warn?: string }) {
  return (
    <div className="card p-3 min-w-0">
      <div className="text-xs muted mb-1">{label}</div>
      <div className="text-2xl font-semibold leading-tight truncate">{value}</div>
      {sub && <div className="text-xs ink2 mt-1 truncate">{sub}</div>}
      {warn && <div className="text-xs mt-1" style={{ color: 'var(--serious)' }}>{warn}</div>}
    </div>
  );
}

function OwnerBadge({ owner }: { owner: string }) {
  const map: Record<string, [string, string]> = {
    flexascale: ['FlexaScale', 'var(--s7)'],
    hpa: ['Native HPA', 'var(--s1)'],
    none: ['No autoscaler', 'var(--muted)'],
    excluded: ['Excluded', 'var(--muted)'],
  };
  const [label, color] = map[owner] || [owner, 'var(--muted)'];
  return (
    <span className="pill">
      <span className="dot" style={{ background: color }} />
      {label}
    </span>
  );
}

export default function App() {
  const [tab, setTab] = useState<'live' | 'results' | 'model'>('live');
  const [overview] = usePoll<Json>(api.overview, 10000);
  const [meta] = usePoll<Json>(api.scenarios, 600000);
  const apps: Json[] = overview?.apps || [];
  const [app, setApp] = useState<string>('shopping');
  const [live, liveErr] = usePoll<Json>(() => api.live(app), 5000, [app]);
  const [activeRes, , reloadActive] = usePoll<Json>(api.active, 3000);
  const active = activeRes?.active || null;
  const running = active && !TERMINAL.includes(active.state);

  const [controller, setController] = useState('hpa');
  const [scenario, setScenario] = useState('flash_sale');
  const [users, setUsers] = useState(40);
  const [spawn, setSpawn] = useState(5);
  const [duration, setDuration] = useState(300);
  const [reset, setReset] = useState(true);
  const [shadow, setShadow] = useState(true);
  const [busy, setBusy] = useState(false);
  const [actionErr, setActionErr] = useState<string | null>(null);

  async function start() {
    setBusy(true);
    setActionErr(null);
    try {
      await api.start({ app, controller, scenario, users, spawn_rate: spawn, duration, reset_replicas: reset, shadow });
      reloadActive();
    } catch (e: unknown) {
      setActionErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function stop() {
    setBusy(true);
    try {
      await api.stop();
      reloadActive();
    } catch (e: unknown) {
      setActionErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const cluster = overview?.cluster;
  const appInfo = apps.find((a) => a.name === app);
  const shopUrl = active?.request?.app === app && active?.app_url ? active.app_url : appInfo?.url;

  return (
    <div className="max-w-[1500px] mx-auto px-4 py-4 space-y-4">
      <header className="flex flex-wrap items-center gap-3 justify-between">
        <div>
          <h1 className="text-xl font-bold">FlexaScale Live Autoscaling Lab</h1>
          <p className="text-sm muted">Real telemetry from the cluster. Unavailable or stale values are shown as “—” and flagged, never estimated.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Status ok={cluster ? cluster.kubectl && cluster.nodes_ready > 0 : null} label={`Cluster ${cluster?.context || ''}`} detail={cluster?.error} />
          <Status ok={cluster ? cluster.prometheus : null} label="Prometheus" detail={cluster?.prometheus_url} />
          <select className="field !w-auto" value={app} onChange={(e) => setApp(e.target.value)} disabled={!!running} aria-label="Application">
            {(apps.length ? apps : [{ name: 'shopping', title: 'shopping' }]).map((a) => (
              <option key={a.name} value={a.name}>
                {a.title}
              </option>
            ))}
          </select>
        </div>
      </header>

      <nav className="seg" aria-label="Views">
        {(['live', 'results', 'model'] as const).map((t) => (
          <button key={t} aria-pressed={tab === t} onClick={() => setTab(t)}>
            {t === 'live' ? 'Live experiment' : t === 'results' ? 'Results & comparison' : 'Model & data'}
          </button>
        ))}
      </nav>

      {tab === 'live' && (
        <LiveView
          meta={meta}
          live={live}
          liveErr={liveErr}
          active={active}
          running={!!running}
          app={app}
          shopUrl={shopUrl}
          grafana={cluster?.grafana_url}
          prometheus={cluster?.prometheus_url}
          controls={{ controller, setController, scenario, setScenario, users, setUsers, spawn, setSpawn, duration, setDuration, reset, setReset, shadow, setShadow }}
          onStart={start}
          onStop={stop}
          busy={busy}
          actionErr={actionErr}
        />
      )}
      {tab === 'results' && <ResultsView />}
      {tab === 'model' && <ModelView />}
    </div>
  );
}

function LiveView(props: {
  meta: Json;
  live: Json;
  liveErr: string | null;
  active: Json;
  running: boolean;
  app: string;
  shopUrl?: string;
  grafana?: string;
  prometheus?: string;
  controls: Json;
  onStart: () => void;
  onStop: () => void;
  busy: boolean;
  actionErr: string | null;
}) {
  const { meta, live, liveErr, active, running, app, controls: c } = props;
  const scenarios: Record<string, Json> = meta?.scenarios || {};
  const services: Json[] = (live?.services || []).filter((s: Json) => s.eligible);
  const excluded: Json[] = (live?.services || []).filter((s: Json) => !s.eligible);
  const names: string[] = services.map((s) => s.name).sort();
  const colorOf = (name: string) => seriesColor(Math.max(0, names.indexOf(name)));
  const exp = active && active.request?.app === app ? active : null;
  const samples: Json[] = exp?.samples || [];
  const last = samples[samples.length - 1];
  const x = samples.map((s) => s.elapsed);
  const slo = exp?.slo?.e2e_p95_ms;

  const svcSeries = (field: string): Series[] =>
    names.map((n) => ({ key: n, label: n, color: colorOf(n), values: samples.map((s) => s.services?.[n]?.[field] ?? null) }));

  const owners = useMemo(() => {
    const out: Record<string, number> = {};
    for (const s of services) out[s.owner] = (out[s.owner] || 0) + 1;
    return out;
  }, [services]);

  const totalDesired = services.reduce((a, s) => a + (s.desired_replicas || 0), 0);
  const totalReady = services.reduce((a, s) => a + (s.ready_replicas || 0), 0);
  const elapsed = last?.elapsed ?? null;
  const fin = exp?.summary?.workload;
  const lowSample = (last?.total_requests ?? 0) < 100;

  return (
    <div className="grid gap-4 lg:grid-cols-[340px_1fr]">
      <aside className="space-y-4">
        <div className="card p-4 space-y-3">
          <h2 className="font-semibold">Experiment</h2>
          <div>
            <div className="text-xs muted mb-1">Autoscaling controller</div>
            <div className="seg w-full">
              {[
                ['hpa', 'Native HPA'],
                ['flexascale', 'FlexaScale'],
              ].map(([k, l]) => (
                <button key={k} className="flex-1" aria-pressed={c.controller === k} disabled={running} onClick={() => c.setController(k)}>
                  {l}
                </button>
              ))}
            </div>
          </div>
          <label className="block">
            <span className="text-xs muted">Workload scenario</span>
            <select className="field mt-1" value={c.scenario} disabled={running} onChange={(e) => c.setScenario(e.target.value)}>
              {Object.entries(scenarios).map(([k, v]) => (
                <option key={k} value={k}>
                  {v.title}
                </option>
              ))}
            </select>
            <span className="text-xs ink2 block mt-1">{scenarios[c.scenario]?.description}</span>
          </label>
          <div className="grid grid-cols-3 gap-2">
            <label>
              <span className="text-xs muted">Peak users</span>
              <input className="field mt-1 tnum" type="number" min={1} max={500} value={c.users} disabled={running} onChange={(e) => c.setUsers(Number(e.target.value))} />
            </label>
            <label>
              <span className="text-xs muted">Spawn/s</span>
              <input className="field mt-1 tnum" type="number" min={0.1} max={100} step={0.5} value={c.spawn} disabled={running} onChange={(e) => c.setSpawn(Number(e.target.value))} />
            </label>
            <label>
              <span className="text-xs muted">Duration s</span>
              <input className="field mt-1 tnum" type="number" min={30} max={3600} step={30} value={c.duration} disabled={running} onChange={(e) => c.setDuration(Number(e.target.value))} />
            </label>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={c.reset} disabled={running} onChange={(e) => c.setReset(e.target.checked)} />
            Reset replicas to minimum first (comparable start)
          </label>
          {c.controller === 'hpa' && (
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={c.shadow} disabled={running} onChange={(e) => c.setShadow(e.target.checked)} />
              FlexaScale shadow mode (log proposals, change nothing)
            </label>
          )}
          <div className="flex gap-2">
            <button className="btn btn-primary flex-1" disabled={running || props.busy} onClick={props.onStart}>
              Start
            </button>
            <button className="btn btn-danger flex-1" disabled={!running || props.busy} onClick={props.onStop}>
              Stop
            </button>
          </div>
          {props.actionErr && (
            <div className="text-sm" role="alert" style={{ color: 'var(--critical)' }}>
              {props.actionErr}
            </div>
          )}
        </div>

        <div className="card p-4 space-y-2 text-sm">
          <h2 className="font-semibold">Open alongside</h2>
          {props.shopUrl ? (
            <a className="block underline" style={{ color: 'var(--accent)' }} href={props.shopUrl} target="_blank" rel="noreferrer">
              Application: {props.shopUrl}
            </a>
          ) : (
            <span className="muted block">Application URL resolves when an experiment starts.</span>
          )}
          {props.grafana && (
            <a className="block underline" style={{ color: 'var(--accent)' }} href={props.grafana} target="_blank" rel="noreferrer">
              Grafana: {props.grafana}
            </a>
          )}
          {props.prometheus && (
            <a className="block underline" style={{ color: 'var(--accent)' }} href={props.prometheus} target="_blank" rel="noreferrer">
              Prometheus: {props.prometheus}
            </a>
          )}
          <p className="text-xs muted">Browsing the shop by hand is independent of the Locust background load.</p>
        </div>

        <div className="card p-4 space-y-2 text-sm">
          <h2 className="font-semibold">Controller ownership</h2>
          <div className="flex flex-wrap gap-2">
            {Object.entries(owners).map(([k, v]) => (
              <span key={k} className="flex items-center gap-1">
                <OwnerBadge owner={k} /> <span className="tnum">×{v as number}</span>
              </span>
            ))}
          </div>
          <div className="text-xs ink2">
            Lease <code>flexascale-{app}</code>:{' '}
            {live?.lease?.holder && !live?.lease?.expired ? <b>held by {live.lease.holder}</b> : 'free'}
          </div>
          {live?.operator && (
            <div className="text-xs ink2">
              Operator: {live.operator.effective_mode} mode, step {live.operator.step}
              {live.operator.model ? `, model ${String(live.operator.model.model_path).split('/').slice(-3).join('/')}` : ', NO MODEL (heuristic)'}
            </div>
          )}
          {excluded.length > 0 && <div className="text-xs muted">Not managed: {excluded.map((s) => `${s.name} (${s.reason})`).join(', ')}</div>}
        </div>
      </aside>

      <main className="space-y-4 min-w-0">
        <div className="card p-4 flex flex-wrap items-center gap-3 justify-between">
          <div className="min-w-0">
            <div className="text-xs muted">Current / last experiment</div>
            <div className="font-semibold truncate">{exp ? exp.id : 'none yet'}</div>
            {exp && (
              <div className="text-xs ink2">
                {exp.request.controller === 'flexascale' ? 'FlexaScale' : 'Native HPA'} · {scenarios[exp.request.scenario]?.title || exp.request.scenario} · {exp.request.users} users ·{' '}
                {exp.request.duration}s
              </div>
            )}
          </div>
          <div className="flex items-center gap-2">
            {exp && <span className="pill">{exp.state}</span>}
            {exp?.summary?.preliminary && <span className="pill" style={{ color: 'var(--serious)' }}>preliminary</span>}
            {exp?.error && <span className="text-sm" style={{ color: 'var(--critical)' }}>{exp.error}</span>}
          </div>
          {exp && (
            <div className="w-full h-1.5 rounded" style={{ background: 'var(--surface-2)' }}>
              <div className="h-1.5 rounded" style={{ width: `${Math.min(100, ((elapsed || 0) / exp.request.duration) * 100)}%`, background: 'var(--accent)' }} />
            </div>
          )}
        </div>

        <div className="grid gap-3 grid-cols-2 md:grid-cols-4 xl:grid-cols-7">
          <Tile label="Elapsed" value={exp ? fmtElapsed(elapsed) : "—"} sub={exp ? `of ${fmtElapsed(exp.request.duration)}` : undefined} />
          <Tile label="Users" value={fmt(last?.users)} />
          <Tile label="Request rate" value={fmt(last?.rps, 1)} sub="req/s (10 s window)" />
          <Tile
            label="Failure rate"
            value={last?.rps ? fmt((100 * (last.fail_rps || 0)) / last.rps, 1, '%') : '—'}
            sub={`${fmt(last?.total_failures)} of ${fmt(last?.total_requests)} total`}
          />
          <Tile
            label="Latency p50 / p95"
            value={last?.p95_ms != null ? `${fmt(last?.p50_ms)} / ${fmt(last?.p95_ms)}` : '—'}
            sub={`p99 ${fmt(last?.p99_ms)} ms`}
            warn={last && lowSample ? 'few samples: indicative only' : undefined}
          />
          <Tile label="Replicas" value={`${totalReady} / ${totalDesired}`} sub="ready / desired (managed)" />
          <Tile
            label="E2E SLO (p95)"
            value={last?.p95_ms == null ? '—' : last.e2e_slo_violation ? 'Violated' : 'Met'}
            sub={slo ? `target ≤ ${fmt(slo)} ms` : undefined}
          />
        </div>

        {fin && (
          <div className="card p-4 text-sm">
            <div className="font-semibold mb-1">Whole-run result {exp.summary.preliminary ? '(preliminary: short or incomplete run)' : ''}</div>
            <div className="ink2 tnum">
              {fmt(fin.total_requests)} requests · {fmt(fin.throughput_rps, 2)} req/s · failures {fmt(fin.failure_rate_pct, 2)}% · p50 {fmt(fin.p50_ms)} ms · p95 {fmt(fin.p95_ms)} ms · p99{' '}
              {fmt(fin.p99_ms)} ms · replica-hours {fmt(exp.summary.resources?.replica_hours, 4)} · {exp.summary.resources?.cost_model === 'priced'
                ? `est. ${exp.summary.resources?.cost_currency} ${fmt(exp.summary.resources?.estimated_cost, 5)}`
                : `cost proxy ${fmt(exp.summary.resources?.resource_cost_proxy, 5)}`}
            </div>
            {exp.cleanup && (
              <div className="text-xs mt-1" style={{ color: exp.cleanup.safe ? 'var(--good-text)' : 'var(--critical)' }}>
                Cleanup: {exp.cleanup.safe ? 'HPA ownership restored and verified' : 'verify ownership manually'} (frozen HPAs left: {exp.cleanup.frozen_hpas_after?.length ?? '?'})
              </div>
            )}
          </div>
        )}

        <div className="grid gap-4 xl:grid-cols-2">
          <LineChart
            title="Throughput"
            unit="requests per second"
            x={x}
            digits={1}
            series={[
              { key: 'rps', label: 'Requests/s', color: seriesColor(0), values: samples.map((s) => s.rps ?? null) },
              { key: 'fail', label: 'Failures/s', color: seriesColor(1), values: samples.map((s) => s.fail_rps ?? null) },
            ]}
          />
          <LineChart
            title="End-to-end latency (Locust, 10 s window)"
            unit="milliseconds"
            x={x}
            reference={slo ? { value: slo, label: `SLO p95 ${slo} ms` } : undefined}
            series={[
              { key: 'p50', label: 'p50', color: seriesColor(0), values: samples.map((s) => s.p50_ms ?? null) },
              { key: 'p95', label: 'p95', color: seriesColor(1), values: samples.map((s) => s.p95_ms ?? null) },
              { key: 'p99', label: 'p99', color: seriesColor(2), values: samples.map((s) => s.p99_ms ?? null) },
            ]}
          />
          <LineChart title="Desired replicas per service" unit="replicas" x={x} step series={svcSeries('desired')} minMax={3} />
          <LineChart
            title="CPU per service"
            unit="% of CPU request (HPA semantics)"
            x={x}
            reference={{ value: live?.policy?.cpu_target_pct || 70, label: 'target' }}
            series={svcSeries('cpu_pct')}
          />
        </div>

        <div className="card p-4 overflow-x-auto">
          <div className="flex items-baseline justify-between mb-2">
            <h3 className="font-semibold text-sm">Services (live, refreshed every 5 s)</h3>
            {liveErr && <span className="text-xs" style={{ color: 'var(--critical)' }}>{liveErr}</span>}
          </div>
          <table className="data w-full text-sm tnum">
            <thead>
              <tr>
                <th>Service</th>
                <th>Owner</th>
                <th>Ready / desired</th>
                <th>HPA min–max</th>
                <th>CPU % req</th>
                <th>Memory %</th>
                <th>Req/s</th>
                <th>Mean lat. ms</th>
                <th>p95 ms</th>
                <th>Telemetry</th>
              </tr>
            </thead>
            <tbody>
              {services.map((s) => {
                const m = s.metrics || {};
                return (
                  <tr key={s.name}>
                    <td>
                      <span className="inline-block w-2.5 h-2.5 rounded-full mr-2 align-middle" style={{ background: colorOf(s.name) }} />
                      {s.name}
                    </td>
                    <td>
                      <OwnerBadge owner={s.owner} />
                    </td>
                    <td>
                      {s.ready_replicas} / {s.desired_replicas}
                    </td>
                    <td>{s.hpa ? `${s.hpa.min_replicas}–${s.hpa.max_replicas}${s.hpa.original_min_replicas != null ? ` (frozen; was ${s.hpa.original_min_replicas}–${s.hpa.original_max_replicas})` : ''}` : 'no HPA'}</td>
                    <td>{fmt(m.cpu_pct, 1)}</td>
                    <td>{fmt(m.memory_pct, 1)}</td>
                    <td>{fmt(m.request_rate, 2)}</td>
                    <td>{fmt(m.latency_mean_ms, 1)}</td>
                    <td>{fmt(m.latency_p95_ms, 0)}</td>
                    <td className="text-xs">
                      {m.stale ? <span style={{ color: 'var(--critical)' }}>stale</span> : m.missing?.length ? <span className="muted">missing: {m.missing.join(', ')}</span> : <span style={{ color: 'var(--good-text)' }}>ok</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <Timeline events={exp?.events || []} />
      </main>
    </div>
  );
}

function Timeline({ events }: { events: Json[] }) {
  const kinds = Array.from(new Set(events.map((e) => e.kind)));
  const [hidden, setHidden] = useState<string[]>([]);
  const shown = events.filter((e) => !hidden.includes(e.kind)).slice().reverse();
  return (
    <div className="card p-4">
      <div className="flex flex-wrap items-center gap-2 mb-2">
        <h3 className="font-semibold text-sm mr-2">Scaling & event timeline</h3>
        {kinds.map((k) => (
          <button
            key={k}
            className="pill"
            aria-pressed={!hidden.includes(k)}
            style={{ opacity: hidden.includes(k) ? 0.45 : 1 }}
            onClick={() => setHidden((h) => (h.includes(k) ? h.filter((x) => x !== k) : [...h, k]))}
          >
            {KIND_LABEL[k] || k}
          </button>
        ))}
      </div>
      <p className="text-xs muted mb-2">
        “Policy” = what the model proposed; “Scale request” = a change FlexaScale actually sent; “Replica change” / “Ready” = what Kubernetes then did.
      </p>
      {shown.length === 0 ? (
        <div className="text-sm muted">No events yet.</div>
      ) : (
        <ol className="space-y-1 max-h-[420px] overflow-y-auto text-sm">
          {shown.map((e, i) => (
            <li key={i} className="flex gap-3">
              <span className="tnum muted w-12 shrink-0 text-right">{fmtElapsed(e.elapsed)}</span>
              <span className="pill shrink-0 w-28 justify-center">{KIND_LABEL[e.kind] || e.kind}</span>
              <span className="ink2 break-words min-w-0">{e.message}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function ResultsView() {
  const [runs] = usePoll<Json>(api.runs, 15000);
  const list: Json[] = runs?.runs || [];
  const [a, setA] = useState('');
  const [b, setB] = useState('');
  const [cmp, setCmp] = useState<Json>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!a || !b) return;
    api.compare(a, b).then(setCmp, (e) => setErr(String(e.message)));
  }, [a, b]);

  return (
    <div className="space-y-4">
      <div className="card p-4 overflow-x-auto">
        <h3 className="font-semibold text-sm mb-2">Recorded experiments ({list.length})</h3>
        <table className="data w-full text-sm tnum">
          <thead>
            <tr>
              <th>Baseline</th>
              <th>Candidate</th>
              <th>Run</th>
              <th>Controller</th>
              <th>Scenario</th>
              <th>Users</th>
              <th>Duration</th>
              <th>State</th>
              <th>Req/s</th>
              <th>p95 ms</th>
              <th>Replica-h</th>
              <th>Raw data</th>
            </tr>
          </thead>
          <tbody>
            {list.map((r) => (
              <tr key={r.id}>
                <td>
                  <input type="radio" name="base" checked={a === r.id} onChange={() => setA(r.id)} aria-label={`baseline ${r.id}`} />
                </td>
                <td>
                  <input type="radio" name="cand" checked={b === r.id} onChange={() => setB(r.id)} aria-label={`candidate ${r.id}`} />
                </td>
                <td className="text-xs">{r.id}</td>
                <td>{r.request.controller}</td>
                <td>{r.request.scenario}</td>
                <td>{r.request.users}</td>
                <td>{r.request.duration}s</td>
                <td>
                  {r.state}
                  {r.preliminary ? ' · preliminary' : ''}
                </td>
                <td>{fmt(r.throughput_rps, 2)}</td>
                <td>{fmt(r.p95_ms)}</td>
                <td>{fmt(r.replica_hours, 4)}</td>
                <td>
                  <a className="underline" style={{ color: 'var(--accent)' }} href={`/api/lab/experiments/${r.id}`} target="_blank" rel="noreferrer">
                    JSON
                  </a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="text-xs muted mt-2">Pick a baseline (usually Native HPA) and a candidate (FlexaScale) run of the same scenario.</p>
      </div>
      {err && <div style={{ color: 'var(--critical)' }}>{err}</div>}
      {cmp && (
        <div className="card p-4 overflow-x-auto">
          <h3 className="font-semibold text-sm">
            {cmp.baseline.request.controller} ({cmp.baseline.id}) vs {cmp.candidate.request.controller} ({cmp.candidate.id})
          </h3>
          {cmp.comparable ? (
            <p className="text-sm my-2" style={{ color: 'var(--good-text)' }}>
              Comparable runs: same app, scenario, users and spawn rate; durations within 10%.
              {cmp.baseline.preliminary || cmp.candidate.preliminary ? ' Short runs: treat as preliminary evidence.' : ''}
            </p>
          ) : (
            <p className="text-sm my-2" style={{ color: 'var(--serious)' }}>
              Not comparable, percentages hidden: {cmp.issues.join('; ')}
            </p>
          )}
          <table className="data w-full text-sm tnum">
            <thead>
              <tr>
                <th>Metric</th>
                <th>Baseline</th>
                <th>Candidate</th>
                <th>Δ</th>
                <th>Δ %</th>
                <th>Better when</th>
              </tr>
            </thead>
            <tbody>
              {cmp.rows.map((r: Json) => (
                <tr key={r.metric}>
                  <td>{r.metric}</td>
                  <td>{fmt(r.baseline, 4)}</td>
                  <td>{fmt(r.candidate, 4)}</td>
                  <td>{fmt(r.delta, 4)}</td>
                  <td>{r.pct_change == null ? '—' : `${r.pct_change > 0 ? '+' : ''}${fmt(r.pct_change, 1)}%`}</td>
                  <td className="muted">{r.better === 'context' ? 'context only' : r.better}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-xs muted mt-2">
            Cost basis: {cmp.cost_label || 'n/a'}. Allocated = requested CPU/memory of ready replicas; observed = cAdvisor usage. Minikube has no real bill.
          </p>
        </div>
      )}
    </div>
  );
}

function ModelView() {
  const [models] = usePoll<Json>(api.models, 60000);
  if (!models) return <div className="muted">Loading…</div>;
  const sim = models._simulation_evaluation;
  const sim4 = models._simulation_evaluation_v4;
  const cards = Object.entries(models)
    .filter(([k]) => !k.startsWith('_'))
    .sort(([a], [b]) => b.localeCompare(a));
  const ci = (mc: number[] | undefined, d: number, scale = 1) => (mc ? `${fmt(scale * mc[0], d)} ± ${fmt(scale * mc[1], d)}` : '—');
  return (
    <div className="space-y-4">
      {cards.map(([name, card]: [string, Json]) => (
        <div key={name} className="card p-4 text-sm space-y-1">
          <h3 className="font-semibold">models/{name}</h3>
          <div className="ink2">
            {card.model} · {fmt(card.total_timesteps)} timesteps · trained {card.trained_at} · {fmt(card.training_seconds)} s
          </div>
          <div className="ink2">
            Topology: {card.num_services} services ({card.graph?.type} graph) · observation v{card.observation?.version ?? 1}:{' '}
            {card.observation?.per_service_fields?.join(', ')} · reward weights{' '}
            {JSON.stringify(card.environment?.reward_weights)}
          </div>
          <div className="ink2">
            Training data: {card.environment?.dataset_path} ({card.environment?.train_split} split; checkpoint selection on {card.environment?.eval_split}) · demand model{' '}
            {card.environment?.demand_model} · replicas {card.environment?.min_replicas}–{card.environment?.max_replicas}
          </div>
          {card.validation && (
            <div className="ink2">
              Validation mean reward by checkpoint: {card.validation.timesteps.map((t: number, i: number) => `${t}: ${card.validation.mean_reward[i]}`).join(' · ')}
            </div>
          )}
        </div>
      ))}
      {sim4 && (
        <div className="card p-4 overflow-x-auto">
          <h3 className="font-semibold text-sm">
            v4 held-out simulation: dependency-aware simulator, {sim4.episodes} paired episodes on unseen services
          </h3>
          <p className="text-xs muted">Selected model: {sim4.selection?.selected} (by validation reward only).</p>
          <table className="data w-full text-sm tnum mt-2">
            <thead>
              <tr>
                <th>Policy</th>
                <th>Reward / step</th>
                <th>SLO violation rate</th>
                <th>Avg replicas</th>
                <th>Avg CPU %</th>
                <th>Replica changes / step</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(sim4.summary).map(([k, v]: [string, Json]) => (
                <tr key={k}>
                  <td>{k}</td>
                  <td>{ci(v.reward, 3)}</td>
                  <td>{ci(v.slo_violation_rate, 1, 100)}%</td>
                  <td>{ci(v.avg_replicas, 2)}</td>
                  <td>{ci(v.avg_cpu_pct, 1)}</td>
                  <td>{ci(v.replica_changes_per_step, 2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {sim && (
        <div className="card p-4 overflow-x-auto">
          <h3 className="font-semibold text-sm">v2/v3 held-out simulation, original simulator ({sim.episodes} paired episodes, {sim.split} split)</h3>
          <table className="data w-full text-sm tnum mt-2">
            <thead>
              <tr>
                <th>Policy</th>
                <th>Reward / episode</th>
                <th>Latency-SLO violations</th>
                <th>Avg replicas</th>
                <th>Avg CPU %</th>
                <th>Scale actions / step</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(sim.results).map(([k, v]: [string, Json]) => (
                <tr key={k}>
                  <td>{k}</td>
                  <td>
                    {fmt(v.summary.reward.mean, 3)} ± {fmt(v.summary.reward.ci95, 3)}
                  </td>
                  <td>{fmt(100 * v.summary.slo_violation_rate.mean, 1)}%</td>
                  <td>{fmt(v.summary.avg_replicas.mean, 2)}</td>
                  <td>{fmt(v.summary.avg_cpu_pct.mean, 1)}</td>
                  <td>{fmt(v.summary.scale_actions_per_step.mean, 2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-xs muted mt-2">Simulation results do not prove live performance; compare live runs in “Results & comparison”.</p>
        </div>
      )}
    </div>
  );
}
