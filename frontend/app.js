const API_BASE = '';

const statusDot = document.getElementById('statusDot');
const statusText = document.getElementById('statusText');
const incidentSelect = document.getElementById('incidentSelect');
const investigateBtn = document.getElementById('investigateBtn');
const sessionInfo = document.getElementById('sessionInfo');
const sessionId = document.getElementById('sessionId');
const sessionStatus = document.getElementById('sessionStatus');
const agentGraph = document.getElementById('agentGraph');
const logsPanel = document.getElementById('logsPanel');
const logContainer = document.getElementById('logContainer');
const briefPanel = document.getElementById('briefPanel');

let retryCount = 0;
const MAX_RETRIES = 3;

async function init() {
  await loadIncidentsWithRetry();
  investigateBtn.addEventListener('click', startInvestigation);
  incidentSelect.addEventListener('change', () => {
    investigateBtn.disabled = !incidentSelect.value;
  });
}

async function loadIncidentsWithRetry() {
  for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
    try {
      const resp = await fetch(`${API_BASE}/api/v1/incidents`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      incidentSelect.innerHTML = '<option value="">-- Choose incident --</option>';
      data.incidents.forEach(inc => {
        const opt = document.createElement('option');
        opt.value = inc.id;
        const sev = inc.severity.toUpperCase();
        opt.textContent = `[${sev}] ${inc.id} - ${inc.title} (${inc.service})`;
        incidentSelect.appendChild(opt);
      });
      retryCount = 0;
      return;
    } catch (err) {
      console.error(`Failed to load incidents (attempt ${attempt}/${MAX_RETRIES}):`, err);
      if (attempt === MAX_RETRIES) {
        incidentSelect.innerHTML = '<option value="">Failed to load (refresh to retry)</option>';
      } else {
        await new Promise(r => setTimeout(r, 1000 * attempt));
      }
    }
  }
}

function setStatus(state, text) {
  statusDot.className = 'status-dot ' + state;
  statusText.textContent = text;
}

function updateNodeState(nodeId, state) {
  const node = document.getElementById('node-' + nodeId);
  const status = document.getElementById('status-' + nodeId);
  if (!node || !status) return;
  node.className = 'graph-node';
  if (state === 'active') {
    node.classList.add('active');
    status.textContent = '⏳';
  } else if (state === 'done') {
    node.classList.add('done');
    status.textContent = '✅';
  } else if (state === 'failed') {
    node.classList.add('failed');
    status.textContent = '❌';
  } else {
    status.textContent = '⏳';
  }
}

function resetGraph() {
  ['router', 'source_fetch', 'analyst', 'reporter'].forEach(id => updateNodeState(id, 'pending'));
}

function addLogEntry(time, agent, action) {
  const entry = document.createElement('div');
  entry.className = 'log-entry';
  entry.innerHTML = `
    <span class="log-time">${time}</span>
    <span class="log-agent">[${agent}]</span>
    <span class="log-action">${action}</span>
  `;
  const empty = logContainer.querySelector('.log-empty');
  if (empty) empty.remove();
  logContainer.appendChild(entry);
  logContainer.scrollTop = logContainer.scrollHeight;
}

function clearLogs() {
  logContainer.innerHTML = '<div class="log-empty">Waiting for investigation...</div>';
}

