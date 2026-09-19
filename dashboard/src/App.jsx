import React, { useState, useEffect } from 'react';

export default function App() {
  const [status, setStatus] = useState(null);
  const [metrics, setMetrics] = useState([]);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [resStatus, resMetrics] = await Promise.all([
          fetch('/api/status').then(r => r.json()),
          fetch('/api/metrics').then(r => r.json())
        ]);
        setStatus(resStatus);
        setMetrics(resMetrics);
      } catch (e) {
        console.error(e);
      }
    };
    fetchData();
    const interval = setInterval(fetchData, 2000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="app-container">
      <header className="navbar">
        <h1 className="brand-title">FlexaScale</h1>
        <div className="status-pill healthy">
          <span>{status?.is_live_cluster ? 'LIVE MINIKUBE' : 'STANDALONE CLUSTER'}</span>
        </div>
      </header>
      <main className="dashboard-grid">
        <div className="services-grid">
          {metrics.map(m => (
            <div key={m.service_id} className="service-card">
              <h3>{m.service_id}</h3>
              <p>Replicas: {m.replica_count}</p>
              <p>CPU: {m.cpu_utilization.toFixed(1)}%</p>
              <p>Latency: {m.latency_ms.toFixed(1)} ms</p>
            </div>
          ))}
        </div>
      </main>
    </div>
  );
}
