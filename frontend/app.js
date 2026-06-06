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

const MAX_RETRIES = 3;
const STAGE_ORDER = ['router', 'source_fetch', 'analyst', 'reporter'];
const STAGE_INDEX = Object.fromEntries(STAGE_ORDER.map((s, i) => [s, i]));

async function init() {
  setStatus('ready', 'Ready');
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
      (data.incidents || []).forEach(inc => {
        const opt = document.createElement('option');
        opt.value = inc.id;
        const sev = String(inc.severity || 'unknown').toUpperCase();
        opt.textContent = `[${sev}] ${inc.id} - ${inc.title} (${inc.service})`;
        incidentSelect.appendChild(opt);
      });
      investigateBtn.disabled = !incidentSelect.value;
      return;
    } catch (err) {
      console.error(`Failed to load incidents (attempt ${attempt}/${MAX_RETRIES}):`, err);
      if (attempt === MAX_RETRIES) {
        incidentSelect.innerHTML = '<option value="">Failed to load (refresh to retry)</option>';
        setStatus('error', 'Unable to load incidents');
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
    status.textContent = '○';
  }
}

function resetGraph() {
  STAGE_ORDER.forEach(id => updateNodeState(id, 'pending'));
}

function addLogEntry(time, agent, action) {
  const entry = document.createElement('div');
  entry.className = 'log-entry';
  entry.appendChild(makeSpan('log-time', time || '-'));
  entry.appendChild(makeSpan('log-agent', `[${agent || 'system'}]`));
  entry.appendChild(makeSpan('log-action', action || ''));

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
  sessionId.textContent = '-';

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
    sessionId.textContent = result.session_id || '-';
    renderLogs(result.logs || []);

    if (result.status !== 'completed') {
      const failedStage = result.stage || inferFailedStage(result.logs || []);
      if (failedStage) updateNodeState(failedStage, 'failed');
      sessionStatus.textContent = 'Failed';
      sessionStatus.className = 'status-badge failed';
      setStatus('error', result.error ? `Failed: ${result.error}` : 'Investigation failed');
      if (result.error) addLogEntry(new Date().toISOString(), 'system', `Error: ${result.error}`);
      return;
    }

    renderBrief(result.brief);
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
    investigateBtn.disabled = !incidentSelect.value;
  }
}

function renderLogs(logs) {
  let currentStageIdx = -1;
  logs.forEach(log => {
    addLogEntry(log.timestamp, log.agent, log.action);

    if (log.agent === 'system') return;

    if (log.action === 'Agent failed' || log.action === 'Exception') {
      updateNodeState(log.agent, 'failed');
      return;
    }

    if (log.action === 'Agent completed') {
      const stageIdx = STAGE_INDEX[log.agent];
      if (stageIdx !== undefined) {
        updateNodeState(log.agent, 'done');
        currentStageIdx = stageIdx;
        const nextStage = STAGE_ORDER[stageIdx + 1];
        if (nextStage) updateNodeState(nextStage, 'active');
      }
    }
  });

  if (currentStageIdx === STAGE_ORDER.length - 1) {
    updateNodeState('reporter', 'done');
  }
}

function inferFailedStage(logs) {
  const failedLog = [...logs].reverse().find(log => log.action === 'Agent failed' || log.action === 'Exception');
  return failedLog ? failedLog.agent : null;
}

function renderBrief(brief) {
  if (!brief) {
    addLogEntry(new Date().toISOString(), 'system', 'Investigation completed without a brief.');
    return;
  }
  briefPanel.style.display = 'block';

  setText('briefId', brief.incident_id);
  setText('briefService', brief.service);
  setText('briefSeverity', String(brief.severity || '').toUpperCase());
  setText('briefStatus', brief.status);

  const badge = document.getElementById('confidenceBadge');
  const score = Math.round((brief.confidence_score || 0) * 100);
  badge.textContent = `Confidence: ${score}%`;
  badge.className = 'confidence-badge ' + (score >= 70 ? 'high' : score >= 40 ? 'medium' : 'low');

  setText('briefSummary', brief.summary, 'No summary available');
  renderTimeline(brief.timeline || []);
  renderHypotheses(brief.hypotheses || []);

  const actionEl = document.getElementById('briefAction');
  actionEl.textContent = brief.recommended_action || 'No action recommended';

  renderServiceImpact(brief.service_impact);
  renderSources(brief.evidence_sources || []);
}

function renderTimeline(timeline) {
  const timelineEl = document.getElementById('briefTimeline');
  clearElement(timelineEl);
  if (!timeline.length) {
    timelineEl.appendChild(makeEmpty('No timeline events available.'));
    return;
  }
  timeline.forEach(event => {
    const item = document.createElement('div');
    item.className = 'timeline-item';
    item.appendChild(makeSpan('timeline-time', event.time || 'unknown'));
    item.appendChild(makeSpan('timeline-source', String(event.source || 'source').toUpperCase()));
    item.appendChild(makeSpan('timeline-event', event.event || ''));
    timelineEl.appendChild(item);
  });
}

