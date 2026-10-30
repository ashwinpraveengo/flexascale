import { useEffect, useState } from 'react';
import { CONTROLLER_LABEL, Json, TERMINAL, api, fmtElapsed } from './api';
import { Banner, Freshness, Icon, StatusBadge, useAge, usePoll } from './ui';
import { Overview } from './pages/Overview';
import { LiveLab } from './pages/LiveLab';
import { Compare } from './pages/Compare';
import { AutoPage } from './pages/AutoPage';
import { Models } from './pages/Models';
import { Experiments } from './pages/Experiments';
import { TopologyPage } from './pages/TopologyPage';
import { useActiveExperiment } from './timeline/feeds';

type Page = 'overview' | 'topology' | 'live' | 'auto' | 'compare' | 'experiments' | 'models';
const GROUPS: { label: string; pages: { id: Page; label: string; icon: string }[] }[] = [
  { label: 'Observe', pages: [{ id: 'overview', label: 'Overview', icon: 'overview' }, { id: 'topology', label: 'Service topology', icon: 'graph' }] },
  { label: 'Operate', pages: [{ id: 'live', label: 'Live lab', icon: 'live' }, { id: 'auto', label: 'Auto mode', icon: 'auto' }] },
  { label: 'Analyze', pages: [{ id: 'compare', label: 'Comparison', icon: 'compare' }, { id: 'experiments', label: 'Experiments', icon: 'history' }, { id: 'models', label: 'Models', icon: 'model' }] },
];
const PAGES = GROUPS.flatMap((g) => g.pages);
const SUBTITLE: Record<Page, string> = {
  overview: 'Cluster, application and autoscaling health',
  topology: 'Discovered microservices and their call graph',
  live: 'Run HPA, FlexaScale and Auto under the same workload',
  auto: 'Per-service controller ownership and its reasons',
  compare: 'Paired benchmark against native HPA',
  experiments: 'Saved runs: configuration, validity and replay',
  models: 'Trained policies, compatibility and inference health',
};

function readTheme(): 'dark' | 'light' {
  try {
    return (localStorage.getItem('flexascale-theme') as 'dark' | 'light') || 'dark';
  } catch {
    return 'dark';
  }
}

function pageFromHash(): Page {
  const h = window.location.hash.replace('#', '').split('?')[0] as Page;
  return PAGES.some((p) => p.id === h) ? h : 'overview';
}

