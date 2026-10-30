import { Json, fmt } from '../api';
import { Card, Empty, KV, Skeleton, StatusBadge, usePoll } from '../ui';
import { api } from '../api';

const ci = (mc: number[] | undefined, d: number, scale = 1) => (mc ? `${fmt(scale * mc[0], d)} ± ${fmt(scale * mc[1], d)}` : '—');

export function Models({ deployed, live }: { deployed?: string; live?: Json }) {
  const { data: models, error } = usePoll<Json>(api.models, 60000);
  if (error) return <Card title="Models"><Empty icon="error">{error}</Empty></Card>;
  if (!models) return <div className="card p-5 space-y-3"><Skeleton h={14} w="30%" /><Skeleton h={80} /></div>;
  const cards = Object.entries(models).filter(([k]) => !k.startsWith('_')).sort(([a], [b]) => b.localeCompare(a));
  const sims = (['_simulation_evaluation_v6', '_simulation_evaluation_v5', '_simulation_evaluation_v4'] as const).filter((k) => models[k]);
  const card = deployed ? models[deployed] : null;
  const op = live?.operator;
  const opModel = op?.model;
  const services = (live?.services || []).filter((s: Json) => s.eligible).length;
  const slots = card?.num_services;
  const graphModel = card?.observation?.version === 3 || String(card?.policy?.class || '').includes('Graph');
  const nMax = card?.observation?.n_max;
  return (
    <div className="space-y-4">
      <Card eyebrow="Deployed policy & inference" title={deployed ? `models/${deployed}` : 'No model configured'}
        actions={<StatusBadge level={!deployed ? 'critical' : card ? 'good' : 'critical'} label={!deployed ? 'not configured' : card ? 'artifact + model card present' : 'model card missing'} />}>
        <div className="grid gap-x-6 gap-y-4 grid-cols-1 sm:grid-cols-2 2xl:grid-cols-4 text-sm">
          <KV wrap k="Artifact" v={<span title={live?.policy?.model_path}>{live?.policy?.model_path || '—'}</span>} />
          <KV wrap k="Policy type" v={card ? (graphModel ? `PPO + graph network (${card.policy?.rounds ?? 2} message-passing rounds on the call graph), one decision per service`
            : `${card.model?.includes('GNN') ? 'PPO + GNN' : 'PPO'}${card.observation?.decision_slot === 0 ? ', per-service (focal)' : ''}`) : '—'} />
          <KV k="Actions" v={card?.action?.deltas ? card.action.deltas.map((d: number) => (d > 0 ? `+${d}` : `${d}`)).join(' ') + ' replicas' : '−1 0 +1 replicas'} />
          <KV k="Observation" v={card ? (graphModel ? `v3 · ${card.observation?.per_service_fields?.length ?? '?'} unit-free inputs per service`
            : `v${card.observation?.version ?? 1} · ${card.observation?.dim ?? '?'} inputs`) : '—'} />
          <KV wrap k="Topology compatibility" v={graphModel && nMax && services
            ? (services <= nMax ? <StatusBadge wrap level="good" label={`${services} services ≤ ${nMax} graph slots: every service, real call graph`} />
              : <StatusBadge wrap level="critical" label={`${services} services > ${nMax} slots: not compatible`} />)
            : slots && services ? (services === slots ? `${services} services: direct` : `${services} services → ${slots}-service neighbourhood windows`) : '—'} />
          <KV wrap k="Inference (operator)" v={op ? (opModel ? <StatusBadge level="good" label={`loaded · ${op.effective_mode} · step ${op.step}`} /> : <StatusBadge wrap level="critical" label={`unavailable: ${op.model_error || 'unknown'}`} />)
            : <span className="muted">no operator running (loaded per experiment)</span>} />
          <KV k="Loaded model sha256" v={opModel?.sha256 ? <span className="tnum" title={opModel.sha256}>{String(opModel.sha256).slice(0, 16)}…</span> : '—'} />
          <KV wrap k="Fallback" v="CPU-threshold heuristic if the model cannot load; live mode refused" />
        </div>
        {op?.last_error && <p className="text-xs mt-3" style={{ color: 'var(--critical)' }}>Operator error: {op.last_error}</p>}
      </Card>
      {sims.map((k) => {
        const s = models[k];
        const ver = k.slice(-2);
        return (
          <Card key={k} eyebrow={`Held-out simulation · ${ver}`} title={`${s.episodes} paired test episodes${s.seeds ? ` (seeds ${s.seeds[0]}–${s.seeds[1]})` : ''}`} pad={false}>
            <p className="text-xs muted px-5 -mt-1 mb-2">Selected: {s.selection?.selected} (validation reward only). ± = 95% confidence half-width. A simulator result does not prove live performance.</p>
            <div className="overflow-x-auto scroll-thin">
              <table className="data w-full text-sm tnum">
                <thead><tr><th>Policy</th><th>Reward / step</th><th>SLO violations</th><th>Avg replicas</th><th>Avg CPU %</th><th>Changes / step</th></tr></thead>
                <tbody>
                  {Object.entries(s.summary).map(([name, v]: [string, Json]) => (
                    <tr key={name} style={name.startsWith('ppo_' + ver) && !name.includes('no_') ? { background: 'var(--accent-soft)' } : undefined}>
                      <td>{name}</td><td>{ci(v.reward, 3)}</td><td>{ci(v.slo_violation_rate, 1, 100)}%</td><td>{ci(v.avg_replicas, 2)}</td><td>{ci(v.avg_cpu_pct, 1)}</td><td>{ci(v.replica_changes_per_step, 2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        );
      })}
      <div className="grid gap-4 lg:grid-cols-2">
        {cards.map(([name, card]: [string, Json]) => card.training?.runs ? <TwinCard key={name} name={name} card={card} deployed={deployed} /> : (
          <Card key={name} eyebrow={name === deployed ? 'Deployed' : 'Model'} title={`models/${name}`}>
            <dl className="text-sm grid grid-cols-[140px_1fr] gap-x-3 gap-y-1.5">
              <dt className="muted">Model</dt><dd>{card.model}</dd>
              <dt className="muted">Training</dt><dd className="tnum">{fmt(card.total_timesteps)} steps · {card.training_seconds > 0 ? `${fmt(card.training_seconds)} s` : 'duration n/a (host clock changed during training)'} · {card.trained_at}</dd>
              <dt className="muted">Simulator</dt><dd>{card.environment?.env_class || 'FlexaScaleEnv'}{card.environment?.control_step_seconds ? ` · ${card.environment.control_step_seconds} s decisions` : ''}</dd>
              <dt className="muted">Actions</dt><dd>{card.action?.deltas ? card.action.deltas.map((d: number) => (d > 0 ? `+${d}` : `${d}`)).join(', ') : '−1, 0, +1'} replicas</dd>
              <dt className="muted">Observation</dt><dd>v{card.observation?.version ?? 1}: {card.observation?.per_service_fields?.join(', ')}</dd>
              <dt className="muted">Reward weights</dt><dd className="tnum">{Object.entries(card.environment?.reward_weights || {}).map(([k, v]) => `${k} ${v}`).join(' · ')}</dd>
              {card.warm_start && <><dt className="muted">Warm start</dt><dd>{card.warm_start.teacher} · agreement {fmt(100 * (card.warm_start.slot0_agreement_heldout || 0))}%</dd></>}
              {card.selection && <><dt className="muted">Selected</dt><dd>{card.selection.selected} of {card.selection.candidates?.length} candidates</dd></>}
            </dl>
          </Card>
        ))}
      </div>
    </div>
  );
}

/** v7 / v9 model cards: graph policy trained in the application twin (different card format from v2–v6). */
function TwinCard({ name, card, deployed }: { name: string; card: Json; deployed?: string }) {
  const sel = card.training.runs?.[card.selected_run] || {};
  const v = card.validation || {};
  const runs = Object.keys(card.training.runs || {});
  const reward = Object.entries(card.training.reward || {}).filter(([k]) => k !== 'kind' && k !== 'scale');
  return (
    <Card eyebrow={name === deployed ? 'Deployed' : 'Model'} title={`models/${name}`}
      actions={card.gate ? <StatusBadge level={card.gate.passed ? 'good' : 'critical'} label={card.gate.passed ? 'gate passed' : 'gate failed'} /> : undefined}>
      <dl className="text-sm grid grid-cols-[140px_1fr] gap-x-3 gap-y-1.5">
        <dt className="muted">Model</dt><dd>PPO (Stable-Baselines3) + graph network ({card.policy?.rounds ?? 2} message-passing rounds, {card.policy?.hidden ?? 64} units){card.policy?.use_graph === false ? ', no graph' : ''}, one decision per service</dd>
        <dt className="muted">Training</dt><dd className="tnum">{sel.steps ? `${fmt(sel.steps)} agent-steps` : '—'}{sel.minutes ? ` · ${fmt(sel.minutes, 1)} min` : ''}{card.training.device ? ` · ${card.training.device}` : ''} · {String(card.created || '').slice(0, 16).replace('T', ' ')}</dd>
        <dt className="muted">Simulator</dt><dd>{card.training.simulator}</dd>
        <dt className="muted">Actions</dt><dd>{(card.action?.deltas || []).map((d: number) => (d > 0 ? `+${d}` : `${d}`)).join(', ')} replicas</dd>
        <dt className="muted">Observation</dt><dd>v{card.observation?.version}: {card.observation?.per_service_fields?.join(', ')} (up to {card.observation?.n_max} services)</dd>
        <dt className="muted">Reward weights</dt><dd className="tnum">{reward.map(([k, x]) => `${k} ${x}`).join(' · ')}</dd>
        <dt className="muted">Selected</dt><dd>{card.selected_run} of {runs.length} training runs (best validation reward)</dd>
        <dt className="muted">Validation</dt><dd className="tnum">reward {fmt(v.reward, 2)} · {fmt(v.replica_hours, 2)} replica-h · p95 {fmt(v.p95_ms)} ms · {v.n} twin workloads</dd>
      </dl>
    </Card>
  );
}
