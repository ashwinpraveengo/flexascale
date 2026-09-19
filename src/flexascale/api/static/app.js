// FlexaScale Real-Time Dashboard Client Logic

const API_BASE = '';
let isPolling = false;

// DOM Elements
const elClusterStatusPill = document.getElementById('cluster-status-pill');
const elClusterStatusText = document.getElementById('cluster-status-text');
const elGlobalModePill = document.getElementById('global-mode-pill');
const elGlobalModeText = document.getElementById('global-mode-text');
const elServicesGrid = document.getElementById('services-grid');
const elGraphFlow = document.getElementById('graph-flow');
const elDecisionsTable = document.getElementById('decisions-tbody');

const elLiveLatency = document.getElementById('live-latency-val');
const elLiveCpu = document.getElementById('live-cpu-val');
const elLiveRps = document.getElementById('live-rps-val');
const elLiveReps = document.getElementById('live-reps-val');

const btnStep = document.getElementById('btn-trigger-step');
const btnFallback = document.getElementById('btn-emergency-fallback');
const configForm = document.getElementById('config-form');

// Sliders and values
const cfgSloLatency = document.getElementById('cfg-slo-latency');
const valSloLatency = document.getElementById('val-cfg-slo-latency');
const cfgTargetCpu = document.getElementById('cfg-target-cpu');
const valTargetCpu = document.getElementById('val-cfg-target-cpu');
const cfgConfidence = document.getElementById('cfg-confidence');
const valConfidence = document.getElementById('val-cfg-confidence');
const cfgHysteresis = document.getElementById('cfg-hysteresis');
const valHysteresis = document.getElementById('val-cfg-hysteresis');
const cfgCooldown = document.getElementById('cfg-cooldown');
const valCooldown = document.getElementById('val-cfg-cooldown');

// Wire slider value displays
cfgSloLatency.addEventListener('input', () => valSloLatency.textContent = `${cfgSloLatency.value} ms`);
cfgTargetCpu.addEventListener('input', () => valTargetCpu.textContent = `${cfgTargetCpu.value} %`);
cfgConfidence.addEventListener('input', () => valConfidence.textContent = parseFloat(cfgConfidence.value).toFixed(2));
cfgHysteresis.addEventListener('input', () => valHysteresis.textContent = parseFloat(cfgHysteresis.value).toFixed(2));
cfgCooldown.addEventListener('input', () => valCooldown.textContent = `${cfgCooldown.value} s`);

// Toast Notification
function showToast(message, type = 'success') {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `<span>${type === 'success' ? '✓' : '⚠'}</span> <span>${message}</span>`;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 4000);
}

// Fetch helper
async function apiGet(endpoint) {
  try {
    const res = await fetch(`${API_BASE}${endpoint}`);
    if (!res.ok) throw new Error(`HTTP error ${res.status}`);
    return await res.json();
  } catch (err) {
    console.debug(`API GET ${endpoint} failed:`, err);
    return null;
  }
}