async function startInvestigation() {
  const incidentId = incidentSelect.value;
  if (!incidentId) return;

  investigateBtn.disabled = true;
  clearLogs();
  resetGraph();
  briefPanel.style.display = 'none';
  agentGraph.style.display = 'block';
  logsPanel.style.display = 'block';
  sessionInfo.style.display = 'block';

  setStatus('running', 'Investigating...');
  sessionStatus.className = 'status-badge running';
  sessionStatus.textContent = 'Running';

  updateNodeState('router', 'active');
  addLogEntry(new Date().toISOString(), 'system', `Starting investigation for incident ${incidentId}`);

  try {
    const resp = await fetch(`${API_BASE}/api/v1/investigate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ incident_id: incidentId }),
    });

    if (!resp.ok) {
      const errData = await resp.json().catch(() => ({ detail: 'Unknown error' }));
      throw new Error(errData.detail || `HTTP ${resp.status}`);
    }

    const result = await resp.json();
    sessionId.textContent = result.session_id;

    try {
      renderLogs(result.logs);
      renderBrief(result.brief);
    } catch (renderErr) {
      console.error('Rendering error:', renderErr);
      addLogEntry(new Date().toISOString(), 'system', 'Error displaying results: ' + renderErr.message);
    }

    sessionStatus.textContent = 'Completed';
    sessionStatus.className = 'status-badge completed';
    setStatus('done', 'Completed');

  } catch (err) {
    console.error('Investigation failed:', err);
    setStatus('error', 'Failed: ' + err.message);
    sessionStatus.textContent = 'Failed';
    sessionStatus.className = 'status-badge failed';
    addLogEntry(new Date().toISOString(), 'system', 'Error: ' + err.message);
    updateNodeState('router', 'failed');
  } finally {
    investigateBtn.disabled = false;
  }
}

const STAGE_ORDER = ['router', 'source_fetch', 'analyst', 'reporter'];
const STAGE_INDEX = Object.fromEntries(STAGE_ORDER.map((s, i) => [s, i]));

function renderLogs(logs) {
  let currentStageIdx = -1;
  logs.forEach(log => {
    addLogEntry(log.timestamp, log.agent, log.action);

    if (log.agent === 'system') {
      if (log.action.includes('Error') || log.action === 'Exception') {
        const failedStage = log.detail ? log.detail.split(' ')[0] : null;
        if (failedStage && STAGE_INDEX[failedStage] !== undefined) {
          updateNodeState(failedStage, 'failed');
        } else {
          updateNodeState(STAGE_ORDER[currentStageIdx] || 'router', 'failed');
        }
      }
      return;
    }

    if (log.action === 'Agent completed') {
      const stageIdx = STAGE_INDEX[log.agent];
      if (stageIdx !== undefined) {
        updateNodeState(log.agent, 'done');
        currentStageIdx = stageIdx;
        const nextStage = STAGE_ORDER[stageIdx + 1];
        if (nextStage) {
          updateNodeState(nextStage, 'active');
        }
      }
    }
  });
}

function renderBrief(brief) {
  if (!brief) return;
  briefPanel.style.display = 'block';

  document.getElementById('briefId').textContent = brief.incident_id;
  document.getElementById('briefService').textContent = brief.service;
  document.getElementById('briefSeverity').textContent = brief.severity.toUpperCase();
  document.getElementById('briefStatus').textContent = brief.status;

  const badge = document.getElementById('confidenceBadge');
  const score = Math.round(brief.confidence_score * 100);
  badge.textContent = `Confidence: ${score}%`;
  badge.className = 'confidence-badge ' + (
    score >= 70 ? 'high' : score >= 40 ? 'medium' : 'low'
  );

  document.getElementById('briefSummary').textContent = brief.summary;

  const timelineEl = document.getElementById('briefTimeline');
  timelineEl.innerHTML = '';
  (brief.timeline || []).forEach(event => {
    const item = document.createElement('div');
    item.className = 'timeline-item';
    item.innerHTML = `
      <span class="timeline-time">${event.time}</span>
      <span class="timeline-source">${event.source.toUpperCase()}</span>
      <span class="timeline-event">${event.event}</span>
    `;
    timelineEl.appendChild(item);
  });

  const hypothesesEl = document.getElementById('briefHypotheses');
  hypothesesEl.innerHTML = '';
  (brief.hypotheses || []).forEach(h => {
    const card = document.createElement('div');
    card.className = 'hypothesis-card';
    const confPct = Math.round(h.confidence * 100);
    const confClass = confPct >= 70 ? 'high' : confPct >= 40 ? 'medium' : 'low';
    let evidenceHtml = '';
    if (h.supporting_evidence && h.supporting_evidence.length) {
      evidenceHtml = '<ul class="hypothesis-evidence">' +
        h.supporting_evidence.filter(e => e).map(e => `<li>${e}</li>`).join('') +
        '</ul>';
    }
    let sourcesHtml = '';
    if (h.source_signals && h.source_signals.length) {
      sourcesHtml = '<div class="hypothesis-sources">' +
        h.source_signals.map(s => `<span class="source-chip ${s}">${s}</span>`).join('') +
        '</div>';
    }
    card.innerHTML = `
      <div class="hypothesis-rank">#${h.rank} Hypothesis</div>
      <div class="hypothesis-title">${h.title}</div>
      <span class="hypothesis-confidence ${confClass}">${confPct}% confidence</span>
      <div class="hypothesis-desc">${h.description}</div>
      ${evidenceHtml}
      ${sourcesHtml}
    `;
    hypothesesEl.appendChild(card);
  });

  document.getElementById('briefAction').innerHTML = brief.recommended_action || 'No action recommended';

  renderServiceImpact(brief.service_impact);

  const sourcesEl = document.getElementById('briefSources');
  sourcesEl.innerHTML = '';
  (brief.evidence_sources || []).forEach(s => {
    const chip = document.createElement('span');
    chip.className = `source-chip ${s}`;
    chip.textContent = s;
    sourcesEl.appendChild(chip);
  });
}

function renderServiceImpact(impact) {
  const el = document.getElementById('briefImpact');
  if (!impact) {
    el.innerHTML = '<div class="impact-container">No impact data available.</div>';
    return;
  }

  const blastClass = impact.estimated_blast_percentage >= 60 ? 'high'
    : impact.estimated_blast_percentage >= 35 ? 'medium' : 'low';

  const customerStatus = impact.customer_facing
    ? '<span class="impact-value danger">Yes — customer-facing service</span>'
    : '<span class="impact-value ok">No — internal service</span>';

  const downstreamHtml = impact.downstream_services && impact.downstream_services.length
    ? impact.downstream_services.map(s => `<span class="impact-chip">${s}</span>`).join('')
    : '<span style="color:#8b949e;font-size:0.8rem;">None</span>';

  const externalHtml = impact.external_dependencies_impacted && impact.external_dependencies_impacted.length
    ? impact.external_dependencies_impacted.map(s => `<span class="impact-chip external">${s}</span>`).join('')
    : '<span style="color:#8b949e;font-size:0.8rem;">None</span>';

  const endpointsHtml = impact.affected_endpoints && impact.affected_endpoints.length
    ? impact.affected_endpoints.map(e => `<span class="impact-chip">${e}</span>`).join('')
    : '<span style="color:#8b949e;font-size:0.8rem;">Unknown</span>';

  el.innerHTML = `
    <div class="impact-grid">
      <div class="impact-item">
        <span class="impact-label">Affected Service</span>
        <span class="impact-value">${impact.affected_service}</span>
      </div>
      <div class="impact-item">
        <span class="impact-label">Customer Impact</span>
        ${customerStatus}
      </div>
    </div>
    <div class="blast-bar-container">
      <div class="blast-bar-label">
        <span>Blast Radius</span>
        <span>${impact.estimated_blast_percentage}%</span>
      </div>
      <div class="blast-bar-track">
        <div class="blast-bar-fill ${blastClass}" style="width:${impact.estimated_blast_percentage}%"></div>
      </div>
    </div>
    <div style="margin-top:14px;">
      <div class="blast-bar-label" style="margin-bottom:6px;">
        <span>Downstream Services</span>
      </div>
      <div class="impact-list">${downstreamHtml}</div>
    </div>
    <div style="margin-top:10px;">
      <div class="blast-bar-label" style="margin-bottom:6px;">
        <span>External Dependencies</span>
      </div>
      <div class="impact-list">${externalHtml}</div>
    </div>
    <div style="margin-top:10px;">
      <div class="blast-bar-label" style="margin-bottom:6px;">
        <span>Affected Endpoints</span>
      </div>
      <div class="impact-list">${endpointsHtml}</div>
    </div>
  `;
}

init();
