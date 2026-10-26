import { useEffect, useMemo, useState } from 'react';
import { CONTROLLER_LABEL, Json, api, deltaDigits, fmt, fmtSigned, seriesColor } from '../api';
import { Card, Empty, ErrorNote, Icon, Skeleton, StatusBadge, usePoll } from '../ui';
import { LineChart } from '../LineChart';
import { MIN_PAIRS } from './Overview';

/** The tuned-HPA reference group ("Native HPA, 60 s scale-down") is a baseline variant, not a FlexaScale model. */
const isReference = (model: string) => model.startsWith('Native HPA');
const candidateName = (model: string) => (isReference(model) ? `${model} (tuned reference)` : `FlexaScale ${model}`);

const METRICS: [string, string, string][] = [
  ['replica_hours_pct', 'Replica-hours', '%'],
  ['cost_pct', 'Cost', '%'],
  ['p95_pct', 'p95 latency', '%'],
  ['failure_pp', 'Failure rate', ' pp'],
  ['throughput_pct', 'Throughput', '%'],
];

export function Compare({ app }: { app: string }) {
  const bench = usePoll<Json>(() => api.benchmark(app), 30000, [app]);
  const runs = usePoll<Json>(api.runs, 20000);
  const models: Json[] = bench.data?.models || [];
  const [model, setModel] = useState<string | null>(null);
  const current = models.find((m) => m.model === model) || models.find((m) => String(m.model).includes('Auto')) || models[0];

  return (
    <div className="space-y-4">
      <ErrorNote error={bench.error} what="Benchmark" />
      {bench.loading && !bench.data ? (
        <div className="card p-5 space-y-3"><Skeleton h={14} w="30%" /><Skeleton h={120} /></div>
      ) : !models.length ? (
        <Card title="No paired benchmark yet"><Empty icon="compare">Paired runs appear here once the same scenario has been run with native HPA and then with FlexaScale (same users, spawn rate and duration).</Empty></Card>
      ) : (
        <>
          <Card eyebrow="Paired benchmark" title={`${candidateName(current.model)} vs native HPA (default)`}
            actions={models.length > 1 && (
              <div className="seg" role="group" aria-label="Model">
                {models.map((m) => <button key={m.model} aria-pressed={m.model === current.model} onClick={() => setModel(m.model)}>{m.model}</button>)}
              </div>
            )}>
            <div className="flex flex-wrap items-center gap-2 mb-4 text-sm">
              <StatusBadge level={current.n_pairs < MIN_PAIRS ? 'warning' : current.verdict_level} label={current.n_pairs < MIN_PAIRS ? `Preliminary: ${current.n_pairs} of ≥ ${MIN_PAIRS} pairs needed for a verdict` : current.verdict} />
              <span className="ink2">{current.n_pairs} comparable pairs · {current.scenarios} scenarios · {isReference(current.model)
                ? 'tuned-HPA reference: each tuned run directly follows the default-HPA run it is paired with, same settings (docs/POLICY_V6.md §5.2). It asks whether a shorter scale-down window alone gives the saving, and does not change the Auto verdict.'
                : 'each pair = native-HPA run then the candidate run, same settings, adjacent in time.'} Δ = candidate − default HPA; negative cost/latency/failures is better.</span>
            </div>
            <div className="grid gap-3 grid-cols-2 lg:grid-cols-5">
              {METRICS.map(([k, label, unit]) => {
                const v = current.pooled?.[k];
                return (
                  <div key={k} className="card-flat p-3 min-w-0">
                    <div className="eyebrow">{label}{k === 'cost_pct' && <span className="normal-case tracking-normal font-normal"> · {current.cost_basis}</span>}</div>
                    <div className="text-2xl font-semibold tnum mt-1">{v ? fmtSigned(v.mean, deltaDigits(unit), unit) : '—'}</div>
                    <div className="text-xs muted tnum mt-0.5">{v?.ci95 ? `95% CI ${fmtSigned(v.ci95[0], deltaDigits(unit))} … ${fmtSigned(v.ci95[1], deltaDigits(unit))}` : v ? 'one pair: no interval' : 'not available'}</div>
                  </div>
                );
              })}
            </div>
            <p className="text-xs muted mt-3">{current.verdict_rule}</p>
          </Card>

          <Card eyebrow="By scenario" title={`Δ per pair (dots) and mean (bar), ${isReference(current.model) ? 'tuned HPA' : 'FlexaScale'} − default HPA`}>
            <DeltaChart model={current} />
          </Card>

          <Card eyebrow="Pairs" title="Every comparable pair" pad={false}>
            <div className="overflow-x-auto scroll-thin max-h-[420px]">
              <table className="data w-full text-sm tnum">
                <thead><tr><th>Scenario</th><th>HPA run</th><th>FlexaScale run</th><th>Δ replica-h</th><th>Δ p95</th><th>Δ failures</th><th>Δ throughput</th></tr></thead>
                <tbody>
                  {current.pairs.map((p: Json) => (
                    <tr key={p.candidate}>
                      <td>{p.scenario.replace(/_/g, ' ')}</td>
                      <td className="text-xs muted">{p.baseline}</td><td className="text-xs muted">{p.candidate}</td>
                      <td>{fmtSigned(p.replica_hours_pct, 1, '%')}</td><td>{fmtSigned(p.p95_pct, 1, '%')}</td>
                      <td>{fmtSigned(p.failure_pp, 2, ' pp')}</td><td>{fmtSigned(p.throughput_pct, 1, '%')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
      <ManualCompare runs={runs.data?.runs || []} error={runs.error} />
    </div>
  );
}

function DeltaChart({ model }: { model: Json }) {
  const [metric, setMetric] = useState('replica_hours_pct');
  const [hover, setHover] = useState<string | null>(null);
  const scen: string[] = Array.from(new Set<string>(model.pairs.map((p: Json) => p.scenario))).sort();
  const vals = model.pairs.map((p: Json) => p[metric]).filter((v: number | null) => v != null) as number[];
  if (!vals.length) return <Empty height={120}>No values for this metric.</Empty>;
  const lim = Math.max(5, ...vals.map((v) => Math.abs(v))) * 1.15;
  const W = 1100, rowH = 36, L = 170, R = 190, T = 26;
  const H = T + scen.length * rowH + 22;
  const x = (v: number) => L + ((v + lim) / (2 * lim)) * (W - L - R);
  const unit = METRICS.find(([k]) => k === metric)?.[2] || '';
  return (
    <div>
      <div className="seg mb-3 flex-wrap" role="group" aria-label="Metric">
        {METRICS.map(([k, label]) => <button key={k} aria-pressed={metric === k} onClick={() => setMetric(k)}>{label}</button>)}
      </div>
      <div className="overflow-x-auto scroll-thin">
        <svg viewBox={`0 0 ${W} ${H}`} style={{ minWidth: 560, width: '100%' }} role="img" aria-label="Per-scenario paired differences">
          {[-lim, -lim / 2, 0, lim / 2, lim].map((t) => (
            <g key={t}>
              <line x1={x(t)} x2={x(t)} y1={T - 6} y2={H - 20} stroke={t === 0 ? 'var(--axis)' : 'var(--grid)'} strokeWidth={t === 0 ? 1.5 : 1} />
              <text x={x(t)} y={H - 6} fontSize={11} textAnchor="middle" fill="var(--muted)" className="tnum">{fmtSigned(t, 0, unit)}</text>
            </g>
          ))}
          <text x={x(-lim / 2)} y={12} fontSize={11} textAnchor="middle" fill="var(--muted)">← FlexaScale lower</text>
          <text x={x(lim / 2)} y={12} fontSize={11} textAnchor="middle" fill="var(--muted)">FlexaScale higher →</text>
          {scen.map((s, i) => {
            const ps = model.pairs.filter((p: Json) => p.scenario === s && p[metric] != null);
            const mean = ps.length ? ps.reduce((a: number, p: Json) => a + p[metric], 0) / ps.length : null;
            const y = T + i * rowH + rowH / 2;
            const agree = ps.length > 1 && (ps.every((p: Json) => p[metric] < 0) || ps.every((p: Json) => p[metric] > 0));
            return (
              <g key={s} onMouseEnter={() => setHover(s)} onMouseLeave={() => setHover(null)}>
                <rect x={0} y={y - rowH / 2} width={W} height={rowH} fill={hover === s ? 'var(--surface-2)' : 'transparent'} />
                <text x={L - 12} y={y + 4} fontSize={12.5} textAnchor="end" fill="var(--ink-2)">{s.replace(/_/g, ' ')}</text>
                {mean != null && (
                  <rect x={Math.min(x(0), x(mean))} y={y - 5} width={Math.max(2, Math.abs(x(mean) - x(0)))} height={10} rx={3}
                    fill="var(--flexa)" opacity={0.35} />
                )}
                {ps.map((p: Json, j: number) => (
                  <circle key={j} cx={x(p[metric])} cy={y} r={5} fill="var(--flexa)" stroke="var(--surface)" strokeWidth={2}>
                    <title>{`${p.candidate}: ${fmtSigned(p[metric], 1, unit)}`}</title>
                  </circle>
                ))}
                <text x={W - 8} y={y + 4} fontSize={12} textAnchor="end" fill="var(--ink-2)" className="tnum">
                  {mean != null ? `${fmtSigned(mean, 1, unit)}${ps.length > 1 ? (agree ? ` · ${ps.length}/${ps.length} agree` : ' · mixed') : ''}` : ''}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}

function hashParam(name: string): string {
  const q = window.location.hash.split('?')[1] || '';
  return new URLSearchParams(q).get(name) || '';
}

function ManualCompare({ runs, error }: { runs: Json[]; error: string | null }) {
  const [filter, setFilter] = useState('');
  const [a, setA] = useState(() => hashParam('a'));
  const [b, setB] = useState(() => hashParam('b'));
  useEffect(() => {
    if (a && b) history.replaceState(null, '', `#compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`);
  }, [a, b]);
  const [cmp, setCmp] = useState<Json>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (!a || !b) return;
    setErr(null);
    api.compare(a, b).then(setCmp, (e) => setErr(String(e.message)));
  }, [a, b]);
  const list = useMemo(() => runs.filter((r) => !filter || r.request.scenario === filter || r.request.controller === filter), [runs, filter]);
  const scen = Array.from(new Set(runs.map((r) => r.request.scenario))).sort();
  return (
    <>
      <Card eyebrow="Experiment history" title={`${runs.length} recorded runs`} pad={false}
        actions={<select className="field !w-auto text-sm" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter">
          <option value="">All runs</option>
          <optgroup label="Controller">{['hpa', 'flexascale', 'auto', 'hpa_fast'].map((c) => <option key={c} value={c}>{CONTROLLER_LABEL[c]}</option>)}</optgroup>
          <optgroup label="Scenario">{scen.map((s) => <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>)}</optgroup>
        </select>}>
        <ErrorNote error={error} />
        <div className="overflow-x-auto scroll-thin max-h-[460px]">
          <table className="data w-full text-sm tnum">
            <thead><tr><th>Base</th><th>Cand.</th><th>Run</th><th>Mode</th><th>Scenario</th><th>Users</th><th>State</th><th>Req/s</th><th>p95 ms</th><th>Replica-h</th><th /></tr></thead>
            <tbody>
              {list.map((r) => (
                <tr key={r.id}>
                  <td><input type="radio" name="base" checked={a === r.id} onChange={() => setA(r.id)} aria-label={`baseline ${r.id}`} /></td>
                  <td><input type="radio" name="cand" checked={b === r.id} onChange={() => setB(r.id)} aria-label={`candidate ${r.id}`} /></td>
                  <td className="text-xs">{r.id}</td>
                  <td>{CONTROLLER_LABEL[r.request.controller] || r.request.controller}</td>
                  <td>{r.request.scenario.replace(/_/g, ' ')}</td>
                  <td>{r.request.users}</td>
                  <td><StatusBadge level={r.state === 'completed' ? (r.preliminary ? 'warning' : 'good') : 'critical'} label={r.state + (r.preliminary ? ' · prelim.' : '')} /></td>
                  <td>{fmt(r.throughput_rps, 2)}</td><td>{fmt(r.p95_ms)}</td><td>{fmt(r.replica_hours, 4)}</td>
                  <td><a className="ink2 hover:underline inline-flex items-center gap-1 text-xs" href={`/api/lab/experiments/${r.id}`} target="_blank" rel="noreferrer">JSON <Icon name="external" size={12} /></a></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-xs muted p-4 pt-2">Pick a baseline (usually native HPA) and a candidate run of the same scenario.</p>
      </Card>
      <ErrorNote error={err} />
      {a && b && <RunVsRun a={a} b={b} comparable={cmp?.comparable} issues={cmp?.issues || []} />}
      {cmp && (
        <Card eyebrow="Side by side" title={`${CONTROLLER_LABEL[cmp.baseline.request.controller]} (${cmp.baseline.id}) vs ${CONTROLLER_LABEL[cmp.candidate.request.controller]} (${cmp.candidate.id})`} pad={false}>
          <div className="px-5 pb-2"><StatusBadge level={cmp.comparable ? 'good' : 'warning'} label={cmp.comparable ? 'Comparable runs' : `Not comparable: ${cmp.issues.join('; ')}`} /></div>
          <div className="overflow-x-auto scroll-thin">
            <table className="data w-full text-sm tnum">
              <thead><tr><th>Metric</th><th>Baseline</th><th>Candidate</th><th>Δ</th><th>Δ %</th><th>Better when</th></tr></thead>
              <tbody>
                {cmp.rows.map((r: Json) => (
                  <tr key={r.metric}><td>{r.metric}</td><td>{fmt(r.baseline, 4)}</td><td>{fmt(r.candidate, 4)}</td><td>{fmt(r.delta, 4)}</td>
                    <td>{r.pct_change == null ? '—' : fmtSigned(r.pct_change, 1, '%')}</td><td className="muted">{r.better === 'context' ? 'context only' : r.better}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-xs muted p-4 pt-2">Cost basis: {cmp.cost_label || 'n/a'}. Allocated = requests of ready replicas; observed = cAdvisor usage. Minikube has no real bill: money figures are estimates at the configured list prices.</p>
        </Card>
      )}
    </>
  );
}

/** Longest continuous end-to-end SLA violation, from the saved 5 s samples (a recovery-time measure). */
function longestViolation(samples: Json[]): number | null {
  if (!samples?.length) return null;
  let best = 0;
  let start: number | null = null;
  for (const s of samples) {
    if (s.e2e_slo_violation) {
      const from: number = start ?? s.elapsed;
      start = from;
      best = Math.max(best, s.elapsed - from);
    } else start = null;
  }
  return best;
}

const g = (o: Json, path: string) => path.split('.').reduce((a, k) => (a == null ? a : a[k]), o);

function RunVsRun({ a, b, comparable, issues }: { a: string; b: string; comparable?: boolean; issues: string[] }) {
  const [runs, setRuns] = useState<[Json, Json] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [syncX, setSyncX] = useState<number | null>(null);
  useEffect(() => {
    setRuns(null);
    Promise.all([api.run(a), api.run(b)]).then((r) => setRuns(r as [Json, Json]), (e) => setErr(String(e.message)));
  }, [a, b]);
  if (err) return <ErrorNote error={err} what="Load runs" />;
  if (!runs) return <div className="card p-5 space-y-3"><Skeleton h={14} w="30%" /><Skeleton h={160} /></div>;
  const [ra, rb] = runs;
  const label = (r: Json) => `${CONTROLLER_LABEL[r.request.controller] || r.request.controller} (${r.id.slice(9, 15)})`;
  const colors = [seriesColor(0), seriesColor(1)];
  const overlay = (fn: (s: Json) => number | null) => {
    const xs = Array.from(new Set([...ra.samples, ...rb.samples].map((s: Json) => Math.round(s.elapsed / 5) * 5))).sort((p, q) => p - q);
    const at = (r: Json) => {
      const m = new Map(r.samples.map((s: Json) => [Math.round(s.elapsed / 5) * 5, fn(s)]));
      return xs.map((x) => (m.has(x) ? (m.get(x) as number | null) : null));
    };
    return { x: xs, series: [ra, rb].map((r, i) => ({ key: r.id, label: label(r), color: colors[i], values: at(r) })) };
  };
  const total = (s: Json) => Object.values(s.services || {}).reduce((acc: number, v: Json) => acc + (v.ready || 0), 0) as number;
  const meanCpu = (s: Json) => {
    const v = Object.values(s.services || {}).map((x: Json) => x.cpu_pct).filter((c) => c != null) as number[];
    return v.length ? v.reduce((p, q) => p + q, 0) / v.length : null;
  };
  const cost = (r: Json) => (g(r, 'summary.resources.cost_model') === 'priced'
    ? { v: g(r, 'summary.resources.estimated_cost'), unit: `${g(r, 'summary.resources.cost_currency') || 'USD'} (est.)` }
    : { v: g(r, 'summary.resources.resource_cost_proxy'), unit: 'proxy' });
  const rows: [string, (r: Json) => number | null, number, string, 'lower' | 'higher' | 'context'][] = [
    ['Throughput', (r) => g(r, 'summary.workload.throughput_rps'), 2, 'req/s', 'higher'],
    ['p50 latency', (r) => g(r, 'summary.workload.p50_ms'), 0, 'ms', 'lower'],
    ['p95 latency', (r) => g(r, 'summary.workload.p95_ms'), 0, 'ms', 'lower'],
    ['p99 latency', (r) => g(r, 'summary.workload.p99_ms'), 0, 'ms', 'lower'],
    ['Failure rate', (r) => g(r, 'summary.workload.failure_rate_pct'), 2, '%', 'lower'],
    ['SLA violation time', (r) => g(r, 'summary.slo.e2e_violation_seconds'), 0, 's', 'lower'],
    ['Longest violation (recovery)', (r) => longestViolation(r.samples), 0, 's', 'lower'],
    ['Avg CPU', (r) => g(r, 'summary.utilization.avg_cpu_pct_of_request'), 1, '% req', 'context'],
    ['Peak CPU', (r) => g(r, 'summary.utilization.peak_cpu_pct_of_request'), 1, '% req', 'context'],
    ['Avg memory', (r) => g(r, 'summary.utilization.avg_memory_pct'), 1, '% limit', 'context'],
    ['Avg replicas', (r) => g(r, 'summary.replicas.avg_total_desired'), 2, '', 'lower'],
    ['Peak replicas', (r) => g(r, 'summary.replicas.peak_total_desired'), 0, '', 'lower'],
    ['Replica-hours', (r) => g(r, 'summary.resources.replica_hours'), 4, 'h', 'lower'],
    ['Scaling events', (r) => g(r, 'summary.stability.scaling_events'), 0, '', 'context'],
    ['Oscillations', (r) => g(r, 'summary.stability.oscillations'), 0, '', 'lower'],
    ['Cost', (r) => cost(r).v, 5, cost(ra).unit === cost(rb).unit ? cost(ra).unit : 'mixed basis', 'lower'],
  ];
  const sameBasis = cost(ra).unit === cost(rb).unit;
  const valid = (r: Json) => g(r, 'summary.complete') && !g(r, 'summary.preliminary') && g(r, 'summary.settled_start') !== false && r.cleanup?.safe !== false;
  return (
    <Card eyebrow="Run vs run" title={`${label(ra)} vs ${label(rb)} · ${ra.request.scenario.replace(/_/g, ' ')}`}
      actions={<StatusBadge level={comparable ? 'good' : 'warning'} label={comparable ? 'comparable' : 'not comparable'} />}>
      <div className="flex flex-wrap gap-2 mb-3 text-xs">
        {[ra, rb].map((r, i) => (
          <span key={r.id} className="pill"><span className="dot" style={{ background: colors[i] }} />{r.id}
            <StatusBadge level={valid(r) ? 'good' : 'warning'} label={valid(r) ? 'valid' : 'check validity'} /></span>
        ))}
        {!comparable && issues.length > 0 && <span className="pill" style={{ color: 'var(--serious)' }}>{issues.join('; ')}</span>}
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <LineChart title="Throughput" unit="req/s" digits={1} {...overlay((s) => s.rps ?? null)} syncX={syncX} onSyncX={setSyncX} height={170} />
        <LineChart title="p95 latency" unit="ms" {...overlay((s) => s.p95_ms ?? null)} syncX={syncX} onSyncX={setSyncX} height={170}
          reference={ra.slo?.e2e_p95_ms ? { value: ra.slo.e2e_p95_ms, label: 'SLO' } : undefined} />
        <LineChart title="Ready replicas (all services)" unit="replicas" step {...overlay(total)} syncX={syncX} onSyncX={setSyncX} height={170} minMax={5} />
        <LineChart title="Mean CPU" unit="% of request" {...overlay(meanCpu)} syncX={syncX} onSyncX={setSyncX} height={170} />
        <LineChart title="Failures" unit="failures / s" digits={1} {...overlay((s) => s.fail_rps ?? null)} syncX={syncX} onSyncX={setSyncX} height={170} />
      </div>
      <div className="overflow-x-auto scroll-thin mt-4">
        <table className="data w-full text-sm tnum">
          <thead><tr><th>Metric</th><th className="text-right">{label(ra)}</th><th className="text-right">{label(rb)}</th><th className="text-right">Δ</th><th>Better when</th></tr></thead>
          <tbody>
            {rows.map(([name, fn, d, unit, better]) => {
              const va = fn(ra), vb = fn(rb);
              const delta = va != null && vb != null && (name !== 'Cost' || sameBasis) ? vb - va : null;
              return (
                <tr key={name}>
                  <td>{name}{unit && <span className="muted text-xs"> · {unit}</span>}</td>
                  <td className="text-right">{fmt(va, d)}</td><td className="text-right">{fmt(vb, d)}</td>
                  <td className="text-right">{delta == null ? '—' : fmtSigned(delta, d)}</td>
                  <td className="muted">{better === 'context' ? 'context only' : better}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="text-xs muted mt-2">Saved results (run.json), not live data. “Longest violation” is the longest continuous stretch with p95 above the end-to-end SLO, from 5 s samples. Cost: estimated at the configured list prices when priced, otherwise the unitless proxy; never a cloud bill. Costs with different bases are not differenced.</p>
    </Card>
  );
}
