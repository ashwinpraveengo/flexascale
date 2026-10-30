import { useCallback, useEffect, useRef, useState } from 'react';
import { Json, api } from '../api';
import { Feed, TEvent, TPoint, fromEvent, fromExperimentSample, fromHistoryPoint, mergeEvents, mergePoints } from './data';

const FS_CONTROLLERS = ['flexascale', 'auto'];

/**
 * The active experiment, polled incrementally: the first request returns the whole run so far, later
 * ones only the samples and events appended since (index-based, so nothing is skipped or repeated).
 * The merged run is exposed as ``active`` (same shape as /experiments/active) so pages keep working.
 */
export function useActiveExperiment(ms = 3000): { active: Json | null; error: string | null; reload: () => void } {
  const [active, setActive] = useState<Json | null>(null);
  const [error, setError] = useState<string | null>(null);
  const cur = useRef<{ id: string | null; samples: Json[]; events: Json[]; base: number }>({ id: null, samples: [], events: [], base: 0 });
  const inflight = useRef(false);

  const load = useCallback(async () => {
    if (inflight.current) return;
    inflight.current = true;
    try {
      const c = cur.current;
      const q = c.id ? `?samples_from=${c.base + c.samples.length}&events_from=${c.events.length}` : '';
      const res = await fetch(`/api/lab/experiments/active${q}`).then((r) => r.json());
      let a = res?.active;
      if (a?.delta && a.id !== c.id) {
        // a new run answered a request made with the previous run's indexes: its slice starts at the old run's
        // sample count and skips its first events, so fetch the new run whole
        a = (await fetch('/api/lab/experiments/active').then((r) => r.json()))?.active;
      }
      if (!a) {
        cur.current = { id: null, samples: [], events: [], base: 0 };
        setActive(null);
      } else if (a.id !== c.id || !a.delta) {
        // new run (or a full snapshot): start over from what the server sent
        cur.current = { id: a.id, samples: a.samples || [], events: a.events || [], base: a.samples_offset || 0 };
        setActive({ ...a, samples: cur.current.samples, events: cur.current.events });
      } else {
        const samples = (a.samples || []).length ? c.samples.concat(a.samples) : c.samples;
        const events = (a.events || []).length ? c.events.concat(a.events) : c.events;
        cur.current = { id: a.id, samples, events, base: c.base };
        setActive({ ...a, samples, events });
      }
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      inflight.current = false;
    }
  }, []);

  useEffect(() => {
    load();
    const id = window.setInterval(() => document.visibilityState === 'visible' && load(), ms);
    return () => window.clearInterval(id);
  }, [load, ms]);
  return { active, error, reload: load };
}

/** Timeline feed of a run snapshot (the active experiment, or a saved run for replay). */
export function feedOfRun(run: Json | null, mode: 'live' | 'replay'): Feed | null {
  if (!run) return null;
  const fsRun = FS_CONTROLLERS.includes(run.request?.controller);
  const points: TPoint[] = (run.samples || []).map((s: Json) => fromExperimentSample(s, fsRun));
  const events: TEvent[] = (run.events || []).filter((e: Json) => e.t != null).map(fromEvent);
  const names = new Set<string>();
  for (const p of points) for (const n of Object.keys(p.services)) names.add(n);
  return {
    mode,
    points,
    events,
    interval: run.sample_interval_s || 5,
    start: run.started_at ?? null,
    duration: run.request?.duration ?? null,
    services: Array.from(names).sort(),
    sloE2eMs: run.slo?.e2e_p95_ms ?? null,
    sloServiceMs: run.slo?.service_mean_ms ?? null,
    cpuTargetPct: run.policy?.cpu_target_pct ?? run.request?.hpa_cpu_target_pct ?? null,
    label: mode === 'replay' ? `Replay of ${run.id}, recorded ${run.started_at ? new Date(run.started_at * 1000).toLocaleString() : ''}` : run.id,
    controller: run.request?.controller,
  };
}

/**
 * Live cluster telemetry outside experiments: the lab's rolling history of /live (recorded while a
 * dashboard polls), fetched incrementally by time.
 */
export function useLiveHistory(app: string, enabled: boolean, ms = 5000, live: Json = null): Feed | null {
  const [points, setPoints] = useState<TPoint[]>([]);
  const [interval, setIntervalS] = useState(5);
  const last = useRef<number | null>(null);
  const appRef = useRef(app);

  useEffect(() => {
    if (appRef.current !== app) {
      appRef.current = app;
      last.current = null;
      setPoints([]);
    }
    if (!enabled) return;
    let stop = false;
    const load = async () => {
      try {
        const q = last.current != null ? `?since=${last.current}` : '';
        const res = await fetch(`/api/lab/apps/${encodeURIComponent(app)}/history${q}`).then((r) => r.json());
        if (stop || !res?.points) return;
        setIntervalS(res.sample_interval_s || 5);
        const add = (res.points as Json[]).map(fromHistoryPoint);
        if (add.length) last.current = add[add.length - 1].t;
        setPoints((p) => mergePoints(p, add, 720));
      } catch {
        /* the page shows the lab-server error elsewhere */
      }
    };
    load();
    const id = window.setInterval(() => document.visibilityState === 'visible' && load(), ms);
    return () => {
      stop = true;
      window.clearInterval(id);
    };
  }, [app, enabled, ms]);

  if (!enabled) return null;
  const names = new Set<string>();
  for (const p of points.slice(-5)) for (const n of Object.keys(p.services)) names.add(n);
  return {
    mode: 'live-history',
    points,
    events: [],
    interval,
    start: null,
    services: Array.from(names).sort(),
    sloE2eMs: null,
    sloServiceMs: live?.policy?.slo_latency_ms ?? null,
    cpuTargetPct: live?.policy?.cpu_target_pct ?? null,
    label: 'Cluster telemetry (no experiment running)',
  };
}

/** A saved run for replay; loads once. */
export function useRun(id: string | null): { run: Json | null; error: string | null; loading: boolean } {
  const [run, setRun] = useState<Json | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    if (!id) {
      setRun(null);
      return;
    }
    let stop = false;
    setLoading(true);
    api.run(id).then(
      (r) => !stop && (setRun(r), setError(null), setLoading(false)),
      (e) => !stop && (setError(String(e?.message || e)), setLoading(false)),
    );
    return () => {
      stop = true;
    };
  }, [id]);
  return { run, error, loading };
}

export { mergeEvents };
