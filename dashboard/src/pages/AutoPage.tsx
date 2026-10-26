import { useEffect, useMemo, useState } from 'react';
import { Json, OWNER_COLOR, TERMINAL, api, fmt, fmtAgo, fmtElapsed } from '../api';
import { Card, Empty, ErrorNote, Icon, OwnerBadge, Skeleton, StatusBadge, usePoll } from '../ui';

const RULES: { id: string; title: string; owner: string; text: (c: Json, p: Json) => string; immediate: boolean }[] = [
  { id: 'controller_health', title: 'Controller health', owner: 'hpa', immediate: true,
    text: () => 'No trained model, missing or stale CPU telemetry, or FlexaScale does not hold the application Lease → native HPA.' },
  { id: 'policy_confidence', title: 'Policy confidence', owner: 'hpa', immediate: false,
    text: (_c, p) => `Policy probability for its action below ${fmt(p?.confidence_threshold, 2)} to take over, or below ${fmt(p?.deactivation_threshold, 2)} once it owns the service → native HPA.` },
  { id: 'sla_risk', title: 'SLA risk: capacity first', owner: 'hpa', immediate: true,
    text: (c) => `Mean latency above ${fmt(c?.sla_latency_ratio ?? 1, 2)} × the service SLO, or CPU ≥ ${fmt(c?.cpu_risk_pct ?? 85)}% of request, and HPA would run more replicas than FlexaScale proposes → native HPA.` },
  { id: 'efficiency', title: 'Efficiency', owner: 'flexascale', immediate: false,
    text: () => 'Otherwise FlexaScale owns the service; its proposal still passes every safety guard (bounds, budget, cooldowns, no scale-down under CPU or latency pressure).' },
];

/** The Auto-mode run to show: the active one if it is an Auto run, else the most recent saved Auto run. */
function useAutoRun(active: Json): { run: Json; saved: boolean; loading: boolean; error: string | null } {
  const runs = usePoll<Json>(api.runs, 30000);
  const activeIsAuto = active?.request?.controller === 'auto';
  const latestId: string | undefined = useMemo(
    () => (runs.data?.runs || []).find((r: Json) => r.request?.controller === 'auto' && r.state === 'completed')?.id,
    [runs.data],
  );
  const [saved, setSaved] = useState<Json>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (activeIsAuto || !latestId || saved?.id === latestId) return;
    api.run(latestId).then(setSaved, (e) => setErr(String(e.message)));
  }, [activeIsAuto, latestId, saved?.id]);
  if (activeIsAuto) return { run: active, saved: false, loading: false, error: null };
  return { run: saved, saved: true, loading: runs.loading || (!!latestId && !saved), error: err || runs.error };
}

