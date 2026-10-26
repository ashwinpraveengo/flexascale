import { useMemo, useState } from 'react';
import { Json, OWNER_COLOR, OWNER_LABEL, fmt } from './api';
import { Icon } from './ui';

/**
 * Application call graph from the policy's `topology` (caller -> callee), laid out in layers by
 * call depth from the entry service(s). Node fill = current owner (HPA / FlexaScale), a status
 * ring + icon marks CPU risk or latency above SLO, and the badge shows ready/desired replicas.
 */
export function Topology({ services, edges, slo, cpuRisk = 85, onSelect, selected }: {
  services: Json[];
  edges: [string, string][];
  slo?: number | null;
  cpuRisk?: number;
  onSelect?: (name: string) => void;
  selected?: string | null;
}) {
  const [hover, setHover] = useState<string | null>(null);
  const byName = useMemo(() => Object.fromEntries(services.map((s) => [s.name, s])), [services]);
  const names = useMemo(() => services.map((s) => s.name).sort(), [services]);

  const layout = useMemo(() => {
    const es = edges.filter(([a, b]) => byName[a] && byName[b] && a !== b);
    const indeg: Record<string, number> = Object.fromEntries(names.map((n) => [n, 0]));
    for (const [, b] of es) indeg[b] += 1;
    const depth: Record<string, number> = {};
    const roots = names.filter((n) => indeg[n] === 0 && es.some(([a]) => a === n));
    const queue = roots.map((r) => ((depth[r] = 0), r));
    while (queue.length) {
      const n = queue.shift() as string;
      for (const [a, b] of es) if (a === n && (depth[b] === undefined || depth[b] < depth[n] + 1) && depth[n] + 1 < names.length) {
        depth[b] = depth[n] + 1;
        queue.push(b);
      }
    }
    const isolated = names.filter((n) => depth[n] === undefined);
    const maxD = Math.max(0, ...Object.values(depth));
    for (const n of isolated) depth[n] = maxD + 1;
    const layers: string[][] = [];
    for (const n of names) (layers[depth[n]] ||= []).push(n);
    // order each layer by the mean position of its callers (fewer crossings)
    const pos: Record<string, number> = {};
    layers.forEach((layer, d) => {
      if (d > 0) {
        layer.sort((a, b) => {
          const pa = es.filter(([, t]) => t === a).map(([s]) => pos[s] ?? 0);
          const pb = es.filter(([, t]) => t === b).map(([s]) => pos[s] ?? 0);
          const ma = pa.length ? pa.reduce((x, y) => x + y, 0) / pa.length : 0.5;
          const mb = pb.length ? pb.reduce((x, y) => x + y, 0) / pb.length : 0.5;
          return ma - mb || a.localeCompare(b);
        });
      }
      layer.forEach((n, i) => (pos[n] = (i + 0.5) / layer.length));
    });
    return { layers: layers.filter(Boolean), es, isolated };
  }, [names, edges, byName]);

  const colW = 172;
  const rowH = 54;
  const maxRows = Math.max(1, ...layout.layers.map((l) => l.length));
  const width = Math.max(560, layout.layers.length * colW + 40);
  const height = maxRows * rowH + 30;
  const xy: Record<string, [number, number]> = {};
  layout.layers.forEach((layer, d) => {
    const x = 30 + d * colW;
    const off = (height - layer.length * rowH) / 2;
    layer.forEach((n, i) => (xy[n] = [x, off + i * rowH + rowH / 2]));
  });

  const risk = (s: Json): { level: 'critical' | 'serious' | null; why: string } => {
    const m = s.metrics || {};
    if (slo && m.latency_mean_ms != null && m.latency_mean_ms > slo) return { level: 'critical', why: `latency ${fmt(m.latency_mean_ms)} ms > SLO ${slo} ms` };
    if (m.cpu_pct != null && m.cpu_pct >= cpuRisk) return { level: 'serious', why: `CPU ${fmt(m.cpu_pct)}% of request` };
    return { level: null, why: '' };
  };

  if (!names.length) return null;
  const focus = hover || selected;
  const linked = new Set<string>();
  if (focus) for (const [a, b] of layout.es) if (a === focus || b === focus) linked.add(a), linked.add(b);

  return (
    <div className="overflow-x-auto scroll-thin">
      <svg viewBox={`0 0 ${width} ${height}`} style={{ minWidth: Math.min(width, 900), width: '100%' }} role="img" aria-label="Application call graph">
        <defs>
          <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" fill="var(--axis)" />
          </marker>
        </defs>
        {layout.es.map(([a, b]) => {
          const [x1, y1] = xy[a];
          const [x2, y2] = xy[b];
          const on = focus ? (a === focus || b === focus) : false;
          const sx = x1 + 132;
          const ex = x2 - 4;
          const mx = (sx + ex) / 2;
          return (
            <path key={`${a}-${b}`} d={`M${sx},${y1} C${mx},${y1} ${mx},${y2} ${ex},${y2}`} fill="none"
              stroke={on ? 'var(--ink-2)' : 'var(--axis)'} strokeWidth={on ? 1.75 : 1} opacity={focus && !on ? 0.35 : 1} markerEnd="url(#arrow)" />
          );
        })}
        {names.map((n) => {
          const s = byName[n];
          const [x, y] = xy[n];
          const r = risk(s);
          const owner = s.owner as string;
          const dim = focus && !linked.has(n) && focus !== n;
          return (
            <g key={n} transform={`translate(${x},${y - 17})`} opacity={dim ? 0.4 : 1} style={{ cursor: onSelect ? 'pointer' : 'default', transition: 'opacity .15s' }}
              onMouseEnter={() => setHover(n)} onMouseLeave={() => setHover(null)} onClick={() => onSelect?.(n)}>
              <title>{`${n} — ${OWNER_LABEL[owner] || owner} · ${s.ready_replicas}/${s.desired_replicas} replicas · CPU ${fmt(s.metrics?.cpu_pct)}%${r.why ? ` · ${r.why}` : ''}`}</title>
              <rect width={132} height={34} rx={9} fill="var(--surface-2)"
                stroke={r.level ? `var(--${r.level})` : selected === n ? 'var(--accent)' : 'var(--border-strong)'} strokeWidth={r.level || selected === n ? 2 : 1} />
              <rect x={0} y={0} width={4} height={34} rx={2} fill={OWNER_COLOR[owner] || 'var(--muted)'} />
              <text x={12} y={14} fontSize={11} fontWeight={650} fill="var(--ink)">{(() => { const t = n.replace(/-service$/, ''); return t.length > 13 ? `${t.slice(0, 12)}…` : t; })()}</text>
              <text x={12} y={27} fontSize={10} fill="var(--muted)" className="tnum">
                {s.metrics?.cpu_pct != null
                  ? `${fmt(s.metrics.cpu_pct)}% cpu${s.metrics.request_rate ? ` · ${fmt(s.metrics.request_rate, s.metrics.request_rate < 10 ? 1 : 0)}/s` : ''}`
                  : 'no data'}
              </text>
              <g transform="translate(100,9)">
                <rect width={26} height={16} rx={8} fill="var(--surface-3)" />
                <text x={13} y={11.5} textAnchor="middle" fontSize={10} fontWeight={700} fill="var(--ink)" className="tnum">
                  {s.ready_replicas}{s.ready_replicas !== s.desired_replicas ? `/${s.desired_replicas}` : ''}
                </text>
              </g>
              {r.level && (
                <g transform="translate(118,-6)">
                  <circle r={7} cx={7} cy={7} fill={`var(--${r.level})`} />
                  <text x={7} y={10.5} textAnchor="middle" fontSize={10} fontWeight={800} fill="#fff">!</text>
                </g>
              )}
            </g>
          );
        })}
      </svg>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs ink2 mt-2">
        <span className="inline-flex items-center gap-1.5"><span className="inline-block w-1 h-3 rounded" style={{ background: 'var(--hpa)' }} />Owned by native HPA</span>
        <span className="inline-flex items-center gap-1.5"><span className="inline-block w-1 h-3 rounded" style={{ background: 'var(--flexa)' }} />Owned by FlexaScale</span>
        <span className="inline-flex items-center gap-1.5"><Icon name="error" size={12} style={{ color: 'var(--critical)' }} />Latency above SLO</span>
        <span className="inline-flex items-center gap-1.5"><Icon name="alert" size={12} style={{ color: 'var(--serious)' }} />CPU ≥ {cpuRisk}%</span>
        <span className="muted">Badge: ready replicas (/desired while starting). Arrows: caller → callee.</span>
        {layout.isolated.length > 0 && <span className="muted">Right column: services with no known edges.</span>}
      </div>
    </div>
  );
}
