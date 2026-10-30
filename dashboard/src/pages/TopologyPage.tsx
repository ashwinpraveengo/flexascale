import { useMemo, useState } from 'react';
import { Json, fmt } from '../api';
import { Topology } from '../Topology';
import { Card, Empty, ErrorNote, KV, OwnerBadge, Stat, StatusBadge } from '../ui';

/**
 * Discovered microservices on their call graph. Nodes are what discovery found in the namespace
 * (Deployments that match the policy's selector); edges come from the application policy's
 * `topology` (FlexaScale's graph input). Declared edges whose services were not discovered are listed.
 */
export function TopologyPage({ live, liveErr }: { live: Json; liveErr: string | null }) {
  const [sel, setSel] = useState<string | null>(null);
  const all: Json[] = live?.services || [];
  const services = all.filter((s) => s.eligible);
  const excluded = all.filter((s) => !s.eligible);
  const edges: [string, string][] = live?.policy?.topology || [];
  const names = new Set(services.map((s) => s.name));
  const dangling = edges.filter(([a, b]) => !names.has(a) || !names.has(b));
  const node = sel ? services.find((s) => s.name === sel) : null;
  const callers = useMemo(() => edges.filter(([, b]) => b === sel).map(([a]) => a), [edges, sel]);
  const callees = useMemo(() => edges.filter(([a]) => a === sel).map(([, b]) => b), [edges, sel]);
  const isolated = services.filter((s) => !edges.some(([a, b]) => a === s.name || b === s.name));
  const withLatency = services.filter((s) => s.metrics?.latency_mean_ms != null).length;
  const idle = services.filter((s) => s.metrics?.no_traffic).length;

  return (
    <div className="space-y-4">
      <ErrorNote error={liveErr} what="Live telemetry" />
      <div className="grid gap-3 grid-cols-2 lg:grid-cols-5">
        <Stat label="Discovered services" icon="layers" value={services.length} sub={`namespace ${live?.namespace || '—'} · selector ${live?.policy ? 'from policy' : '—'}`} />
        <Stat label="Call-graph edges" icon="graph" value={edges.length} sub={dangling.length ? `${dangling.length} reference undiscovered services` : 'all endpoints discovered'}
          level={dangling.length ? 'warning' : 'good'} />
        <Stat label="Latency reporting" icon="clock" value={`${withLatency}/${services.length}`} sub={`${idle} idle (scraped, no requests in the last minute)`} />
        <Stat label="Without edges" icon="info" value={isolated.length} sub={isolated.length ? isolated.map((s) => s.name).join(', ') : 'every service is on the graph'} />
        <Stat label="Not managed" icon="shield" value={excluded.length} sub={excluded.map((s) => s.name).join(', ') || 'none'} />
      </div>

      <Card eyebrow="Service topology" title="Caller → callee graph with live state" actions={sel ? <button className="btn btn-ghost text-xs" onClick={() => setSel(null)}>Clear selection</button> : undefined}>
        {services.length ? (
          <Topology services={services} edges={edges} slo={live?.policy?.slo_latency_ms} onSelect={(n) => setSel(sel === n ? null : n)} selected={sel} />
        ) : (
          <Empty icon="graph">No eligible services discovered{live?.namespace ? ` in ${live.namespace}` : ''}.</Empty>
        )}
      </Card>

      <div className="grid gap-4 xl:grid-cols-[1fr_1fr]">
        <Card eyebrow="Selected service" title={node ? node.name : 'Click a node'}>
          {!node ? (
            <Empty icon="graph" height={140}>Select a service on the graph to see its dependencies and live state.</Empty>
          ) : (
            <div className="space-y-4">
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
                <KV k="Owner" v={<OwnerBadge owner={node.owner} compact />} />
                <KV k="Replicas" v={`${node.ready_replicas} ready / ${node.desired_replicas} desired`} mono />
                <KV k="HPA" v={node.hpa ? `${node.hpa.name} ${node.hpa.min_replicas}–${node.hpa.max_replicas}${node.hpa.frozen ? ' (frozen)' : ''}` : 'none'} />
                <KV k="Requests" v={`${fmt(node.cpu_request_cores, 2)} CPU · ${fmt((node.memory_request_bytes || 0) / 2 ** 20)} MiB`} mono />
                <KV k="CPU / memory" v={`${fmt(node.metrics?.cpu_pct)}% / ${fmt(node.metrics?.memory_pct)}%`} mono />
                <KV k="Requests/s" v={node.metrics?.no_traffic ? '0 (no requests)' : fmt(node.metrics?.request_rate, 2)} mono />
                <KV k="Latency mean / p95" v={node.metrics?.no_traffic ? 'no requests' : `${fmt(node.metrics?.latency_mean_ms, 1)} / ${fmt(node.metrics?.latency_p95_ms)} ms`} mono />
                <KV k="Telemetry" v={node.metrics?.stale ? <StatusBadge level="critical" label="stale" /> : node.metrics?.missing?.length ? `missing ${node.metrics.missing.join(', ')}` : <StatusBadge level="good" label="complete" />} />
              </div>
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div className="card-flat p-3"><div className="eyebrow mb-1">Called by</div>{callers.length ? callers.map((c) => <div key={c}>{c}</div>) : <span className="muted">entry service (no callers)</span>}</div>
                <div className="card-flat p-3"><div className="eyebrow mb-1">Calls</div>{callees.length ? callees.map((c) => <div key={c}>{c}</div>) : <span className="muted">leaf service</span>}</div>
              </div>
            </div>
          )}
        </Card>
        <Card eyebrow="Graph input" title="How FlexaScale uses this graph">
          <ul className="text-sm ink2 space-y-2 list-disc pl-5">
            <li>Edges come from the application policy (<code>topology:</code> in config/apps/*.yaml): FlexaScale's code holds no service names.</li>
            <li>Discovery lists the Deployments matching the policy's namespace, label selector and include/exclude rules; datastores are skipped.</li>
            <li>The graph policy reads every service's own features together with its callers' and callees' (message passing over these edges).</li>
            <li>Services discovered but absent from the graph are still scaled, with no neighbours.</li>
          </ul>
          {dangling.length > 0 && (
            <div className="mt-3 text-xs" style={{ color: 'var(--serious)' }}>Declared edges with undiscovered endpoints: {dangling.map(([a, b]) => `${a} → ${b}`).join(', ')}</div>
          )}
        </Card>
      </div>
    </div>
  );
}