async function apiPost(endpoint, body = {}) {
  try {
    const res = await fetch(`${API_BASE}${endpoint}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    if (!res.ok) throw new Error(`HTTP error ${res.status}`);
    return await res.json();
  } catch (err) {
    console.error(`API POST ${endpoint} failed:`, err);
    throw err;
  }
}

// Initialize Configuration Form
async function loadConfig() {
  const cfg = await apiGet('/api/config');
  if (cfg) {
    cfgSloLatency.value = cfg.slo_latency_target_ms;
    valSloLatency.textContent = `${cfg.slo_latency_target_ms} ms`;
    cfgTargetCpu.value = cfg.target_cpu_utilization;
    valTargetCpu.textContent = `${cfg.target_cpu_utilization} %`;
    cfgConfidence.value = cfg.confidence_threshold;
    valConfidence.textContent = cfg.confidence_threshold.toFixed(2);
    cfgHysteresis.value = cfg.deactivation_threshold;
    valHysteresis.textContent = cfg.deactivation_threshold.toFixed(2);
    cfgCooldown.value = cfg.cooldown_seconds;
    valCooldown.textContent = `${cfg.cooldown_seconds} s`;
  }
}

configForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  try {
    const payload = {
      slo_latency_target_ms: parseFloat(cfgSloLatency.value),
      target_cpu_utilization: parseFloat(cfgTargetCpu.value),
      confidence_threshold: parseFloat(cfgConfidence.value),
      deactivation_threshold: parseFloat(cfgHysteresis.value),
      cooldown_seconds: parseFloat(cfgCooldown.value),
    };
    await apiPost('/api/config', payload);
    showToast('Configuration updated and synced with Controller!', 'success');
  } catch (err) {
    showToast('Failed to update configuration', 'danger');
  }
});

// Buttons
btnStep.addEventListener('click', async () => {
  try {
    btnStep.disabled = true;
    const res = await apiPost('/api/step');
    showToast(`Operator step executed: ${res.length} services evaluated`, 'success');
    pollTelemetry();
  } catch (err) {
    showToast('Failed to trigger step', 'danger');
  } finally {
    btnStep.disabled = false;
  }
});

btnFallback.addEventListener('click', async () => {
  if (!confirm('Trigger emergency fallback? All scaling locks will be released to native Kubernetes HPA.')) return;
  try {
    btnFallback.disabled = true;
    await apiPost('/api/fallback');
    showToast('Emergency fallback active: All services released to HPA', 'danger');
    pollTelemetry();
  } catch (err) {
    showToast('Fallback execution failed', 'danger');
  } finally {
    btnFallback.disabled = false;
  }
});

// Render Microservices Cards
function renderServices(metrics, status) {
  if (!metrics || metrics.length === 0) return;
  const modes = status?.modes || {};

  elServicesGrid.innerHTML = metrics.map(s => {
    const mode = modes[s.service_id] || 'HPA';
    const isRL = mode === 'RL';
    const badgeClass = isRL ? 'badge-rl' : 'badge-hpa';
    const badgeText = isRL ? 'RL Mode' : 'HPA Fallback';
    const cpuClass = s.cpu_utilization > 75 ? 'fill-cpu high' : 'fill-cpu';
    const sloPass = s.slo_satisfied;

    return `
      <div class="service-card" id="card-${s.service_id}">
        <div class="service-header">
          <span class="service-name">${s.service_id}</span>
          <span class="service-badge ${badgeClass}">${badgeText}</span>
        </div>

        <div class="service-stat-row">
          <span class="stat-label">Provisioned Replicas</span>
          <div>
            <span class="replica-count">${s.replica_count}</span>
            <span class="replica-label">pods</span>
          </div>
        </div>

        <div class="progress-group">
          <div class="progress-header">
            <span>CPU Utilization</span>
            <span class="progress-val">${s.cpu_utilization.toFixed(1)}%</span>
          </div>
          <div class="progress-track">
            <div class="${cpuClass} progress-fill" style="width: ${Math.min(100, s.cpu_utilization)}%"></div>
          </div>
        </div>

        <div class="progress-group">
          <div class="progress-header">
            <span>Memory Utilization</span>
            <span class="progress-val">${s.memory_utilization.toFixed(1)}%</span>
          </div>
          <div class="progress-track">
            <div class="fill-mem progress-fill" style="width: ${Math.min(100, s.memory_utilization)}%"></div>
          </div>
        </div>

        <div class="service-footer-stats">
          <div class="footer-stat-box">
            <span class="stat-label">Throughput</span>
            <span class="footer-stat-val">${s.request_rate.toFixed(1)} rps</span>
          </div>
          <div class="footer-stat-box">
            <span class="stat-label">Latency</span>
            <span class="footer-stat-val">${s.latency_ms.toFixed(1)} ms</span>
            <span class="slo-badge ${sloPass ? 'slo-pass' : 'slo-breach'}">
              ${sloPass ? 'SLO PASS' : 'SLO BREACH'}
            </span>
          </div>
        </div>
      </div>
    `;
  }).join('');
}

// Render Dependency Call Graph
function renderGraph(graph, status) {
  if (!graph || !graph.nodes || graph.nodes.length === 0) return;
  const modes = status?.modes || {};

  let html = '';
  graph.nodes.forEach((node, idx) => {
    const mode = modes[node.id] || 'HPA';
    const isRL = mode === 'RL';
    const modeClass = isRL ? 'rl-active' : 'hpa-active';

    html += `
      <div class="graph-node ${modeClass}">
        <span class="node-title">${node.label}</span>
        <span class="node-meta">Tier ${idx + 1} • ${isRL ? 'RL Locked' : 'HPA Governed'}</span>
      </div>
    `;

    // Connect to next node if an edge exists
    if (idx < graph.nodes.length - 1) {
      const nextNode = graph.nodes[idx + 1];
      const edge = graph.edges.find(e => e.source === node.id && e.target === nextNode.id);
      const weight = edge ? edge.weight.toFixed(1) : '1.0';

      html += `
        <div class="graph-edge">
          <span class="edge-weight-tag">EMA: ${weight} rps</span>
          <div class="edge-line"></div>
        </div>
      `;
    }
  });

  elGraphFlow.innerHTML = html;
}

// Render SVG Sparkline / Area Chart
function renderSvgChart(svgId, points, key, strokeColor, fillColor, threshold = null, thresholdColor = '#ef4444') {
  const svg = document.getElementById(svgId);
  if (!svg || !points || points.length < 2) return;

  const width = 500;
  const height = 180;
  const padding = { top: 20, right: 15, bottom: 25, left: 40 };

  const values = points.map(p => p[key]);
  let minVal = Math.min(...values);
  let maxVal = Math.max(...values);
  if (threshold !== null) {
    maxVal = Math.max(maxVal, threshold * 1.15);
  }
  if (maxVal === minVal) maxVal += 1.0;
  minVal = Math.max(0, minVal * 0.85);

  const plotW = width - padding.left - padding.right;
  const plotH = height - padding.top - padding.bottom;

  const getX = (i) => padding.left + (i / (points.length - 1)) * plotW;
  const getY = (v) => padding.top + plotH - ((v - minVal) / (maxVal - minVal)) * plotH;

  // Build smooth path
  let pathD = `M ${getX(0)} ${getY(values[0])}`;
  for (let i = 1; i < values.length; i++) {
    const prevX = getX(i - 1);
    const prevY = getY(values[i - 1]);
    const currX = getX(i);
    const currY = getY(values[i]);
    const cpX1 = prevX + (currX - prevX) / 2;
    const cpX2 = prevX + (currX - prevX) / 2;
    pathD += ` C ${cpX1} ${prevY}, ${cpX2} ${currY}, ${currX} ${currY}`;
  }

  // Area fill path
  const areaD = `${pathD} L ${getX(values.length - 1)} ${padding.top + plotH} L ${getX(0)} ${padding.top + plotH} Z`;

  let thresholdSvg = '';
  if (threshold !== null && threshold >= minVal && threshold <= maxVal) {
    const threshY = getY(threshold);
    thresholdSvg = `
      <line x1="${padding.left}" y1="${threshY}" x2="${width - padding.right}" y2="${threshY}" 
            stroke="${thresholdColor}" stroke-dasharray="4,4" stroke-width="1.5" opacity="0.75" />
      <text x="${width - padding.right - 5}" y="${threshY - 5}" fill="${thresholdColor}" font-size="10" font-family="JetBrains Mono" text-anchor="end">
        Target: ${threshold}
      </text>
    `;
  }

  svg.innerHTML = `
    <defs>
      <linearGradient id="grad-${svgId}" x1="0%" y1="0%" x2="0%" y2="100%">
        <stop offset="0%" stop-color="${fillColor}" stop-opacity="0.4" />
        <stop offset="100%" stop-color="${fillColor}" stop-opacity="0.0" />
      </linearGradient>
    </defs>
    <!-- Axis lines -->
    <line x1="${padding.left}" y1="${padding.top + plotH}" x2="${width - padding.right}" y2="${padding.top + plotH}" stroke="rgba(255,255,255,0.08)" stroke-width="1" />
    <text x="${padding.left - 8}" y="${padding.top + 10}" fill="#64748b" font-size="10" font-family="JetBrains Mono" text-anchor="end">${maxVal.toFixed(0)}</text>
    <text x="${padding.left - 8}" y="${padding.top + plotH}" fill="#64748b" font-size="10" font-family="JetBrains Mono" text-anchor="end">${minVal.toFixed(0)}</text>
    <!-- Area & Line -->
    <path d="${areaD}" fill="url(#grad-${svgId})" />
    <path d="${pathD}" fill="none" stroke="${strokeColor}" stroke-width="2.5" stroke-linecap="round" />
    ${thresholdSvg}
  `;
}

// Render Decisions Table
function renderDecisions(decisions) {
  if (!decisions || decisions.length === 0) {
    elDecisionsTable.innerHTML = `<tr><td colspan="7" class="loading-cell">No scaling events recorded yet.</td></tr>`;
    return;
  }

  elDecisionsTable.innerHTML = decisions.slice(0, 15).map(d => {
    const isRL = d.chosen_mode === 'RL';
    const modeBadge = isRL
      ? `<span class="service-badge badge-rl">RL</span>`
      : `<span class="service-badge badge-hpa">HPA</span>`;

    const confText = d.confidence !== null ? `${(d.confidence * 100).toFixed(0)}%` : 'N/A';
    const actionText = d.action_applied !== null
      ? (d.action_applied > 0 ? `+${d.action_applied} (Scale Up)` : (d.action_applied < 0 ? `${d.action_applied} (Scale Down)` : '0 (Maintain)'))
      : 'Maintain';

    return `
      <tr>
        <td style="color: #fff; font-weight: 600;">${d.service_id}</td>
        <td>${modeBadge}</td>
        <td style="color: ${d.confidence >= 0.7 ? '#10b981' : '#f59e0b'}; font-weight: 600;">${confText}</td>
        <td style="font-weight: 700; color: #fff;">${d.target_replicas}</td>
        <td>${actionText}</td>
        <td>${d.lock_acquired ? '🔒 Acquired' : '—'}</td>
        <td style="color: #94a3b8;">${d.reason}</td>
      </tr>
    `;
  }).join('');
}

// Main Polling Loop
async function pollTelemetry() {
  if (isPolling) return;
  isPolling = true;

  try {
    const [status, metrics, history, decisions, graph, cfg] = await Promise.all([
      apiGet('/api/status'),
      apiGet('/api/metrics'),
      apiGet('/api/history'),
      apiGet('/api/decisions'),
      apiGet('/api/graph'),
      apiGet('/api/config')
    ]);

    // Update Header Status
    if (status) {
      elClusterStatusText.textContent = status.is_live_cluster ? 'MINIKUBE LIVE' : 'CLUSTER HEALTHY';
      const allRL = Object.values(status.modes).every(m => m === 'RL');
      const allHPA = Object.values(status.modes).every(m => m === 'HPA');
      elGlobalModeText.textContent = allRL ? 'ALL RL ACTIVE' : (allHPA ? 'NATIVE HPA FALLBACK' : 'HYBRID SCALING');
    }

    // Render Cards & Graph
    if (metrics) renderServices(metrics, status);
    if (graph) renderGraph(graph, status);
    if (decisions) renderDecisions(decisions);

    // Update Charts
    if (history && history.length > 1) {
      const latest = history[history.length - 1];
      const sloTarget = cfg?.slo_latency_target_ms || 100.0;
      const cpuTarget = cfg?.target_cpu_utilization || 70.0;

      elLiveLatency.textContent = `${latest.latency_ms.toFixed(1)} ms`;
      elLiveCpu.textContent = `${latest.cpu_utilization.toFixed(1)} %`;
      elLiveRps.textContent = `${latest.request_rate.toFixed(1)} rps`;
      elLiveReps.textContent = `${latest.total_replicas} pods`;

      renderSvgChart('chart-latency', history, 'latency_ms', '#ec4899', '#ec4899', sloTarget, '#ef4444');
      renderSvgChart('chart-cpu', history, 'cpu_utilization', '#00f2fe', '#00f2fe', cpuTarget, '#f59e0b');
      renderSvgChart('chart-rps', history, 'request_rate', '#10b981', '#10b981');
      renderSvgChart('chart-replicas', history, 'total_replicas', '#3b82f6', '#3b82f6');
    }
  } catch (err) {
    console.error('Error during telemetry poll:', err);
  } finally {
    isPolling = false;
  }
}

// Boot
loadConfig();
pollTelemetry();
setInterval(pollTelemetry, 2000);