export function AutoPage({ live, active, onNavigate }: { live: Json; active: Json; onNavigate: (p: string) => void }) {
  const policy = live?.policy || {};
  const cfg = policy.auto || {};
  const { run, saved, loading, error } = useAutoRun(active);
  const state: Record<string, Json> = run?.auto_state || {};
  const counts: Record<string, number> = run?.auto_counts || {};
  const total = Object.values(counts).reduce((a, b) => a + (b as number), 0);
  const running = !!run && !saved && !TERMINAL.includes(run.state);
  const services: Json[] = (live?.services || []).filter((s: Json) => s.eligible);
  const byName: Record<string, Json> = Object.fromEntries(services.map((s) => [s.name, s]));
  const lastSample = run?.samples?.[run.samples.length - 1];
  const handoffs: Record<string, Json> = {};
  for (const e of run?.events || []) if (e.kind === 'auto' && e.service) handoffs[e.service] = e;
  const handoffCount = (run?.events || []).filter((e: Json) => e.kind === 'auto' && e.service).length;
  const fsOwned = Object.values(state).filter((d: Json) => d.owner === 'flexascale').length;

  return (
    <div className="space-y-4">
      <Card eyebrow="Auto mode" title="Explainable per-service choice between FlexaScale and native HPA"
        actions={<button className="btn btn-primary text-sm" onClick={() => onNavigate('live')}><Icon name="play" size={13} />Run in Auto mode</button>}>
        <p className="text-sm ink2 leading-relaxed max-w-5xl">
          Every operator step (every {fmt(policy.poll_interval_seconds)} s), for each service, FlexaScale's proposal and native HPA's
          recommendation (<code>ceil(replicas × CPU / {fmt(policy.cpu_target_pct)}%)</code>) are computed from the same telemetry. The rules are
          checked in order; the first that applies decides the owner. A <b>recommendation</b> is not an action: only the owner's change is sent to
          Kubernetes. Ownership is exclusive: FlexaScale freezes a service's HPA (min = max) before scaling it and restores the original bounds on
          hand-back, under one Lease per application. Stopping a run, losing the Lease or the operator exiting returns every service to native HPA.
        </p>
      </Card>

      <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-4">
        {RULES.map((r, i) => {
          const n = counts[r.id] || 0;
          return (
            <Card key={r.id} eyebrow={`Rule ${i + 1}`} title={r.title}
              actions={<span className="pill"><span className="dot" style={{ background: OWNER_COLOR[r.owner] }} />→ {r.owner === 'hpa' ? 'HPA' : 'FlexaScale'}</span>}>
              <p className="text-sm ink2 leading-relaxed">{r.text(cfg, policy)}</p>
              <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                <span className="pill">{r.immediate ? 'applies immediately' : `after ${fmt(cfg.dwell_steps ?? 2)} consecutive steps`}</span>
                {total > 0 && <span className="pill tnum">{fmt(n)} decisions · {fmt((100 * n) / total)}%</span>}
              </div>
              {total > 0 && (
                <div className="mt-3 h-1.5 rounded-full overflow-hidden" style={{ background: 'var(--surface-3)' }} aria-hidden>
                  <div className="h-full rounded-full" style={{ width: `${(100 * n) / total}%`, background: OWNER_COLOR[r.owner] }} />
                </div>
              )}
            </Card>
          );
        })}
      </div>

      <Card eyebrow={run ? (saved ? `Saved result · ${run.id}` : `Live · ${run.id}`) : 'Auto mode'}
        title={run ? (running ? 'Who owns each service right now, and why' : 'Final ownership of the most recent Auto run') : 'No Auto-mode run recorded yet'}
        actions={run && (
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <StatusBadge level={running ? 'good' : 'unknown'} label={running ? `running · ${fmtElapsed(lastSample?.elapsed)}` : `finished ${fmtAgo(run.ended_at)}`} />
            <span className="pill tnum">{fsOwned}/{Object.keys(state).length} FlexaScale</span>
            <span className="pill tnum">{handoffCount} ownership changes</span>
          </div>
        )} pad={false}>
        <div className="px-5 pb-2"><ErrorNote error={error} /></div>
        {loading && !run ? (
          <div className="p-5 space-y-2">{Array.from({ length: 6 }, (_, i) => <Skeleton key={i} h={18} />)}</div>
        ) : !run || Object.keys(state).length === 0 ? (
          <Empty icon="auto">Start an experiment in Auto mode from the Live lab; each service's owner, the rule that chose it and the reason appear here.</Empty>
        ) : (
          <div className="overflow-x-auto scroll-thin">
            <table className="data w-full text-sm">
              <thead>
                <tr>
                  <th>Service</th><th>Decision · rule · logged reason</th>
                  <th className="text-right" title="Recommendations: what each controller would set">FlexaScale → / HPA →</th>
                  <th className="text-right" title="What Kubernetes has now">Desired / ready</th>
                  <th className="text-right">CPU %</th><th className="text-right">Mem %</th><th className="text-right">Latency / SLO</th>
                  <th className="text-right">Conf.</th><th>Telemetry</th><th>Last change</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(state).sort(([a], [b]) => a.localeCompare(b)).map(([svc, d]) => {
                  const liveSvc = byName[svc];
                  const sample = lastSample?.services?.[svc];
                  const desired = running ? liveSvc?.desired_replicas : sample?.desired;
                  const ready = running ? liveSvc?.ready_replicas : sample?.ready;
                  const m = running ? liveSvc?.metrics || {} : { cpu_pct: sample?.cpu_pct, memory_pct: sample?.memory_pct, latency_mean_ms: sample?.latency_ms, stale: sample?.stale };
                  const slo = d.inputs?.slo_ms;
                  const over = slo && m.latency_mean_ms != null && m.latency_mean_ms > slo;
                  const h = handoffs[svc];
                  return (
                    <tr key={svc}>
                      <td className="font-medium">{svc}</td>
                      <td className="whitespace-normal min-w-[340px] max-w-[460px]">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <OwnerBadge owner={d.owner} compact />
                          <span className="pill">{String(d.rule).replace(/_/g, ' ')}</span>
                          {d.candidate && d.candidate !== d.owner && <span className="text-xs muted">→ {d.candidate === 'flexascale' ? 'FlexaScale' : 'HPA'} pending</span>}
                        </div>
                        <div className="text-xs ink2 mt-1 leading-relaxed">{d.reason}</div>
                      </td>
                      <td className="text-right tnum">{d.flexascale_proposal ?? '—'} / {d.hpa_recommendation ?? '—'}</td>
                      <td className="text-right tnum">{desired ?? '—'} / {ready ?? '—'}</td>
                      <td className="text-right tnum" style={m.cpu_pct >= (cfg.cpu_risk_pct ?? 85) ? { color: 'var(--serious)' } : undefined}>{fmt(m.cpu_pct)}</td>
                      <td className="text-right tnum">{fmt(m.memory_pct)}</td>
                      <td className="text-right tnum">
                        {over && <Icon name="error" size={12} style={{ color: 'var(--critical)' }} className="inline mr-1 -mt-0.5" />}
                        {fmt(m.latency_mean_ms)} / {fmt(slo)} ms
                      </td>
                      <td className="text-right tnum">{fmt(d.inputs?.confidence, 3)}</td>
                      <td>{m.stale ? <StatusBadge level="critical" label="stale" /> : m.cpu_pct == null ? <StatusBadge level="warning" label="missing" /> : <StatusBadge level="good" label="fresh" />}</td>
                      <td className="text-xs ink2 tnum">{h ? `${fmtElapsed(h.elapsed)} → ${h.owner === 'flexascale' ? 'FlexaScale' : 'HPA'}` : '—'}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <p className="text-xs muted px-5 py-3">
          {saved ? 'Saved result: the last decision of each service in that run, with the telemetry of its final sample. ' : 'Live: Kubernetes state and telemetry refresh every 5 s; decisions every operator step. '}
          Cooldown timers are enforced by the operator but not exported, so they are not shown.
        </p>
      </Card>

      <div className="grid gap-4 xl:grid-cols-[1fr_380px]">
        <Card eyebrow="Ownership changes" title="Hand-offs between controllers (logged events)">
          <HandoffLog events={(run?.events || []).filter((e: Json) => e.kind === 'auto' && e.service)} />
        </Card>
        <Card eyebrow="Configuration" title="Policy file → auto">
          <dl className="text-sm grid grid-cols-[1fr_auto] gap-x-4 gap-y-2 tnum">
            {[
              ['Latency risk', `> ${fmt(cfg.sla_latency_ratio ?? 1, 2)} × SLO (${fmt(policy.slo_latency_ms)} ms)`],
              ['CPU risk', `≥ ${fmt(cfg.cpu_risk_pct ?? 85)}% of request`],
              ['Switch to FlexaScale after', `${fmt(cfg.dwell_steps ?? 2)} steps`],
              ['Take over at confidence', fmt(policy.confidence_threshold, 2)],
              ['Hand back below', fmt(policy.deactivation_threshold, 2)],
              ['HPA target / tolerance', `${fmt(cfg.hpa_target_pct ?? policy.cpu_target_pct)}% ± ${fmt(100 * (cfg.hpa_tolerance ?? 0.1))}%`],
            ].map(([k, v]) => (
              <div key={k} className="contents"><dt className="ink2">{k}</dt><dd className="text-right font-semibold">{v}</dd></div>
            ))}
          </dl>
          <p className="text-xs muted mt-3">Edit the <code>auto:</code> block of <code>config/apps/&lt;app&gt;.yaml</code>; the operator validates it at start and refuses invalid values. Changes apply to the next run.</p>
          <div className="mt-3"><StatusBadge level={policy.auto_valid === false ? 'critical' : 'good'} label={policy.auto_valid === false ? 'invalid configuration' : 'configuration valid'} /></div>
        </Card>
      </div>
    </div>
  );
}

function HandoffLog({ events }: { events: Json[] }) {
  if (!events.length) return <Empty height={100}>No ownership changes recorded.</Empty>;
  return (
    <ol className="space-y-1.5 max-h-[320px] overflow-y-auto scroll-thin pr-1 text-sm">
      {events.slice().reverse().map((e, i) => (
        <li key={i} className="flex gap-3 items-baseline min-w-0">
          <span className="tnum muted w-12 shrink-0 text-right text-xs">{fmtElapsed(e.elapsed)}</span>
          <OwnerBadge owner={e.owner} compact />
          <span className="ink2 min-w-0 break-words">{e.message}</span>
        </li>
      ))}
    </ol>
  );
}