export default function App() {
  const [page, setPage] = useState<Page>(pageFromHash);
  const [theme, setTheme] = useState<'dark' | 'light'>(readTheme);
  const [menu, setMenu] = useState(false);
  const [app, setApp] = useState('shopping');

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem('flexascale-theme', theme);
    } catch {
      /* private mode: theme still applies for this page */
    }
  }, [theme]);
  useEffect(() => {
    const on = () => setPage(pageFromHash());
    window.addEventListener('hashchange', on);
    return () => window.removeEventListener('hashchange', on);
  }, []);
  const go = (p: string) => {
    window.location.hash = p;
    setPage(p.split('?')[0] as Page);
    setMenu(false);
    window.scrollTo({ top: 0 });
  };

  const overview = usePoll<Json>(api.overview, 10000);
  const meta = usePoll<Json>(api.scenarios, 600000);
  const live = usePoll<Json>(() => api.live(app), 5000, [app]);
  const activeRes = useActiveExperiment(3000);
  const bench = usePoll<Json>(() => api.benchmark(app), 30000, [app]);
  const active = activeRes.active;
  const exp = active && active.request?.app === app ? active : null;
  const running = !!exp && !TERMINAL.includes(exp.state);
  const cluster = overview.data?.cluster;
  const apps: Json[] = overview.data?.apps || [];
  const appInfo = apps.find((a) => a.name === app);
  const shopUrl = exp?.app_url || appInfo?.url;
  const last = exp?.samples?.[exp.samples.length - 1];
  const deployed = String(live.data?.policy?.model_path || '').replace(/\\/g, '/').split('/')[1];
  const liveAge = useAge(live.data?.timestamp);
  const apiDown = !!(overview.error && live.error);
  const current = PAGES.find((p) => p.id === page);

  const nav = (
    <nav className="space-y-5" aria-label="Pages">
      {GROUPS.map((g) => (
        <div key={g.label}>
          <div className="eyebrow px-2.5 mb-1.5 !text-[10px]">{g.label}</div>
          <div className="space-y-0.5">
            {g.pages.map((p) => (
              <button key={p.id} className="nav-item" aria-current={page === p.id ? 'page' : undefined} onClick={() => go(p.id)}>
                <Icon name={p.icon} size={17} />
                {p.label}
                {p.id === 'live' && running && <span className="dot dot-live ml-auto" style={{ background: 'var(--good)', color: 'var(--good)' }} />}
              </button>
            ))}
          </div>
        </div>
      ))}
    </nav>
  );

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[244px_1fr]">
      <aside className="hidden lg:flex flex-col gap-7 p-4 border-r sticky top-0 h-screen" style={{ borderColor: 'var(--border)', background: 'color-mix(in srgb, var(--surface) 50%, transparent)' }}>
        <Brand />
        {nav}
        <div className="mt-auto space-y-2 text-xs">
          <div className="card-flat p-3 space-y-1.5">
            <div className="eyebrow">Deployed policy</div>
            <div className="font-semibold">{deployed || '—'}</div>
            <div className="muted">{live.data?.policy?.mode === 'observe' ? 'observe by default; live only during experiments' : live.data?.policy?.mode}</div>
          </div>
          {shopUrl && <a className="btn w-full justify-between text-xs" href={shopUrl} target="_blank" rel="noreferrer">Open the shop <Icon name="external" size={13} /></a>}
        </div>
      </aside>

      <div className="min-w-0">
        <header className="sticky top-0 z-20 backdrop-blur-md border-b" style={{ borderColor: 'var(--border)', background: 'color-mix(in srgb, var(--page) 80%, transparent)' }}>
          <div className="px-4 sm:px-6 py-3 flex items-center gap-3 flex-wrap">
            <button className="btn btn-ghost lg:hidden !p-2" aria-label="Menu" aria-expanded={menu} onClick={() => setMenu((m) => !m)}><Icon name="menu" size={18} /></button>
            <div className="lg:hidden"><Brand compact /></div>
            <div className="min-w-0 hidden sm:block">
              <h1 className="text-lg font-semibold leading-tight tracking-tight">{current?.label}</h1>
              <p className="text-xs muted">{SUBTITLE[page]} · real telemetry; missing values shown as “—”, never estimated</p>
            </div>
            <div className="ml-auto flex items-center gap-2 flex-wrap justify-end">
              {running && (
                <button className="pill" onClick={() => go('live')} title="Experiment running">
                  <span className="dot dot-live" style={{ background: 'var(--good)', color: 'var(--good)' }} />
                  {CONTROLLER_LABEL[exp.request.controller]} · {fmtElapsed(last?.elapsed ?? null)}
                </button>
              )}
              <Freshness ts={live.data?.timestamp} error={live.error} label="Telemetry" />
              <StatusBadge level={!cluster ? 'unknown' : cluster.kubectl && cluster.nodes_ready > 0 ? 'good' : 'critical'} label={`Cluster${cluster?.context ? ` ${cluster.context}` : ''}`} title={cluster?.error} />
              <StatusBadge level={!cluster ? 'unknown' : cluster.prometheus ? 'good' : 'critical'} label="Prometheus" title={cluster?.prometheus_url} />
              <select className="field !w-auto !py-1.5 text-sm" value={app} onChange={(e) => setApp(e.target.value)} disabled={running} aria-label="Application">
                {(apps.length ? apps : [{ name: 'shopping', title: 'shopping' }]).map((a) => <option key={a.name} value={a.name}>{a.title}</option>)}
              </select>
              <button className="btn btn-ghost !p-2" aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`} onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>
                <Icon name={theme === 'dark' ? 'sun' : 'moon'} size={17} />
              </button>
            </div>
          </div>
          {menu && <div className="lg:hidden px-4 pb-3">{nav}</div>}
        </header>

        <main className="px-4 sm:px-6 py-5 max-w-[1720px] space-y-4">
          {apiDown && (
            <Banner level="critical"><b>Lab server unreachable.</b> The dashboard cannot reach the FlexaScale lab API on this host; values below are the last ones received and are not current. <span className="muted">({live.error})</span></Banner>
          )}
          {!apiDown && liveAge != null && liveAge > 20 && (
            <Banner level="warning"><b>Telemetry is stale</b>: the last live update is {Math.round(liveAge)} s old. Values are shown as last received.</Banner>
          )}
          {page === 'overview' && <Overview overview={overview.data} live={live.data} liveErr={live.error} active={active} app={app} bench={bench.data} onNavigate={go} />}
          {page === 'topology' && <TopologyPage live={live.data} liveErr={live.error} />}
          {page === 'live' && <LiveLab meta={meta.data} live={live.data} liveErr={live.error} active={active} app={app} shopUrl={shopUrl}
            grafana={cluster?.grafana_url} prometheus={cluster?.prometheus_url} reloadActive={activeRes.reload} />}
          {page === 'compare' && <Compare app={app} />}
          {page === 'auto' && <AutoPage live={live.data} active={active} onNavigate={go} />}
          {page === 'experiments' && <Experiments app={app} meta={meta.data} onNavigate={go} />}
          {page === 'models' && <Models deployed={deployed} live={live.data} />}
        </main>
      </div>
    </div>
  );
}

function Brand({ compact }: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <svg width="30" height="30" viewBox="0 0 32 32" aria-hidden>
        <defs>
          <linearGradient id="brand-g" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="var(--accent)" />
            <stop offset="1" stopColor="var(--flexa)" />
          </linearGradient>
        </defs>
        <rect width="32" height="32" rx="9" fill="url(#brand-g)" />
        <path d="M8 22V10h9M8 16h6" stroke="#fff" strokeWidth="2.2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M18 22h2v-4h2v-5h2v9" stroke="#fff" strokeWidth="1.8" fill="none" strokeLinecap="round" strokeLinejoin="round" opacity="0.9" />
      </svg>
      {!compact && (
        <div className="leading-tight">
          <div className="font-semibold tracking-tight">FlexaScale</div>
          <div className="text-[11px] muted">Autoscaling control center</div>
        </div>
      )}
    </div>
  );
}
