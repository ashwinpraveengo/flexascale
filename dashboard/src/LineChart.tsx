import { useMemo, useRef, useState } from 'react';
import { fmt } from './api';

export interface Series {
  key: string;
  label: string;
  color: string;
  values: (number | null)[];
}

interface Props {
  title: string;
  unit: string;
  x: number[]; // elapsed seconds
  series: Series[];
  reference?: { value: number; label: string };
  step?: boolean;
  digits?: number;
  height?: number;
  minMax?: number;
  empty?: string;
}

const PAD = { l: 44, r: 12, t: 10, b: 24 };

function niceMax(v: number): number {
  if (v <= 0) return 1;
  const exp = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 2, 2.5, 5, 10]) {
    if (m * exp >= v) return m * exp;
  }
  return 10 * exp;
}

export function LineChart({ title, unit, x, series, reference, step, digits = 0, height = 190, minMax = 1, empty }: Props) {
  const ref = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  const width = 560;
  const w = width - PAD.l - PAD.r;
  const h = height - PAD.t - PAD.b;

  const { yMax, xMin, xMax } = useMemo(() => {
    let m = reference ? reference.value * 1.1 : 0;
    for (const s of series) for (const v of s.values) if (v !== null && v > m) m = v;
    const xs = x.length ? x : [0, 1];
    return { yMax: niceMax(Math.max(m, minMax)), xMin: xs[0], xMax: Math.max(xs[xs.length - 1], xs[0] + 1) };
  }, [series, x, reference, minMax]);

  const sx = (v: number) => PAD.l + ((v - xMin) / (xMax - xMin)) * w;
  const sy = (v: number) => PAD.t + h - (v / yMax) * h;

  const paths = series.map((s) => {
    let d = '';
    let prevY: number | null = null;
    s.values.forEach((v, i) => {
      if (v === null) {
        prevY = null;
        return;
      }
      const px = sx(x[i]);
      const py = sy(v);
      if (prevY === null) d += `M${px.toFixed(1)},${py.toFixed(1)}`;
      else if (step) d += `H${px.toFixed(1)}V${py.toFixed(1)}`;
      else d += `L${px.toFixed(1)},${py.toFixed(1)}`;
      prevY = py;
    });
    return d;
  });

  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * yMax);
  const xTicks = 5;

  function onMove(e: React.MouseEvent<SVGSVGElement>) {
    if (!ref.current || !x.length) return;
    const rect = ref.current.getBoundingClientRect();
    const px = ((e.clientX - rect.left) / rect.width) * width;
    const xv = xMin + ((px - PAD.l) / w) * (xMax - xMin);
    let best = 0;
    for (let i = 1; i < x.length; i++) if (Math.abs(x[i] - xv) < Math.abs(x[best] - xv)) best = i;
    setHover(best);
  }

  const hasData = x.length > 1 && series.some((s) => s.values.some((v) => v !== null));

  return (
    <div className="card p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2 mb-1">
        <h3 className="font-semibold text-sm">{title}</h3>
        <span className="text-xs muted">{unit}</span>
      </div>
      {series.length > 1 && (
        <div className="flex flex-wrap gap-x-3 gap-y-1 mb-2 text-xs ink2">
          {series.map((s) => (
            <span key={s.key} className="inline-flex items-center gap-1">
              <span className="inline-block w-3 h-[2px] rounded" style={{ background: s.color }} />
              {s.label}
            </span>
          ))}
          {reference && (
            <span className="inline-flex items-center gap-1">
              <span className="inline-block w-3 h-[2px]" style={{ background: 'var(--critical)' }} />
              {reference.label}
            </span>
          )}
        </div>
      )}
      {!hasData ? (
        <div className="flex items-center justify-center text-sm muted" style={{ height }}>
          {empty || 'No samples yet — start an experiment.'}
        </div>
      ) : (
        <div className="relative">
          <svg
            ref={ref}
            viewBox={`0 0 ${width} ${height}`}
            className="w-full h-auto select-none"
            onMouseMove={onMove}
            onMouseLeave={() => setHover(null)}
            role="img"
            aria-label={title}
          >
            {ticks.map((t) => (
              <g key={t}>
                <line x1={PAD.l} x2={width - PAD.r} y1={sy(t)} y2={sy(t)} stroke="var(--grid)" strokeWidth={1} />
                <text x={PAD.l - 6} y={sy(t) + 4} textAnchor="end" fontSize={10} fill="var(--muted)" className="tnum">
                  {fmt(t, t < 10 && yMax <= 10 ? 1 : 0)}
                </text>
              </g>
            ))}
            {Array.from({ length: xTicks + 1 }, (_, i) => xMin + (i / xTicks) * (xMax - xMin)).map((t) => (
              <text key={t} x={sx(t)} y={height - 6} textAnchor="middle" fontSize={10} fill="var(--muted)" className="tnum">
                {Math.round(t)}s
              </text>
            ))}
            <line x1={PAD.l} x2={width - PAD.r} y1={sy(0)} y2={sy(0)} stroke="var(--axis)" strokeWidth={1} />
            {reference && (
              <g>
                <line x1={PAD.l} x2={width - PAD.r} y1={sy(reference.value)} y2={sy(reference.value)} stroke="var(--critical)" strokeWidth={1} opacity={0.7} />
                {series.length === 1 && (
                  <text x={width - PAD.r} y={sy(reference.value) - 4} textAnchor="end" fontSize={10} fill="var(--ink-2)">
                    {reference.label}
                  </text>
                )}
              </g>
            )}
            {paths.map((d, i) => (
              <path key={series[i].key} d={d} fill="none" stroke={series[i].color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
            ))}
            {hover !== null && (
              <g>
                <line x1={sx(x[hover])} x2={sx(x[hover])} y1={PAD.t} y2={PAD.t + h} stroke="var(--axis)" strokeWidth={1} />
                {series.map((s) =>
                  s.values[hover] !== null ? (
                    <circle key={s.key} cx={sx(x[hover])} cy={sy(s.values[hover] as number)} r={4} fill={s.color} stroke="var(--surface)" strokeWidth={2} />
                  ) : null,
                )}
              </g>
            )}
          </svg>
          {hover !== null && (
            <div
              className="absolute top-1 card px-3 py-2 text-xs shadow-lg pointer-events-none"
              style={{ left: sx(x[hover]) / width > 0.6 ? 8 : undefined, right: sx(x[hover]) / width > 0.6 ? undefined : 8 }}
            >
              <div className="font-semibold mb-1 tnum">t = {Math.round(x[hover])}s</div>
              {series.map((s) => (
                <div key={s.key} className="flex items-center gap-2 tnum">
                  <span className="inline-block w-2 h-2 rounded-full" style={{ background: s.color }} />
                  <span className="ink2">{s.label}</span>
                  <span className="ml-auto pl-3 font-semibold">{fmt(s.values[hover], digits)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