function renderHypotheses(hypotheses) {
  const hypothesesEl = document.getElementById('briefHypotheses');
  clearElement(hypothesesEl);
  if (!hypotheses.length) {
    hypothesesEl.appendChild(makeEmpty('No hypotheses generated.'));
    return;
  }

  hypotheses.forEach(h => {
    const card = document.createElement('div');
    card.className = 'hypothesis-card';
    const confPct = Math.round((h.confidence || 0) * 100);
    const confClass = confPct >= 70 ? 'high' : confPct >= 40 ? 'medium' : 'low';

    const evidenceHtml = (h.supporting_evidence || []).filter(Boolean).length
      ? '<ul class="hypothesis-evidence">' +
        h.supporting_evidence.filter(Boolean).map(e => `<li>${escapeHTML(e)}</li>`).join('') +
        '</ul>'
      : '';

    const sourcesHtml = (h.source_signals || []).length
      ? '<div class="hypothesis-sources">' +
        h.source_signals.map(s => `<span class="source-chip ${safeClass(s)}">${escapeHTML(s)}</span>`).join('') +
        '</div>'
      : '';

    card.innerHTML = `
      <div class="hypothesis-rank">#${escapeHTML(h.rank)} Hypothesis</div>
      <div class="hypothesis-title">${escapeHTML(h.title)}</div>
      <span class="hypothesis-confidence ${confClass}">${confPct}% confidence</span>
      <div class="hypothesis-desc">${escapeHTML(h.description)}</div>
      ${evidenceHtml}
      ${sourcesHtml}
    `;
    hypothesesEl.appendChild(card);
  });
}

function renderSources(sources) {
  const sourcesEl = document.getElementById('briefSources');
  clearElement(sourcesEl);
  if (!sources.length) {
    sourcesEl.appendChild(makeEmpty('No evidence sources recorded.'));
    return;
  }
  sources.forEach(s => {
    const chip = document.createElement('span');
    chip.className = `source-chip ${safeClass(s)}`;
    chip.textContent = s;
    sourcesEl.appendChild(chip);
  });
}

function renderServiceImpact(impact) {
  const el = document.getElementById('briefImpact');
  if (!impact) {
    el.textContent = 'No impact data available.';
    return;
  }

  const blast = Number(impact.estimated_blast_percentage || 0);
  const blastClass = blast >= 60 ? 'high' : blast >= 35 ? 'medium' : 'low';
  const customerStatus = impact.customer_facing
    ? '<span class="impact-value danger">Yes — customer-facing service</span>'
    : '<span class="impact-value ok">No — internal service</span>';

  const downstreamHtml = chipList(impact.downstream_services, 'impact-chip', 'None');
  const externalHtml = chipList(impact.external_dependencies_impacted, 'impact-chip external', 'None');
  const endpointsHtml = chipList(impact.affected_endpoints, 'impact-chip', 'Unknown');

  el.innerHTML = `
    <div class="impact-grid">
      <div class="impact-item">
        <span class="impact-label">Affected Service</span>
        <span class="impact-value">${escapeHTML(impact.affected_service)}</span>
      </div>
      <div class="impact-item">
        <span class="impact-label">Customer Impact</span>
        ${customerStatus}
      </div>
    </div>
    <div class="blast-bar-container">
      <div class="blast-bar-label">
        <span>Blast Radius</span>
        <span>${blast}%</span>
      </div>
      <div class="blast-bar-track">
        <div class="blast-bar-fill ${blastClass}" style="width:${Math.max(0, Math.min(100, blast))}%"></div>
      </div>
    </div>
    <div style="margin-top:14px;">
      <div class="blast-bar-label" style="margin-bottom:6px;"><span>Downstream Services</span></div>
      <div class="impact-list">${downstreamHtml}</div>
    </div>
    <div style="margin-top:10px;">
      <div class="blast-bar-label" style="margin-bottom:6px;"><span>External Dependencies Impacted</span></div>
      <div class="impact-list">${externalHtml}</div>
    </div>
    <div style="margin-top:10px;">
      <div class="blast-bar-label" style="margin-bottom:6px;"><span>Affected Endpoints</span></div>
      <div class="impact-list">${endpointsHtml}</div>
    </div>
  `;
}

function chipList(items, className, emptyText) {
  if (items && items.length) {
    return items.map(item => `<span class="${className}">${escapeHTML(item)}</span>`).join('');
  }
  return `<span style="color:#8b949e;font-size:0.8rem;">${escapeHTML(emptyText)}</span>`;
}

function makeSpan(className, text) {
  const span = document.createElement('span');
  span.className = className;
  span.textContent = text;
  return span;
}

function makeEmpty(text) {
  const div = document.createElement('div');
  div.className = 'log-empty';
  div.textContent = text;
  return div;
}

function setText(id, value, fallback = '-') {
  document.getElementById(id).textContent = value || fallback;
}

function clearElement(el) {
  while (el.firstChild) el.removeChild(el.firstChild);
}

function escapeHTML(value) {
  const div = document.createElement('div');
  div.textContent = value == null ? '' : String(value);
  return div.innerHTML;
}

function safeClass(value) {
  return String(value || '').toLowerCase().replace(/[^a-z0-9_-]/g, '-');
}

init();
