import { useMemo, useState } from 'react';
import { CONTROLLER_LABEL, Json, api, fmt, fmtMoney, isNativeHpa } from '../api';
import { Card, Empty, ErrorNote, Icon, KV, Skeleton, StatusBadge, usePoll } from '../ui';
import { ScalingTimeline } from '../timeline/ScalingTimeline';
import { feedOfRun, useRun } from '../timeline/feeds';

/** A run counts for comparisons only if all of these hold (the lab's comparability rules). */
function validity(r: Json): { ok: boolean; reasons: string[] } {
  const reasons: string[] = [];
  if (r.state !== 'completed') reasons.push(`state ${r.state}`);
  if (!r.complete) reasons.push('incomplete load window');
  if (r.settled_start === false) reasons.push('unsettled start');
  if (r.cleanup_safe === false) reasons.push('cleanup not verified');
  if (r.on_battery_samples) reasons.push(`${r.on_battery_samples} samples on battery`);
  return { ok: reasons.length === 0, reasons };
}

export function Experiments({ app, meta, onNavigate }: { app: string; meta: Json; onNavigate: (p: string) => void }) {
  const runs = usePoll<Json>(api.runs, 15000);
  const [controller, setController] = useState('');
  const [scenario, setScenario] = useState('');
  const [onlyValid, setOnlyValid] = useState(false);
  const [q, setQ] = useState('');
  const [selected, setSelected] = useState<string | null>(() => new URLSearchParams(window.location.hash.split('?')[1] || '').get('run'));
  const [baseline, setBaseline] = useState<string | null>(null);
  const all: Json[] = (runs.data?.runs || []).filter((r: Json) => r.request?.app === app);
  const shown = useMemo(() => all.filter((r) => (!controller || r.request.controller === controller) && (!scenario || r.request.scenario === scenario)
    && (!onlyValid || validity(r).ok) && (!q || r.id.includes(q) || String(r.block || '').includes(q))), [all, controller, scenario, onlyValid, q]);
  const controllers = Array.from(new Set(all.map((r) => r.request.controller))).sort();
  const scenarios = Array.from(new Set(all.map((r) => r.request.scenario))).sort();
  const { run, error, loading } = useRun(selected);
  const feed = useMemo(() => feedOfRun(run, 'replay'), [run]);

  const select = (id: string) => {
    setSelected(id);
    window.history.replaceState(null, '', `#experiments?run=${encodeURIComponent(id)}`);
  };

  return (
    <div className="grid gap-4 2xl:grid-cols-[minmax(600px,700px)_1fr]">
      <Card eyebrow="Experiment history" title={`${shown.length} of ${all.length} saved runs`} pad={false}
        actions={<button className="btn btn-ghost !p-2" onClick={runs.reload} aria-label="Reload"><Icon name="refresh" size={15} /></button>}>
        <div className="px-4 sm:px-5 pb-3 grid grid-cols-2 gap-2">
          <select className="field text-sm" value={controller} onChange={(e) => setController(e.target.value)} aria-label="Controller">
            <option value="">All controllers</option>
            {controllers.map((c) => <option key={c} value={c}>{CONTROLLER_LABEL[c] || c}</option>)}
          </select>
          <select className="field text-sm" value={scenario} onChange={(e) => setScenario(e.target.value)} aria-label="Scenario">
            <option value="">All scenarios</option>
            {scenarios.map((s) => <option key={s} value={s}>{meta?.scenarios?.[s]?.title || s}</option>)}
          </select>
          <input className="field text-sm" placeholder="Search id or block" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search" />
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={onlyValid} onChange={(e) => setOnlyValid(e.target.checked)} />valid only</label>
        </div>
        <ErrorNote error={runs.error} what="Runs" />
        {runs.loading && !runs.data ? (
          <div className="p-5 space-y-2">{Array.from({ length: 6 }, (_, i) => <Skeleton key={i} h={28} />)}</div>
        ) : shown.length === 0 ? (
          <Empty icon="history">No saved runs match. Runs are written to reports/experiments/ when an experiment ends.</Empty>
        ) : (
          <div className="overflow-auto scroll-thin max-h-[calc(100vh-260px)]">
            <table className="data w-full text-sm tnum">
              <thead><tr><th>Run</th><th>Controller</th><th className="text-right">req/s</th><th className="text-right">p95 ms</th><th className="text-right">replica-h</th><th>Validity</th></tr></thead>
              <tbody>
                {shown.map((r) => {
                  const v = validity(r);
                  return (
                    <tr key={r.id} onClick={() => select(r.id)} className="cursor-pointer" aria-selected={selected === r.id}
                      style={selected === r.id ? { background: 'var(--accent-soft)' } : undefined}>
                      <td className="max-w-[200px]">
                        <div className="truncate font-medium" title={r.id}>{r.request.scenario.replace(/_/g, ' ')}</div>
                        <div className="text-xs muted truncate">{r.started_at ? new Date(r.started_at * 1000).toLocaleString() : r.id.slice(0, 15)}{r.block ? ` · ${r.block}` : ''}</div>
                      </td>
                      <td>
                        <span className="pill"><span className="dot" style={{ background: isNativeHpa(r.request.controller) ? 'var(--hpa)' : r.request.controller === 'auto' ? 'var(--auto)' : 'var(--flexa)' }} />
                          {CONTROLLER_LABEL[r.request.controller] || r.request.controller}</span>
                      </td>
                      <td className="text-right">{fmt(r.throughput_rps, 1)}</td>
                      <td className="text-right">{fmt(r.p95_ms)}</td>
                      <td className="text-right">{fmt(r.replica_hours, 3)}</td>
                      <td title={v.reasons.join('; ') || 'complete, settled start, cleanup verified'}>
                        {v.ok ? <StatusBadge level="good" label={r.preliminary ? 'valid · short' : 'valid'} /> : <StatusBadge level={r.state === 'failed' ? 'critical' : 'warning'} label={v.reasons[0]} />}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <div className="space-y-4 min-w-0">
        {!selected ? (
          <Card><Empty icon="history" height={280}>Select a run to see its configuration, validity checks and a replay of its scaling timeline.</Empty></Card>
        ) : loading && !run ? (
          <Card><Skeleton h={320} /></Card>
        ) : error ? (
          <ErrorNote error={error} what={selected} />
        ) : run ? (
          <>
            <RunDetail run={run} row={all.find((r) => r.id === run.id)} baseline={baseline} onBaseline={setBaseline} onNavigate={onNavigate} />
            <ScalingTimeline feed={feed} title="Scaling timeline (replay)" />
          </>
        ) : null}
      </div>
    </div>
  );
}

function RunDetail({ run, row, baseline, onBaseline, onNavigate }: { run: Json; row?: Json; baseline: string | null; onBaseline: (id: string | null) => void; onNavigate: (p: string) => void }) {
  const s = run.summary || {};
  const w = s.workload || {};
  const res = s.resources || {};
  const req = run.request || {};
  const v = validity(row || { ...run, complete: s.complete, cleanup_safe: run.cleanup?.safe });
  const hosts = (run.samples || []).map((x: Json) => x.host).filter(Boolean);
  const battery = hosts.filter((h: Json) => h.on_ac === false).length;
  return (
    <Card eyebrow={`${CONTROLLER_LABEL[req.controller] || req.controller} · ${req.scenario?.replace(/_/g, ' ')}`} title={run.id}
      actions={
        <div className="flex gap-2 flex-wrap">
          {baseline && baseline !== run.id ? (
            <button className="btn btn-primary text-xs" onClick={() => onNavigate(`compare?a=${encodeURIComponent(baseline)}&b=${encodeURIComponent(run.id)}`)}>
              Compare with baseline <Icon name="compare" size={13} />
            </button>
          ) : null}
          <button className="btn text-xs" onClick={() => onBaseline(baseline === run.id ? null : run.id)}>{baseline === run.id ? 'Baseline selected ✓' : 'Use as baseline'}</button>
        </div>
      }>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-3 text-sm">
        <KV k="State" v={<StatusBadge level={run.state === 'completed' ? 'good' : run.state === 'failed' ? 'critical' : 'warning'} label={run.state} />} />
        <KV k="Users / spawn" v={`${req.users} / ${req.spawn_rate}/s`} mono />
        <KV k="Duration" v={`${req.duration} s (measured ${fmt(s.actual_duration_s)} s)`} mono wrap />
        <KV k="Comparable start" v={req.reset_replicas ? 'yes' : 'no'} />
        <KV k="Cleanup" v={run.cleanup?.safe ? 'verified safe' : run.cleanup ? 'NOT verified' : '—'} />
        <KV k="Host power" v={hosts.length ? (battery ? `${battery} samples on battery` : 'AC throughout') : 'not recorded'} wrap />
        <KV k="Throughput" v={`${fmt(w.throughput_rps, 2)} req/s`} mono />
        <KV k="p50 / p90 / p95 / p99" v={`${fmt(w.p50_ms)} / ${fmt(w.p90_ms)} / ${fmt(w.p95_ms)} / ${fmt(w.p99_ms)} ms`} mono wrap />
        <KV k="Failures" v={`${fmt(w.failure_rate_pct, 2)}% of ${fmt(w.total_requests)} requests`} mono wrap />
        <KV k="Replica-hours" v={fmt(res.replica_hours, 4)} mono />
        <KV k={res.cost_model === 'priced' ? 'Estimated cost' : 'Cost proxy'} v={res.cost_model === 'priced' ? fmtMoney(res.estimated_cost, res.cost_currency, 5) : fmt(res.resource_cost_proxy, 5)} mono />
        <KV k="SLA violated" v={s.slo?.e2e_violation_seconds != null ? `${fmt(s.slo.e2e_violation_seconds)} s` : '—'} mono />
        {req.controller === 'hpa_tuned' && <KV k="HPA settings" v={`${req.hpa_cpu_target_pct}% CPU, ${req.hpa_scale_down_window_s} s window`} />}
        {req.policy_variant && <KV k="Policy variant" v={req.policy_variant} />}
        {req.block && <KV k="Block" v={req.block} />}
        {run.model?.model_path && <div className="col-span-2 sm:col-span-3"><KV k="Model" v={String(run.model.model_path).replace(/\\/g, '/')} wrap mono /></div>}
      </div>
      {!v.ok && <p className="text-xs mt-3" style={{ color: 'var(--serious)' }}>Not used in comparisons: {v.reasons.join('; ')}.</p>}
      {run.error && <div className="mt-3"><ErrorNote error={run.error} /></div>}
      <p className="text-xs muted mt-3">Raw data: reports/experiments/{run.id}/run.json, telemetry.csv, decisions.jsonl and the Locust CSVs. Every number above is recomputed from them by scripts/build_live_report.py.</p>
    </Card>
  );
}
