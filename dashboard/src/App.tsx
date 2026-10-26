import { useEffect, useState } from 'react';
import { CONTROLLER_LABEL, Json, TERMINAL, api, fmtElapsed } from './api';
import { Banner, Freshness, Icon, StatusBadge, useAge, usePoll } from './ui';
import { Overview } from './pages/Overview';
import { LiveLab } from './pages/LiveLab';
import { Compare } from './pages/Compare';
import { AutoPage } from './pages/AutoPage';
import { Models } from './pages/Models';

type Page = 'overview' | 'live' | 'compare' | 'auto' | 'models';
const PAGES: { id: Page; label: string; icon: string }[] = [
  { id: 'overview', label: 'Overview', icon: 'overview' },
  { id: 'live', label: 'Live lab', icon: 'live' },
  { id: 'compare', label: 'Comparison', icon: 'compare' },
  { id: 'auto', label: 'Auto mode', icon: 'auto' },
  { id: 'models', label: 'Models', icon: 'model' },
];

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
    setPage(p as Page);
    setMenu(false);
    window.scrollTo({ top: 0 });
  };

  const overview = usePoll<Json>(api.overview, 10000);
  const meta = usePoll<Json>(api.scenarios, 600000);
  const live = usePoll<Json>(() => api.live(app), 5000, [app]);
  const activeRes = usePoll<Json>(api.active, 3000);
  const bench = usePoll<Json>(() => api.benchmark(app), 30000, [app]);
  const active = activeRes.data?.active || null;
  const exp = active && active.request?.app === app ? active : null;
  const running = !!exp && !TERMINAL.includes(exp.state);
  const cluster = overview.data?.cluster;
  const apps: Json[] = overview.data?.apps || [];
  const appInfo = apps.find((a) => a.name === app);
  const shopUrl = exp?.app_url || appInfo?.url;
  const last = exp?.samples?.[exp.samples.length - 1];
  const deployed = String(live.data?.policy?.model_path || '').split('/')[1];
  const liveAge = useAge(live.data?.timestamp);
  const apiDown = !!(overview.error && live.error);

  const nav = (
    <nav className="space-y-1" aria-label="Pages">
      {PAGES.map((p) => (
        <button key={p.id} className="nav-item" aria-current={page === p.id ? 'page' : undefined} onClick={() => go(p.id)}>
          <Icon name={p.icon} size={17} />
          {p.label}
          {p.id === 'live' && running && <span className="dot dot-live ml-auto" style={{ background: 'var(--good)', color: 'var(--good)' }} />}
        </button>
      ))}
    </nav>
  );

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[236px_1fr]">
      <aside className="hidden lg:flex flex-col gap-6 p-4 border-r sticky top-0 h-screen" style={{ borderColor: 'var(--border)', background: 'color-mix(in srgb, var(--surface) 55%, transparent)' }}>
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
        <header className="sticky top-0 z-20 backdrop-blur-md border-b" style={{ borderColor: 'var(--border)', background: 'color-mix(in srgb, var(--page) 78%, transparent)' }}>
          <div className="px-4 sm:px-6 py-3 flex items-center gap-3 flex-wrap">
            <button className="btn btn-ghost lg:hidden !p-2" aria-label="Menu" aria-expanded={menu} onClick={() => setMenu((m) => !m)}><Icon name="menu" size={18} /></button>
            <div className="lg:hidden"><Brand compact /></div>
            <div className="min-w-0 hidden sm:block">
              <h1 className="text-lg font-semibold leading-tight">{PAGES.find((p) => p.id === page)?.label}</h1>
              <p className="text-xs muted">Real cluster telemetry · missing values shown as “—”, never estimated</p>
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

        <main className="px-4 sm:px-6 py-5 max-w-[1680px] space-y-4">
          {apiDown && (
            <Banner level="critical"><b>Lab server unreachable.</b> The dashboard cannot reach the FlexaScale lab API on this host; values below are the last ones received and are not current. <span className="muted">({live.error})</span></Banner>
          )}
          {!apiDown && liveAge != null && liveAge > 20 && (
            <Banner level="warning"><b>Telemetry is stale</b>: the last live update is {Math.round(liveAge)} s old. Values are shown as last received.</Banner>
          )}
          {page === 'overview' && <Overview overview={overview.data} live={live.data} liveErr={live.error} active={active} app={app} bench={bench.data} onNavigate={go} />}
          {page === 'live' && <LiveLab meta={meta.data} live={live.data} liveErr={live.error} active={active} app={app} shopUrl={shopUrl}
            grafana={cluster?.grafana_url} prometheus={cluster?.prometheus_url} reloadActive={activeRes.reload} />}
          {page === 'compare' && <Compare app={app} />}
          {page === 'auto' && <AutoPage live={live.data} active={active} onNavigate={go} />}
          {page === 'models' && <Models deployed={deployed} live={live.data} />}
        </main>
      </div>
    </div>
  );
}

function Brand({ compact }: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <svg width="28" height="28" viewBox="0 0 32 32" aria-hidden>
        <rect width="32" height="32" rx="9" fill="var(--accent)" />
        <path d="M9 21V11h9M9 16h6M19 21l4-10" stroke="#fff" strokeWidth="2.2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      {!compact && (
        <div className="leading-tight">
          <div className="font-semibold">FlexaScale</div>
          <div className="text-[11px] muted">Autoscaling control center</div>
        </div>
      )}
    </div>
  );
}
