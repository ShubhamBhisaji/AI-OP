'use strict';

/* ══ Config ════════════════════════════════════════════════════════ */
const _LOCAL_HOSTS = new Set(['localhost', '127.0.0.1', '0.0.0.0', '[::1]']);
const _NETWORK_ERROR_RE = /failed to fetch|networkerror|err_connection|econnrefused|err_name_not_resolved|timeout/i;

function _defaultApiBase() {
  return location.origin.replace(/\/+$/, '');
}

function _isLocalHost(hostname) {
  const host = String(hostname || '').trim().toLowerCase();
  if (!host) return false;
  return _LOCAL_HOSTS.has(host) || host.endsWith('.localhost') || host.endsWith('.local');
}

function _formatApiBase(urlObj) {
  const normalized = (urlObj.origin + urlObj.pathname).replace(/\/+$/, '');
  return normalized.replace(/\/api$/i, '');
}

function _normalizeApiBase(rawValue) {
  const value = String(rawValue || '').trim();
  if (!value) return '';
  try {
    return _formatApiBase(new URL(value, location.origin));
  } catch (_) {
    return value.replace(/\/+$/, '');
  }
}

function _resolveApiBase() {
  const fallback = _defaultApiBase();
  const savedValue = localStorage.getItem('aetheer_api_url');
  const savedBase = _normalizeApiBase(savedValue);
  if (!savedBase) return fallback;

  try {
    const savedUrl = new URL(savedBase, location.origin);
    if (!_isLocalHost(location.hostname) && _isLocalHost(savedUrl.hostname)) {
      localStorage.removeItem('aetheer_api_url');
      return fallback;
    }
    return _formatApiBase(savedUrl);
  } catch (_) {
    localStorage.removeItem('aetheer_api_url');
    return fallback;
  }
}

let API_BASE = _resolveApiBase();
let _JWT_TOKEN = localStorage.getItem('aetheer_jwt_token') || '';
let _CURRENT_USER = null;
let _authCheckInProgress = false;
let _authBusy = false;
let _activeAiProvider = '';
const _DEFAULT_AI_PROVIDERS = ['github', 'openai', 'claude', 'gemini', 'ollama'];
const _PROVIDER_DEFAULT_MODEL = {
  openai: 'gpt-4o',
  gemini: 'gemini-2.5-flash-lite',
  ollama: 'llama3.2:1b'
};
let _providerSwitchBusy = false;
const AUTH_LOGIN_SUBTITLE = 'Access your Tecbunny-built AetheerAI workspace';
const AUTH_REGISTER_SUBTITLE = 'Create your Tecbunny operator account';

function _usingCustomApiBase() {
  return _normalizeApiBase(API_BASE) !== _normalizeApiBase(_defaultApiBase());
}

function updateApiConnectionState() {
  const input = document.getElementById('settings-api-url');
  const status = document.getElementById('settings-api-status');
  if (!input || !status) return;

  const currentAppBase = _defaultApiBase();
  input.placeholder = currentAppBase;
  status.textContent = _usingCustomApiBase()
    ? 'Custom backend active. Change this only if your API lives on a different domain.'
    : 'Using the current app backend. You do not need to change this unless the API is hosted separately.';
}

function _normalizeProviderName(value) {
  return String(value || '').trim().toLowerCase();
}

function setActiveAiProvider(provider) {
  _activeAiProvider = _normalizeProviderName(provider);
}

function updateTopbarProviderApplyState() {
  const topbarSelect = document.getElementById('topbar-provider-select');
  const topbarApplyBtn = document.getElementById('topbar-provider-apply');
  if (!topbarSelect || !topbarApplyBtn) return;

  if (!_CURRENT_USER || _providerSwitchBusy) {
    topbarApplyBtn.disabled = true;
    return;
  }

  const selected = _normalizeProviderName(topbarSelect.value);
  const active = _normalizeProviderName(_activeAiProvider);
  topbarApplyBtn.disabled = !selected || !active || selected === active;
}

/* ══ API helper ════════════════════════════════════════════════════ */
async function apiFetch(path, opts = {}) {
  const url = API_BASE + path;
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  const isPublicPath = path === '/api/health' || path.startsWith('/api/auth/login') || path.startsWith('/api/auth/register');
  const isAuthStateCheck = path === '/api/auth/me';

  if (!_JWT_TOKEN && !isPublicPath) {
    throw new Error('Unauthorized (401): please sign in to access protected endpoints.');
  }
  
  // Use JWT token for authentication
  if (_JWT_TOKEN) {
    headers['Authorization'] = 'Bearer ' + _JWT_TOKEN;
  }
  
  const res = await fetch(url, { ...opts, headers });
  const json = await res.json().catch(() => ({}));
  if (!res.ok) {
    let msg = json.detail || json.error || `HTTP ${res.status}`;
    if (res.status === 401) {
      if (_JWT_TOKEN && isAuthStateCheck) {
        msg = 'Session expired or invalid token. Please sign in again.';
        _JWT_TOKEN = '';
        _CURRENT_USER = null;
        localStorage.removeItem('aetheer_jwt_token');
        showLandingPage();
      } else if (!_JWT_TOKEN) {
        msg = 'Unauthorized (401): please sign in to access protected endpoints.';
      }
    }
    throw new Error(msg);
  }
  return json;
}

/* ══ Toast ══════════════════════════════════════════════════════════ */
function toast(msg, type = 'info') {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  document.getElementById('toast-container').appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

function compactLayout() {
  return window.innerWidth <= 980;
}

function setSidebarOpen(open) {
  const next = !!open;
  document.body.classList.toggle('sidebar-open', next);
  const btn = document.getElementById('menu-toggle');
  if (btn) btn.setAttribute('aria-expanded', next ? 'true' : 'false');
}

function toggleSidebar(forceOpen) {
  if (!compactLayout()) return;
  if (typeof forceOpen === 'boolean') {
    setSidebarOpen(forceOpen);
    return;
  }
  setSidebarOpen(!document.body.classList.contains('sidebar-open'));
}

function closeSidebar() {
  setSidebarOpen(false);
}

/* ══ Navigation ════════════════════════════════════════════════════ */
let currentPage = 'dashboard';

function nav(page) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
  const pageEl = document.getElementById('page-' + page);
  if (pageEl) pageEl.classList.add('active');
  const navBtn = document.querySelector(`.nav-item[data-page="${page}"]`);
  if (navBtn) navBtn.classList.add('active');
  const titles = {
    dashboard: 'Dashboard', goals: 'Goals & Projects', agents: 'Agents',
    chat: 'Chat', collaborate: 'Collaborate', memory: 'Memory OS',
    logs: 'Audit Logs', database: 'Database', settings: 'Settings',
    playground: '⚡ Playground',
    predict: 'AI Predict', upload: 'Upload Files',
    history: 'Prediction History', insights: 'Insights & Analytics',
    admin: 'Admin Panel',
  };
  const contexts = {
    dashboard: 'Mission control',
    goals: 'Execution planning',
    agents: 'Specialist roster',
    chat: 'Direct operator assist',
    collaborate: 'Multi-agent sessions',
    memory: 'Knowledge inspection',
    logs: 'Operational trace',
    database: 'Persistence overview',
    settings: 'Workspace configuration',
    playground: 'Rapid experimentation',
  };
  document.getElementById('topbar-title').textContent = titles[page] || page;
  setText('topbar-eyebrow', contexts[page] || 'Workspace');
  currentPage = page;
  closeSidebar();
  if (page === 'playground')  pgLoadAgents();
  if (page === 'goals')       loadGoals();
  if (page === 'agents')      loadAgents();
  if (page === 'memory')      loadMemory();
  if (page === 'logs')        loadLogs();
  if (page === 'database')    loadDatabase();
  if (page === 'collaborate') loadCollaborations();
  if (page === 'settings')    loadSettings();
  if (page === 'predict')     loadModelPicker();
  if (page === 'upload')      { loadUploads(); setupDropZone(); }
  if (page === 'history')     loadHistory();
  if (page === 'insights')    loadInsights();
  if (page === 'admin')       { loadAdminUsers(); loadAdminActivity(); }
}

document.querySelectorAll('.nav-item[data-page]').forEach(btn => {
  btn.addEventListener('click', () => nav(btn.dataset.page));
});

const _menuToggle = document.getElementById('menu-toggle');
if (_menuToggle) {
  _menuToggle.addEventListener('click', () => toggleSidebar());
}

const _sidebarBackdrop = document.getElementById('sidebar-backdrop');
if (_sidebarBackdrop) {
  _sidebarBackdrop.addEventListener('click', closeSidebar);
}

window.addEventListener('resize', () => {
  if (!compactLayout()) closeSidebar();
});

document.getElementById('refresh-btn').addEventListener('click', () => {
  if (currentPage === 'dashboard') loadDashboard();
  else nav(currentPage);
});

const _topbarProviderSelect = document.getElementById('topbar-provider-select');
if (_topbarProviderSelect) {
  _topbarProviderSelect.addEventListener('change', updateTopbarProviderApplyState);
}

/* ══ Tab switcher ═══════════════════════════════════════════════════ */
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const group = btn.closest('.card, div');
    const target = btn.dataset.tab;
    group.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    group.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    const pane = document.getElementById(target);
    if (pane) pane.classList.add('active');
  });
});

/* ══ Status helpers ═════════════════════════════════════════════════ */
function setOnline(on) {
  document.getElementById('status-dot').className = 'dot' + (on ? '' : ' offline');
  document.getElementById('topbar-dot').className  = 'status-dot' + (on ? '' : ' offline');
  document.getElementById('topbar-status').textContent = on ? 'Online' : 'Offline';
  const heroBadge = document.getElementById('hero-health-badge');
  if (heroBadge) {
    heroBadge.className = `badge ${on ? 'badge-green' : 'badge-red'} ml-auto`;
    heroBadge.textContent = on ? 'Live' : 'Offline';
  }
  if (!on) {
    setText('hero-status', 'API unavailable');
  }
}

function statusBadgeClass(status) {
  const m = { completed:'badge-green', running:'badge-blue', pending:'badge-yellow',
               failed:'badge-red', partial:'badge-yellow', cancelled:'badge-gray' };
  return m[status] || 'badge-gray';
}
function statusIcon(status) {
  const m = { completed:'✓', running:'⟳', pending:'·', failed:'✗', partial:'~', cancelled:'⊘' };
  return m[status] || '?';
}
function fmtCost(v) { return v != null ? `$${(+v).toFixed(4)}` : '—'; }
function fmtSeconds(s) {
  if (s == null) return '—';
  if (s < 60) return `${Math.round(s)}s`;
  return `${Math.floor(s/60)}m ${Math.round(s%60)}s`;
}
function timeAgo(ts) {
  if (!ts) return '—';
  const s = Math.floor(Date.now()/1000 - ts);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s/60)}m ago`;
  if (s < 86400) return `${Math.floor(s/3600)}h ago`;
  return `${Math.floor(s/86400)}d ago`;
}
function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

/* ══ Dashboard ══════════════════════════════════════════════════════ */
async function loadDashboard() {
  if (!_JWT_TOKEN) {
    setOnline(false);
    return;
  }

  try {
    const r = await apiFetch('/api/system/status');
    const d = r.data;
    const projects = d.projects || {};
    const uptimeText = fmtSeconds(d.uptime_seconds);
    setOnline(true);
    document.getElementById('dc-provider').textContent  = d.provider || '—';
    document.getElementById('dc-model').textContent     = d.model || '—';
    document.getElementById('dc-total').textContent     = projects.total ?? '—';
    document.getElementById('dc-running').textContent   = projects.running ?? '—';
    document.getElementById('dc-completed').textContent = projects.completed ?? '—';
    document.getElementById('dc-failed').textContent    = (projects.failed ?? 0) + (projects.cancelled ?? 0);
    document.getElementById('dc-agents').textContent    = d.agents_registered ?? '—';
    document.getElementById('dc-tools').textContent     = d.tools_registered ?? '—';
    document.getElementById('dc-memory').textContent    = d.memory_keys ?? '—';
    setText('dash-uptime', `uptime ${uptimeText}`);
    document.getElementById('sidebar-provider').textContent = d.provider || '—';
    document.getElementById('sidebar-model').textContent    = d.model || '—';
    setActiveAiProvider(d.provider);
    const quickProviderSelect = document.getElementById('topbar-provider-select');
    if (quickProviderSelect && d.provider) {
      const nextProvider = String(d.provider).trim().toLowerCase();
      const hasProvider = Array.from(quickProviderSelect.options).some(opt => opt.value === nextProvider);
      if (hasProvider) quickProviderSelect.value = nextProvider;
    }
    updateTopbarProviderApplyState();
    setText('hero-provider', d.provider ? `${d.provider}${d.model ? ` · ${d.model}` : ''}` : 'No provider');
    setText('hero-uptime', uptimeText);
    setText('hero-running', String(projects.running ?? '—'));
    setText('hero-agents', String(d.agents_registered ?? '—'));
    setText('hero-memory', String(d.memory_keys ?? '—'));
    setText('hero-status', (projects.running ?? 0) > 0 ? `${projects.running} active goal${projects.running === 1 ? '' : 's'}` : 'Standing by');
    setText('dash-last-sync', new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));

    // Badge counts for nav
    const badge = document.getElementById('nav-badge-goals');
    const active = (projects.running ?? 0) + (projects.pending ?? 0);
    badge.textContent = active || projects.total || 0;
  } catch (e) {
    setOnline(false);
    setText('dash-last-sync', 'offline');
  }

  // Load recent goals
  try {
    const r = await apiFetch('/api/goals');
    renderRecentGoals(r.data || []);
  } catch (_) {}
}

function renderRecentGoals(goals) {
  const el = document.getElementById('recent-goals-list');
  if (!goals.length) {
    el.innerHTML = `<div class="empty-state" style="padding:30px"><div class="empty-icon">🎯</div><h3>No goals yet</h3><p>Submit your first goal using the form above.</p></div>`;
    return;
  }
  const rows = goals.slice(0,5).map(g => `
    <div style="display:flex;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid var(--border)" onclick="openGoalDetail(${JSON.stringify(escHtml(g.id))})" style="cursor:pointer">
      <span class="badge ${statusBadgeClass(g.status)}">${statusIcon(g.status)} ${escHtml(g.status)}</span>
      <span style="font-weight:600;font-size:13px;color:var(--text)">${escHtml(g.name||'—')}</span>
      <span style="font-size:12px;color:var(--text3);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml((g.goal||'').slice(0,80))}</span>
      <span style="font-size:11px;color:var(--text3);flex-shrink:0">${timeAgo(g.started_at)}</span>
    </div>`).join('');
  el.innerHTML = rows;
}

async function submitGoalWithQueueFallback(payload) {
  const host = String(window.location.hostname || '').toLowerCase();
  const vercelHost = host.endsWith('.vercel.app') || host === 'project-za3zh.vercel.app';

  if (vercelHost) {
    return await apiFetch('/api/queue/jobs', {
      method: 'POST',
      body: JSON.stringify({
        task_type: 'goal',
        task_data: payload,
        priority: 'normal',
        stream_results: true
      })
    });
  }

  try {
    return await apiFetch('/api/goals', {
      method: 'POST',
      body: JSON.stringify(payload)
    });
  } catch (e) {
    const msg = String(e && e.message ? e.message : e || '');
    if (!/Direct goal execution is disabled on Vercel/i.test(msg)) {
      throw e;
    }
    return await apiFetch('/api/queue/jobs', {
      method: 'POST',
      body: JSON.stringify({
        task_type: 'goal',
        task_data: payload,
        priority: 'normal',
        stream_results: true
      })
    });
  }
}

/* Quick Goal */
document.getElementById('quick-submit-btn').addEventListener('click', async () => {
  const name = document.getElementById('quick-name').value.trim();
  const goal = document.getElementById('quick-goal').value.trim();
  if (!name || !goal) { toast('Enter a name and goal', 'error'); return; }
  const btn = document.getElementById('quick-submit-btn');
  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Running…';
  try {
    const payload = { name, goal, background: true, parallel: true };
    const r = await submitGoalWithQueueFallback(payload);
    const goalId = r.data?.id || r.data?.job_id || '';
    const idText = goalId ? ` ID: ${String(goalId).slice(0, 8)}...` : '';
    toast(`Goal accepted${idText}`, 'success');
    document.getElementById('quick-result').style.display = 'block';
    document.getElementById('quick-result').innerHTML = `<div class="alert alert-success">Goal submitted successfully. <button class="btn btn-sm btn-secondary" onclick="nav('goals')" style="margin-left:8px">View -></button></div>`;
    loadDashboard();
  } catch (e) { toast(e.message, 'error'); }
  btn.disabled = false; btn.innerHTML = '▶ Run Goal';
});

/* ══ Goals ══════════════════════════════════════════════════════════ */
let _allGoals = [];

async function loadGoals() {
  try {
    const r = await apiFetch('/api/goals');
    _allGoals = r.data || [];
    renderGoalsTable(_allGoals);
  } catch (e) { toast('Failed to load goals: ' + e.message, 'error'); }
}

function renderGoalsTable(goals) {
  const badge = document.getElementById('nav-badge-goals');
  badge.textContent = goals.length;

  if (!goals.length) {
    document.getElementById('goals-tbody').innerHTML = `<tr><td colspan="7"><div class="empty-state" style="padding:40px"><div class="empty-icon">🎯</div><h3>No goals yet</h3><p>Click "+ New Goal" to get started.</p></div></td></tr>`;
    return;
  }
  const rows = goals.map(g => {
    const pct = g.progress?.percent ?? 0;
    return `
    <tr style="cursor:pointer" onclick="openGoalDetail('${escHtml(g.id)}')">
      <td><b style="color:var(--text)">${escHtml(g.name||'—')}</b></td>
      <td style="max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text2)">${escHtml((g.goal||'').slice(0,80))}</td>
      <td><span class="badge ${statusBadgeClass(g.status)}">${escHtml(g.status||'?')}</span></td>
      <td style="min-width:120px">
        <div class="progress-bar"><div class="progress-fill" style="width:${pct}%"></div></div>
        <div style="font-size:11px;color:var(--text3);margin-top:3px">${pct}% · ${g.completed_tasks||0}/${g.total_tasks||0}</div>
      </td>
      <td style="font-size:12px;color:var(--text2)">${fmtCost(g.spent_usd)}</td>
      <td style="font-size:12px;color:var(--text2)">${g.total_tasks||0}</td>
      <td onclick="event.stopPropagation()">
        <button class="btn btn-sm btn-danger" onclick="deleteGoal('${escHtml(g.id)}')">✕</button>
      </td>
    </tr>`;
  }).join('');
  document.getElementById('goals-tbody').innerHTML = rows;
}

function openGoalModal() { document.getElementById('goal-modal').style.display = 'block'; }
function closeGoalModal() { document.getElementById('goal-modal').style.display = 'none'; }

async function submitGoal() {
  const name = document.getElementById('gm-name').value.trim();
  const goal = document.getElementById('gm-goal').value.trim();
  if (!name || !goal) { toast('Name and goal are required', 'error'); return; }
  const payload = {
    name, goal,
    background: document.getElementById('gm-background').checked,
    parallel:   document.getElementById('gm-parallel').checked,
    collaboration_mode: document.getElementById('gm-collab').checked,
  };
  const cost    = document.getElementById('gm-cost').value;
  const runtime = document.getElementById('gm-runtime').value;
  if (cost)    payload.max_cost_usd          = parseFloat(cost);
  if (runtime) payload.max_runtime_seconds   = parseInt(runtime);

  const btn = document.getElementById('gm-submit-btn');
  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Submitting…';
  try {
    await submitGoalWithQueueFallback(payload);
    toast('Goal submitted!', 'success');
    closeGoalModal();
    loadGoals();
  } catch (e) { toast(e.message, 'error'); }
  btn.disabled = false; btn.innerHTML = '▶ Submit Goal';
}

async function deleteGoal(id) {
  if (!confirm('Delete this goal/project?')) return;
  try {
    await apiFetch('/api/projects/' + id, { method: 'DELETE' });
    toast('Deleted', 'success');
    loadGoals();
  } catch (e) { toast(e.message, 'error'); }
}

async function openGoalDetail(id) {
  try {
    const r = await apiFetch('/api/goals/' + id);
    const g = r.data;
    document.getElementById('goal-detail').style.display = 'block';
    document.getElementById('gd-name').textContent = g.name || '—';
    document.getElementById('gd-goal').textContent = g.goal || '—';
    document.getElementById('gd-status-badge').className = 'badge ' + statusBadgeClass(g.status);
    document.getElementById('gd-status-badge').textContent = g.status || '?';
    const pct = g.progress?.percent ?? 0;
    document.getElementById('gd-pct').textContent = pct + '%';
    document.getElementById('gd-progress-fill').style.width = pct + '%';

    document.getElementById('gd-stats').innerHTML = [
      ['Tasks Done', g.completed_tasks||0],
      ['Tasks Failed', g.failed_tasks||0],
      ['Total Tasks', g.total_tasks||0],
      ['Cost', fmtCost(g.spent_usd)],
    ].map(([k,v]) => `<div style="background:var(--surface2);border:1px solid var(--border);border-radius:8px;padding:12px"><div style="font-size:10px;color:var(--text3);font-weight:700;text-transform:uppercase;letter-spacing:0.8px;margin-bottom:4px">${k}</div><div style="font-size:20px;font-weight:800;color:var(--text)">${v}</div></div>`).join('');

    if (g.plan_summary) {
      document.getElementById('gd-summary').innerHTML = `<div class="card" style="font-size:13px;color:var(--text2);line-height:1.7"><b style="color:var(--text)">Summary:</b><br>${escHtml(g.plan_summary)}</div>`;
    } else { document.getElementById('gd-summary').innerHTML = ''; }

    const tasks = g.tasks || [];
    document.getElementById('gd-task-count').textContent = tasks.length;
    document.getElementById('gd-task-list').innerHTML = tasks.map(t => {
      const iconMap = { completed:'✓ ',done:'✓ ', failed:'✗ ', running:'⟳ ', pending:'· ' };
      const clsMap  = { completed:'done',done:'done', failed:'fail', running:'run', pending:'pend' };
      const ic = iconMap[t.status]||'· ';
      const cl = clsMap[t.status]||'pend';
      return `<div class="task-item">
        <div class="task-icon ${cl}">${ic}</div>
        <div class="task-body">
          <div class="task-title">${escHtml(t.title||'Task #'+(t.index+1))}</div>
          <div class="task-desc">${escHtml(t.description||'')}</div>
          <div class="task-agent">${escHtml(t.agent_type||'')}</div>
        </div>
        <span class="badge ${statusBadgeClass(t.status)}" style="flex-shrink:0">${escHtml(t.status||'?')}</span>
      </div>`;
    }).join('') || '<div style="color:var(--text3);font-size:13px">No tasks recorded yet.</div>';

    document.getElementById('goal-detail').scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (e) { toast('Load error: ' + e.message, 'error'); }
}

function closeGoalDetail() { document.getElementById('goal-detail').style.display = 'none'; }

/* Auto-poll running goals */
setInterval(async () => {
  if (!_JWT_TOKEN || currentPage !== 'goals') return;
  const running = _allGoals.filter(g => g.status === 'running' || g.status === 'pending');
  if (running.length) loadGoals();
}, 5000);

/* ══ Agents ═════════════════════════════════════════════════════════ */
let _selectedAgent = null;

async function loadAgents() {
  try {
    const r = await apiFetch('/api/agents');
    renderAgentsGrid(r.data || []);
  } catch (e) { toast('Failed to load agents: ' + e.message, 'error'); }
}

function renderAgentsGrid(agents) {
  const grid = document.getElementById('agents-grid');
  const empty = document.getElementById('agents-empty');
  if (!agents.length) {
    grid.innerHTML = ''; empty.style.display = 'flex'; return;
  }
  empty.style.display = 'none';
  grid.innerHTML = agents.map(a => `
    <div class="card" style="cursor:default">
      <div style="display:flex;align-items:flex-start;gap:10px;margin-bottom:12px">
        <div style="width:38px;height:38px;border-radius:10px;background:rgba(99,102,241,0.12);border:1px solid rgba(99,102,241,0.25);display:flex;align-items:center;justify-content:center;font-size:18px;flex-shrink:0">🤖</div>
        <div style="flex:1;min-width:0">
          <div style="font-weight:700;font-size:14px;color:var(--text)">${escHtml(a.name)}</div>
          <div style="font-size:12px;color:var(--text3);margin-top:2px">${escHtml(a.role||'Agent')}</div>
        </div>
      </div>
      ${a.tools?.length ? `<div style="font-size:11px;color:var(--text3);margin-bottom:10px">Tools: ${a.tools.map(t=>`<span class="badge badge-purple" style="margin:1px">${escHtml(t)}</span>`).join('')}</div>` : ''}
      <div style="display:flex;gap:6px;margin-top:auto">
        <button class="btn btn-primary btn-sm" onclick="openAgentRunner('${escHtml(a.name)}')">▶ Run Task</button>
        <button class="btn btn-danger btn-sm" onclick="deleteAgent('${escHtml(a.name)}')">✕</button>
      </div>
    </div>`).join('');
}

function openAgentPanel() { document.getElementById('agent-panel').style.display = 'block'; }
function closeAgentPanel() { document.getElementById('agent-panel').style.display = 'none'; }

async function createAgent() {
  const name = document.getElementById('ag-name').value.trim();
  if (!name) { toast('Agent name is required', 'error'); return; }
  const tools = document.getElementById('ag-tools').value.split(',').map(s=>s.trim()).filter(Boolean);
  const perm  = parseInt(document.getElementById('ag-perm').value) || 1;
  const role  = document.getElementById('ag-role').value.trim();
  try {
    await apiFetch('/api/agents', {
      method: 'POST',
      body: JSON.stringify({ name, role: role||null, tools, permission_level: perm })
    });
    toast(`Agent "${name}" created!`, 'success');
    closeAgentPanel(); loadAgents();
  } catch (e) { toast(e.message, 'error'); }
}

async function designAgent() {
  const name = document.getElementById('agd-name').value.trim();
  const role = document.getElementById('agd-role').value.trim();
  const goal = document.getElementById('agd-goal').value.trim();
  if (!name || !role || !goal) { toast('All fields required', 'error'); return; }
  const perm = parseInt(document.getElementById('agd-perm').value) || 2;
  try {
    await apiFetch('/api/agents/design', {
      method: 'POST',
      body: JSON.stringify({ name, role_description: role, goal, permission_level: perm })
    });
    toast(`Agent "${name}" designed!`, 'success');
    closeAgentPanel(); loadAgents();
  } catch (e) { toast(e.message, 'error'); }
}

async function deleteAgent(name) {
  if (!confirm(`Delete agent "${name}"?`)) return;
  try {
    await apiFetch('/api/agents/' + encodeURIComponent(name), { method: 'DELETE' });
    toast('Deleted', 'success'); loadAgents();
  } catch (e) { toast(e.message, 'error'); }
}

function openAgentRunner(name) {
  _selectedAgent = name;
  document.getElementById('runner-agent-name').textContent = name;
  document.getElementById('runner-result').innerHTML = '';
  document.getElementById('runner-task').value = '';
  document.getElementById('agent-runner').style.display = 'block';
  document.getElementById('agent-runner').scrollIntoView({ behavior: 'smooth', block: 'start' });
}
function closeAgentRunner() { document.getElementById('agent-runner').style.display = 'none'; _selectedAgent = null; }

async function runAgentTask() {
  const task = document.getElementById('runner-task').value.trim();
  if (!task || !_selectedAgent) { toast('Enter a task', 'error'); return; }
  const btn = document.getElementById('runner-run-btn');
  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Running…';
  try {
    const r = await apiFetch(`/api/agents/${encodeURIComponent(_selectedAgent)}/run`, {
      method: 'POST', body: JSON.stringify({ task })
    });
    const result = r.data?.result || JSON.stringify(r.data, null, 2);
    document.getElementById('runner-result').innerHTML = `<div class="alert alert-success"><b>Result:</b><pre style="margin-top:8px;white-space:pre-wrap">${escHtml(String(result))}</pre></div>`;
  } catch (e) {
    document.getElementById('runner-result').innerHTML = `<div class="alert alert-error">Error: ${escHtml(e.message)}</div>`;
  }
  btn.disabled = false; btn.innerHTML = '▶ Run';
}

/* ══ Chat ════════════════════════════════════════════════════════════ */
let _chatHistory = [];

function clearChat() {
  _chatHistory = [];
  document.getElementById('chat-messages').innerHTML = `
    <div class="msg"><div class="msg-avatar">✨</div><div class="msg-bubble">Hi! I'm AetheerAI. Ask me anything or describe a task and I'll help you out.</div></div>`;
}

function appendChatMsg(role, text) {
  const el = document.createElement('div');
  el.className = 'msg ' + (role === 'user' ? 'user' : '');
  el.innerHTML = `
    <div class="msg-avatar">${role === 'user' ? '👤' : '✨'}</div>
    <div class="msg-bubble">${escHtml(text)}</div>`;
  const container = document.getElementById('chat-messages');
  container.appendChild(el);
  container.scrollTop = container.scrollHeight;
}

async function sendChat() {
  const input = document.getElementById('chat-input');
  const msg   = input.value.trim();
  if (!msg) return;
  input.value = '';
  appendChatMsg('user', msg);
  _chatHistory.push({ role: 'user', content: msg });

  const btn = document.getElementById('chat-send-btn');
  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>';

  // Typing indicator
  const typing = document.createElement('div');
  typing.className = 'msg'; typing.id = 'chat-typing';
  typing.innerHTML = `<div class="msg-avatar">✨</div><div class="msg-bubble" style="color:var(--text3)">Thinking…</div>`;
  document.getElementById('chat-messages').appendChild(typing);
  document.getElementById('chat-messages').scrollTop = 9999;

  try {
    const r = await apiFetch('/api/chat', {
      method: 'POST',
      body: JSON.stringify({ message: msg, history: _chatHistory.slice(-20) })
    });
    typing.remove();
    const reply = r.data?.reply || '(no reply)';
    appendChatMsg('assistant', reply);
    _chatHistory.push({ role: 'assistant', content: reply });
  } catch (e) {
    typing.remove();
    appendChatMsg('assistant', '⚠ Error: ' + e.message);
  }
  btn.disabled = false; btn.textContent = 'Send';
}

/* ══ Collaborate ═════════════════════════════════════════════════════ */
async function loadCollaborations() {
  try {
    const r = await apiFetch('/api/collaborations?limit=50');
    renderCollabTable(r.data || []);
  } catch (e) { toast('Failed: ' + e.message, 'error'); }
}

function renderCollabTable(sessions) {
  if (!sessions.length) {
    document.getElementById('collab-tbody').innerHTML = `<tr><td colspan="6"><div class="empty-state" style="padding:30px"><div class="empty-icon">👥</div><h3>No sessions</h3></div></td></tr>`;
    return;
  }
  document.getElementById('collab-tbody').innerHTML = sessions.map(s => `
    <tr>
      <td style="font-size:12px;color:var(--text3)">${escHtml((s.session_id||s.id||'—').slice(0,12))}…</td>
      <td style="max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml((s.goal||'—').slice(0,80))}</td>
      <td>${(s.agents||[]).map(a=>`<span class="badge badge-purple">${escHtml(a)}</span>`).join(' ')}</td>
      <td>${s.rounds||'—'}</td>
      <td><span class="badge badge-blue">${escHtml(s.mode||'standard')}</span></td>
      <td style="font-size:11px;color:var(--text3)">${timeAgo(s.created_at)}</td>
    </tr>`).join('');
}

async function runCollaboration() {
  const goal = document.getElementById('cf-goal').value.trim();
  if (!goal) { toast('Goal is required', 'error'); return; }
  const team    = document.getElementById('cf-team').value.trim();
  const agentNs = document.getElementById('cf-agents').value.split(',').map(s=>s.trim()).filter(Boolean);
  const rounds  = parseInt(document.getElementById('cf-rounds').value) || 2;
  const btn = document.getElementById('cf-submit-btn');
  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Running…';
  try {
    await apiFetch('/api/collaborations', {
      method: 'POST',
      body: JSON.stringify({ goal, team_name: team||null, agent_names: agentNs, rounds })
    });
    toast('Collaboration complete!', 'success');
    document.getElementById('collab-form-wrap').style.display = 'none';
    loadCollaborations();
  } catch (e) { toast(e.message, 'error'); }
  btn.disabled = false; btn.innerHTML = '▶ Start Collaboration';
}

/* ══ Memory ══════════════════════════════════════════════════════════ */
async function loadMemory() {
  const ns = document.getElementById('memory-ns').value.trim() || 'global';
  try {
    const r = await apiFetch(`/api/memory?namespace=${encodeURIComponent(ns)}`);
    renderMemoryTable(r.data || {});
  } catch (e) { toast('Memory load failed: ' + e.message, 'error'); }
}

function renderMemoryTable(data) {
  const keys = Object.keys(data);
  if (!keys.length) {
    document.getElementById('memory-tbody').innerHTML = `<tr><td colspan="3"><div class="empty-state" style="padding:30px"><div class="empty-icon">🧠</div><h3>Empty namespace</h3></div></td></tr>`;
    return;
  }
  document.getElementById('memory-tbody').innerHTML = keys.map(k => {
    const preview = JSON.stringify(data[k]).slice(0, 120);
    return `<tr>
      <td style="font-weight:600;font-family:monospace;font-size:12px;color:var(--accent2)">${escHtml(k)}</td>
      <td style="font-size:12px;color:var(--text2);max-width:380px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml(preview)}</td>
      <td><button class="btn btn-sm btn-danger" onclick="deleteMemoryKey('${escHtml(k)}')">✕ Delete</button></td>
    </tr>`;
  }).join('');
}

async function deleteMemoryKey(key) {
  const ns = document.getElementById('memory-ns').value.trim() || 'global';
  if (!confirm(`Delete key "${key}" from namespace "${ns}"?`)) return;
  try {
    await apiFetch(`/api/memory/${encodeURIComponent(key)}?namespace=${encodeURIComponent(ns)}`, { method: 'DELETE' });
    toast('Deleted', 'success'); loadMemory();
  } catch (e) { toast(e.message, 'error'); }
}

/* ══ Logs ════════════════════════════════════════════════════════════ */
let _allLogs = [];

async function loadLogs() {
  try {
    const r = await apiFetch('/api/logs?limit=300');
    _allLogs = r.data || [];
    renderLogs(_allLogs);
  } catch (e) { toast('Logs load failed: ' + e.message, 'error'); }
}

function renderLogs(logs) {
  const box = document.getElementById('log-box');
  if (!logs.length) { box.innerHTML = '<span style="color:var(--text3)">No log entries found.</span>'; return; }
  box.innerHTML = logs.map(entry => {
    const ts  = entry.timestamp || entry.ts || '';
    const lvl = entry.level || entry.lvl || 'INFO';
    const msg = entry.message || entry.msg || entry.raw || JSON.stringify(entry);
    return `<div class="log-entry"><span class="log-ts">${escHtml(ts)}</span> <span class="log-lvl-${lvl}">[${lvl}]</span> ${escHtml(msg)}</div>`;
  }).join('');
  box.scrollTop = box.scrollHeight;
}

function filterLogs() {
  const q = document.getElementById('log-filter').value.toLowerCase();
  if (!q) { renderLogs(_allLogs); return; }
  renderLogs(_allLogs.filter(e => JSON.stringify(e).toLowerCase().includes(q)));
}

/* ══ Database ═══════════════════════════════════════════════════════ */
async function loadDatabase() {
  try {
    const [statsR, goalsR, tasksR, logsR] = await Promise.all([
      apiFetch('/api/db/stats'),
      apiFetch('/api/db/goals?limit=25'),
      apiFetch('/api/db/tasks?limit=25'),
      apiFetch('/api/db/logs?limit=25'),
    ]);

    const stats = statsR.data || {};
    document.getElementById('db-stat-goals').textContent = stats.goal_runs?.total ?? 0;
    document.getElementById('db-stat-tasks').textContent = stats.tasks?.total ?? 0;
    document.getElementById('db-stat-logs').textContent  = stats.system_logs?.total ?? 0;
    document.getElementById('db-stat-failed').textContent = stats.goal_runs?.failed ?? 0;

    renderDbGoals(goalsR.data?.items || []);
    renderDbTasks(tasksR.data?.items || []);
    renderDbSystemLogs(logsR.data?.items || []);
  } catch (e) {
    toast('Database load failed: ' + e.message, 'error');
  }
}

function renderDbGoals(items) {
  const tbody = document.getElementById('db-goals-tbody');
  if (!items.length) {
    tbody.innerHTML = '<tr><td colspan="7" style="color:var(--text3)">No persisted goal runs yet.</td></tr>';
    return;
  }

  tbody.innerHTML = items.map(g => {
    const pct = g.progress?.percent ?? 0;
    return `<tr>
      <td style="font-family:monospace;font-size:11px;color:var(--text3)">${escHtml((g.id||'').slice(0,10))}…</td>
      <td>${escHtml(g.name || '—')}</td>
      <td><span class="badge ${statusBadgeClass(g.status)}">${escHtml(g.status || 'unknown')}</span></td>
      <td>${pct}%</td>
      <td>${g.completed_tasks || 0}/${g.total_tasks || 0}</td>
      <td>${fmtCost(g.spent_usd)}</td>
      <td style="font-size:12px;color:var(--text2)">${escHtml(g.started_at || '—')}</td>
    </tr>`;
  }).join('');
}

function renderDbTasks(items) {
  const tbody = document.getElementById('db-tasks-tbody');
  if (!items.length) {
    tbody.innerHTML = '<tr><td colspan="5" style="color:var(--text3)">No tasks persisted yet.</td></tr>';
    return;
  }
  tbody.innerHTML = items.map(t => `
    <tr>
      <td style="font-family:monospace;font-size:11px;color:var(--text3)">${escHtml((t.goal_id||'').slice(0,8))}…</td>
      <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml(t.title || 'Task')}</td>
      <td>${escHtml(t.agent_type || '—')}</td>
      <td><span class="badge ${statusBadgeClass(t.status)}">${escHtml(t.status || 'pending')}</span></td>
      <td>${t.attempts ?? 0}</td>
    </tr>`).join('');
}

function renderDbSystemLogs(items) {
  const tbody = document.getElementById('db-logs-tbody');
  if (!items.length) {
    tbody.innerHTML = '<tr><td colspan="4" style="color:var(--text3)">No system logs captured yet.</td></tr>';
    return;
  }
  tbody.innerHTML = items.map(l => `
    <tr>
      <td><span class="badge ${statusBadgeClass((l.level||'').toLowerCase() === 'error' ? 'failed' : (l.level||'').toLowerCase() === 'warning' ? 'pending' : 'running')}">${escHtml(l.level || 'INFO')}</span></td>
      <td style="font-family:monospace;font-size:11px;color:var(--text3)">${escHtml(l.logger_name || '—')}</td>
      <td style="max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml(l.message || '')}</td>
      <td style="font-size:12px;color:var(--text2)">${escHtml(l.created_at || '—')}</td>
    </tr>`).join('');
}

/* ══ Settings ════════════════════════════════════════════════════════ */
function setAiProviderOptions(providers) {
  const normalized = (Array.isArray(providers) ? providers : _DEFAULT_AI_PROVIDERS)
    .map(p => String(p || '').trim().toLowerCase())
    .filter(Boolean);
  const unique = Array.from(new Set(normalized));
  if (!unique.length) return;

  ['settings-ai-provider', 'topbar-provider-select'].forEach(id => {
    const select = document.getElementById(id);
    if (!select) return;

    const current = (select.value || '').trim().toLowerCase();
    select.innerHTML = unique
      .map(p => `<option value="${escHtml(p)}">${escHtml(p)}</option>`)
      .join('');

    if (current && unique.includes(current)) {
      select.value = current;
    }
  });

  updateTopbarProviderApplyState();
}

async function quickSwitchProvider(provider) {
  const normalized = _normalizeProviderName(provider);
  if (!normalized || _providerSwitchBusy) return;
  if (!_CURRENT_USER || !_JWT_TOKEN) {
    toast('Sign in first to switch providers.', 'error');
    return;
  }

  const topbarSelect = document.getElementById('topbar-provider-select');
  const settingsProvider = document.getElementById('settings-ai-provider');
  const settingsModel = document.getElementById('settings-ai-model');

  if (settingsProvider) settingsProvider.value = normalized;
  if (settingsModel && !settingsModel.value.trim()) {
    settingsModel.value = _PROVIDER_DEFAULT_MODEL[normalized] || '';
  }

  _providerSwitchBusy = true;
  if (topbarSelect) topbarSelect.disabled = true;
  updateTopbarProviderApplyState();
  try {
    await saveAiRuntime();
    if (topbarSelect) topbarSelect.value = normalized;
  } finally {
    _providerSwitchBusy = false;
    if (topbarSelect) topbarSelect.disabled = !_CURRENT_USER;
    updateTopbarProviderApplyState();
  }
}

async function quickApplyProvider() {
  const topbarSelect = document.getElementById('topbar-provider-select');
  if (!topbarSelect) return;
  await quickSwitchProvider(topbarSelect.value);
}

function _setSupabaseSettingsStatus(message, tone = 'neutral') {
  const statusEl = document.getElementById('settings-sb-status');
  if (!statusEl) return;
  statusEl.textContent = message;
  if (tone === 'success') {
    statusEl.style.color = '#10b981';
  } else if (tone === 'error') {
    statusEl.style.color = '#ef4444';
  } else {
    statusEl.style.color = 'var(--text3)';
  }
}

async function loadSupabaseSettings() {
  const urlEl = document.getElementById('settings-sb-url');
  const anonEl = document.getElementById('settings-sb-anon-key');
  const serviceEl = document.getElementById('settings-sb-service-key');
  const schemaEl = document.getElementById('settings-sb-schema');
  if (!urlEl || !anonEl || !serviceEl || !schemaEl) return;

  urlEl.value = '';
  anonEl.value = '';
  serviceEl.value = '';
  schemaEl.value = 'public';
  _setSupabaseSettingsStatus('No Supabase configuration loaded.');

  if (!_CURRENT_USER) return;

  try {
    const r = await apiFetch('/api/auth/setup/supabase');
    const d = r.data || {};
    urlEl.value = String(d.customer_supabase_url || '').trim();
    schemaEl.value = String(d.customer_supabase_schema || 'public').trim() || 'public';

    const anonMasked = String(d.customer_supabase_anon_key || '').trim();
    const serviceMasked = String(d.customer_supabase_service_role_key || '').trim();
    if (d.configured) {
      _setSupabaseSettingsStatus(
        `Configured. Anon key: ${anonMasked || '***'} | Service role: ${serviceMasked || 'not set'}`,
        'success'
      );
    } else {
      _setSupabaseSettingsStatus('Not configured yet. Add Supabase URL and anon key, then save.');
    }
  } catch (_) {
    _setSupabaseSettingsStatus('Unable to load Supabase configuration.', 'error');
  }
}

async function loadSettings() {
  document.getElementById('settings-api-url').value = API_BASE;
  const base = API_BASE;
  document.getElementById('link-swagger').href = base + '/docs';
  document.getElementById('link-redoc').href   = base + '/redoc';
  updateApiConnectionState();
  setAiProviderOptions(_DEFAULT_AI_PROVIDERS);
  document.getElementById('settings-ai-api-key').value = '';
  document.getElementById('settings-ai-base-url').value = '';
  document.getElementById('settings-ai-key-status').textContent = 'No API key saved for this user.';
  
  // Show user info if authenticated
  const userInfoEl = document.getElementById('settings-user-info');
  const userDetailsEl = document.getElementById('settings-user-details');
  if (_CURRENT_USER) {
    userInfoEl.style.display = 'block';
    userDetailsEl.innerHTML = [
      ['Username', _CURRENT_USER.username],
      ['Email', _CURRENT_USER.email],
      ['Full Name', _CURRENT_USER.full_name],
      ['Role', _CURRENT_USER.role],
      ['Created', new Date(_CURRENT_USER.created_at).toLocaleDateString()],
    ].map(([k,v]) => `<div><span style="color:var(--text3)">${k}:</span> <b style="color:var(--text)">${escHtml(String(v||'—'))}</b></div>`).join('');
  } else {
    userInfoEl.style.display = 'none';
  }
  
  try {
    const r = await apiFetch('/api/health');
    const d = r.data;
    setAiProviderOptions(d.supported_providers);
    if (d.provider) {
      const normalizedProvider = _normalizeProviderName(d.provider);
      document.getElementById('settings-ai-provider').value = normalizedProvider;
      setActiveAiProvider(normalizedProvider);
      const quickProviderSelect = document.getElementById('topbar-provider-select');
      if (quickProviderSelect) {
        const activeProvider = normalizedProvider;
        const hasProvider = Array.from(quickProviderSelect.options).some(opt => opt.value === activeProvider);
        if (hasProvider) quickProviderSelect.value = activeProvider;
      }
      updateTopbarProviderApplyState();
    }
    if (d.model) {
      document.getElementById('settings-ai-model').value = String(d.model).trim();
    }

    const supportedProviders = Array.isArray(d.supported_providers) && d.supported_providers.length
      ? d.supported_providers.join(', ')
      : _DEFAULT_AI_PROVIDERS.join(', ');
    document.getElementById('settings-sysinfo').innerHTML = [
      ['API Version', 'v2.0.0'],
      ['Provider', d.provider],
      ['Model', d.model],
      ['Supported Providers', supportedProviders],
      ['Offline Provider', d.offline_provider],
      ['Offline Model', d.offline_model],
    ].map(([k,v]) => `<div><span style="color:var(--text3)">${k}:</span> <b style="color:var(--text)">${escHtml(String(v||'—'))}</b></div>`).join('');
  } catch (_) {}

  try {
    const r = await apiFetch('/api/auth/settings/ai-api');
    const d = r.data || {};
    const savedProvider = String(d.provider || '').trim().toLowerCase();
    if (savedProvider) {
      const select = document.getElementById('settings-ai-provider');
      const hasOption = Array.from(select.options).some(opt => opt.value === savedProvider);
      if (!hasOption) {
        const option = document.createElement('option');
        option.value = savedProvider;
        option.textContent = savedProvider;
        select.appendChild(option);
      }
      select.value = savedProvider;
    }
    if (d.model != null) {
      document.getElementById('settings-ai-model').value = String(d.model || '').trim();
    }
    if (d.base_url) {
      document.getElementById('settings-ai-base-url').value = String(d.base_url).trim();
    }
    if (d.api_key) {
      document.getElementById('settings-ai-key-status').textContent = 'Saved key: ' + String(d.api_key);
    }
  } catch (_) {}

  await loadSupabaseSettings();

  // Restore from localStorage if available (persisted user preference)
  restoreAiConfigFromLocalStorage();
}

/* ══ AI Configuration Persistence ════════════════════════════════ */
function saveAiConfigToLocalStorage() {
  const provider = document.getElementById('settings-ai-provider').value.trim().toLowerCase();
  const model = document.getElementById('settings-ai-model').value.trim();
  const baseUrl = document.getElementById('settings-ai-base-url').value.trim();

  const config = {
    provider: provider || null,
    model: model || null,
    base_url: baseUrl || null,
  };

  localStorage.setItem('aetheer_ai_config', JSON.stringify(config));
}

function restoreAiConfigFromLocalStorage() {
  try {
    const saved = localStorage.getItem('aetheer_ai_config');
    if (!saved) return;

    const config = JSON.parse(saved);

    if (config.provider) {
      const select = document.getElementById('settings-ai-provider');
      const hasOption = Array.from(select.options).some(opt => opt.value === config.provider);
      if (hasOption) {
        select.value = config.provider;
      }
    }

    if (config.model) {
      document.getElementById('settings-ai-model').value = config.model;
    }

    if (config.base_url) {
      document.getElementById('settings-ai-base-url').value = config.base_url;
    }
  } catch (_) {
    // Silently ignore localStorage errors
  }
}

function saveApiUrl() {
  const raw = document.getElementById('settings-api-url').value.trim();
  if (!raw) {
    resetApiUrl();
    return;
  }

  let parsed = null;
  try {
    parsed = new URL(raw, location.origin);
  } catch (_) {
    toast('Enter a valid API URL (for example: https://your-app.vercel.app).', 'error');
    return;
  }

  const currentBase = _defaultApiBase();
  const currentIsLocal = _isLocalHost(location.hostname);
  const targetIsLocal = _isLocalHost(parsed.hostname);
  if (!currentIsLocal && targetIsLocal) {
    API_BASE = currentBase;
    localStorage.removeItem('aetheer_api_url');
    toast('Localhost API URLs are ignored on deployed environments. Using this site URL.', 'error');
  } else {
    const nextBase = _formatApiBase(parsed);
    if (_normalizeApiBase(nextBase) === _normalizeApiBase(currentBase)) {
      API_BASE = currentBase;
      localStorage.removeItem('aetheer_api_url');
      toast('Using the current app backend. No custom backend URL is needed.', 'success');
    } else {
      API_BASE = nextBase;
      localStorage.setItem('aetheer_api_url', API_BASE);
      toast('Custom backend URL saved.', 'success');
    }
  }

  document.getElementById('settings-api-url').value = API_BASE;
  updateApiConnectionState();
  loadDashboard();
  loadSettings();
}

function resetApiUrl() {
  API_BASE = _defaultApiBase();
  localStorage.removeItem('aetheer_api_url');
  document.getElementById('settings-api-url').value = API_BASE;
  updateApiConnectionState();
  toast('Using the current app backend.', 'success');
  loadDashboard();
  loadSettings();
}

async function saveSupabaseSettings() {
  const urlEl = document.getElementById('settings-sb-url');
  const anonEl = document.getElementById('settings-sb-anon-key');
  const serviceEl = document.getElementById('settings-sb-service-key');
  const schemaEl = document.getElementById('settings-sb-schema');
  if (!urlEl || !anonEl || !serviceEl || !schemaEl) {
    toast('Supabase settings form is unavailable.', 'error');
    return;
  }

  const rawUrl = urlEl.value.trim();
  const anonKey = anonEl.value.trim();
  const serviceRoleKey = serviceEl.value.trim();
  const schema = schemaEl.value.trim();

  if (!rawUrl) {
    toast('Supabase Project URL is required.', 'error');
    return;
  }

  let normalizedUrl = '';
  try {
    normalizedUrl = new URL(rawUrl).toString().replace(/\/+$/, '');
  } catch (_) {
    toast('Enter a valid Supabase Project URL.', 'error');
    return;
  }

  const payload = {
    supabase_url: normalizedUrl,
  };
  if (schema) {
    payload.schema = schema;
  }
  if (anonKey) {
    payload.supabase_anon_key = anonKey;
  }
  if (serviceRoleKey) {
    payload.supabase_service_role_key = serviceRoleKey;
  }

  try {
    await apiFetch('/api/auth/setup/supabase', {
      method: 'PUT',
      body: JSON.stringify(payload),
    });

    anonEl.value = '';
    serviceEl.value = '';
    toast('Supabase details saved.', 'success');
    await loadSupabaseSettings();
  } catch (e) {
    toast('Supabase update failed: ' + e.message, 'error');
  }
}

async function saveAiRuntime() {
  const provider = document.getElementById('settings-ai-provider').value.trim().toLowerCase();
  const model = document.getElementById('settings-ai-model').value.trim();
  const apiKey = document.getElementById('settings-ai-api-key').value.trim();
  const baseUrlRaw = document.getElementById('settings-ai-base-url').value.trim();

  if (!provider) {
    toast('Select a provider first.', 'error');
    return;
  }

  let baseUrl = null;
  if (baseUrlRaw) {
    try {
      baseUrl = new URL(baseUrlRaw).toString().replace(/\/+$/, '');
    } catch (_) {
      toast('Enter a valid AI API endpoint URL.', 'error');
      return;
    }
  }

  const configPayload = {
    provider,
    model: model || null,
  };
  if (apiKey) {
    configPayload.api_key = apiKey;
  }
  if (baseUrl) {
    configPayload.base_url = baseUrl;
  }

  // Persist provider/model/base URL locally so the user preference survives even if server settings storage is unavailable.
  saveAiConfigToLocalStorage();

  let settingsStoredOnServer = false;
  let settingsStoreError = '';

  try {
    await apiFetch('/api/auth/settings/ai-api', {
      method: 'PUT',
      body: JSON.stringify(configPayload),
    });
    settingsStoredOnServer = true;
  } catch (e) {
    settingsStoreError = e && e.message ? e.message : 'unknown error';
  }

  try {
    if (apiKey && settingsStoredOnServer) {
      const masked = apiKey.length <= 9 ? '***' : `${apiKey.slice(0, 4)}***${apiKey.slice(-2)}`;
      document.getElementById('settings-ai-key-status').textContent = 'Saved key: ' + masked;
    } else if (apiKey && !settingsStoredOnServer) {
      document.getElementById('settings-ai-key-status').textContent = 'API key not stored on server (settings table unavailable).';
    } else {
      document.getElementById('settings-ai-key-status').textContent = 'API key unchanged.';
    }
    document.getElementById('settings-ai-api-key').value = '';

    try {
      const r = await apiFetch('/api/system/ai/runtime', {
        method: 'POST',
        body: JSON.stringify({ provider, model: model || null }),
      });
      const d = r.data || {};
      const activeProvider = d.provider || provider;
      const activeModel = d.model || model || 'default';
      setActiveAiProvider(activeProvider);
      const quickProviderSelect = document.getElementById('topbar-provider-select');
      if (quickProviderSelect) {
        const normalizedActiveProvider = _normalizeProviderName(activeProvider);
        const hasOption = Array.from(quickProviderSelect.options).some(opt => opt.value === normalizedActiveProvider);
        if (hasOption) quickProviderSelect.value = normalizedActiveProvider;
      }
      updateTopbarProviderApplyState();
      if (settingsStoredOnServer) {
        toast(`AI configuration saved. Runtime active: ${activeProvider}/${activeModel}`, 'success');
      } else {
        toast(`Runtime active: ${activeProvider}/${activeModel}. Settings were saved locally in this browser only.`, 'info');
      }
      loadDashboard();
    } catch (runtimeErr) {
      if (settingsStoredOnServer) {
        toast('AI configuration saved, but runtime switch failed: ' + runtimeErr.message, 'info');
      } else {
        toast('Could not activate runtime and server settings are unavailable: ' + runtimeErr.message, 'error');
      }
    }

    if (!settingsStoredOnServer && settingsStoreError) {
      console.warn('AI settings store unavailable:', settingsStoreError);
    }

    loadSettings();
  } catch (e) {
    toast('AI configuration update failed: ' + e.message, 'error');
  }
}

function openDocs(type) {
  const url = API_BASE + (type === 'swagger' ? '/docs' : '/redoc');
  window.open(url, '_blank', 'noopener');
}

/* ══ Playground (Input → Output) ════════════════════════════════════ */
let _pgMode = 'chat';
let _pgHistory = [];

  // Wire mode buttons
  document.querySelectorAll('.pg-mode').forEach(btn => {
    btn.addEventListener('click', () => {
      _pgMode = btn.dataset.mode;
      document.querySelectorAll('.pg-mode').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      ['chat', 'goal', 'agent'].forEach(m => {
        const el = document.getElementById('pg-opts-' + m);
        if (el) el.style.display = (m === _pgMode) ? '' : 'none';
      });
      const ph = {
        chat:  'Type your message or question here…',
        goal:  'Describe the goal for AetheerAI to accomplish… e.g. Build a REST API for a todo app',
        agent: 'Describe the task for the agent to execute…',
      };
      document.getElementById('pg-input').placeholder = ph[_pgMode] || '…';
    });
  });

  async function pgLoadAgents() {
    const select = document.getElementById('pg-agent');
    if (!select) return;
    try {
      const r = await apiFetch('/api/agents');
      const agents = r.data || [];
      if (!agents.length) {
        select.innerHTML = '<option value="">No agents available</option>';
        return;
      }
      select.innerHTML = agents.map(a => `<option value="${escHtml(a.name)}">${escHtml(a.name)}</option>`).join('');
    } catch (_) {
      select.innerHTML = '<option value="">Failed to load</option>';
    }
  }

  async function pgRun() {
    const input = document.getElementById('pg-input').value.trim();
    if (!input) { toast('Enter some input first.', 'error'); return; }

    const runBtn = document.getElementById('pg-run-btn');
    const outputEl = document.getElementById('pg-output');
    const elapsedEl = document.getElementById('pg-elapsed');

    runBtn.disabled = true;
    runBtn.innerHTML = '<span class="spinner"></span> Running…';
    outputEl.innerHTML = '<div class="pg-stream-text">Working…</div>';

    const t0 = performance.now();
    let outputText = '';

    try {
      if (_pgMode === 'chat') {
        const temperature = parseFloat(document.getElementById('pg-temp').value || '0.7');
        const stream = document.getElementById('pg-stream').checked;

        if (stream) {
          const resp = await fetch(API_BASE + '/api/chat/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': _JWT_TOKEN ? ('Bearer ' + _JWT_TOKEN) : '' },
            body: JSON.stringify({ message: input, temperature, stream: true }),
          });

          if (!resp.ok || !resp.body) {
            throw new Error('Streaming failed');
          }

          const reader = resp.body.getReader();
          const decoder = new TextDecoder();
          outputText = '';
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            const chunk = decoder.decode(value, { stream: true });
            outputText += chunk;
            outputEl.innerHTML = `<div class="pg-stream-text">${escHtml(outputText)}</div>`;
          }
        } else {
          const r = await apiFetch('/api/chat', {
            method: 'POST',
            body: JSON.stringify({ message: input, temperature }),
          });
          outputText = String(r.data?.response ?? r.response ?? '');
          outputEl.innerHTML = `<div class="pg-stream-text">${escHtml(outputText)}</div>`;
        }
      }
      else if (_pgMode === 'goal') {
        const name = document.getElementById('pg-goal-name').value.trim() || 'Playground Goal';
        const r = await apiFetch('/api/goals', {
          method: 'POST',
          body: JSON.stringify({ name, goal: input, background: true, parallel: true }),
        });
        const g = r.data || {};
        outputText = renderGoalSummary(g);
        outputEl.innerHTML = outputText;
        loadDashboard();
      }
      else if (_pgMode === 'agent') {
        const agent = document.getElementById('pg-agent').value;
        if (!agent) throw new Error('Select an agent first.');
        const r = await apiFetch('/api/agents/' + encodeURIComponent(agent) + '/run', {
          method: 'POST',
          body: JSON.stringify({ task: input }),
        });
        outputText = typeof r.data === 'string' ? r.data : JSON.stringify(r.data, null, 2);
        outputEl.innerHTML = `<pre>${escHtml(outputText)}</pre>`;
      }

      const took = ((performance.now() - t0) / 1000).toFixed(2);
      elapsedEl.textContent = `Completed in ${took}s`;

      _pgHistory.unshift({
        mode: _pgMode,
        input,
        output: outputText,
        took,
        ts: Date.now(),
      });
      _pgHistory = _pgHistory.slice(0, 20);
      pgRenderHistory();
    } catch (e) {
      outputEl.innerHTML = `<div class="alert alert-error">${escHtml(e.message || 'Run failed')}</div>`;
      toast(e.message || 'Run failed', 'error');
    }

    runBtn.disabled = false;
    runBtn.innerHTML = '▶ Run';
  }

  function renderGoalSummary(g) {
    return `<div class="card" style="padding:14px">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px">
          <span class="badge ${statusBadgeClass(g.status || 'pending')}">${escHtml(g.status || 'pending')}</span>
          <b style="font-size:14px;color:var(--text)">${escHtml(g.name || 'Goal')}</b>
          <span style="font-size:11px;color:var(--text3);margin-left:auto">ID: ${escHtml((g.id || '').slice(0, 12))}</span>
        </div>
        <div style="font-size:12px;color:var(--text2);line-height:1.7;margin-bottom:10px">${escHtml(g.goal || '')}</div>
        ${g.plan_summary ? `<div style="background:var(--surface2);border:1px solid var(--border);border-radius:8px;padding:10px;margin-bottom:10px">
          <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;color:var(--text3);margin-bottom:8px">Summary</div>
          <div style="font-size:13px;color:var(--text2);line-height:1.75">${escHtml(g.plan_summary)}</div>
        </div>` : ''}

        <div style="display:flex;gap:8px">
          <button class="btn btn-sm btn-secondary" onclick="nav('goals')">View in Goals →</button>
          ${g.id ? `<button class="btn btn-sm btn-secondary" onclick="openGoalDetail('${escHtml(g.id)}');nav('goals')">Details</button>` : ''}
        </div>
      </div>`;
  }

  function pgRenderHistory() {
    const wrap = document.getElementById('pg-history-wrap');
    const container = document.getElementById('pg-history');
    if (!_pgHistory.length) { wrap.style.display = 'none'; return; }
    wrap.style.display = 'block';
    const modeIcon = { chat: '💬', goal: '🎯', agent: '🤖' };
    container.innerHTML = _pgHistory.slice(0, 8).map((item, i) => `
      <div class="pg-history-item" onclick="pgRerun(${i})">
        <div style="font-size:16px;flex-shrink:0">${modeIcon[item.mode] || '⚡'}</div>
        <div style="flex:1;min-width:0">
          <div class="pg-history-input">${escHtml(item.input.slice(0, 100))}</div>
          <div class="pg-history-output">${escHtml(String(item.output || '').slice(0, 130))}</div>
        </div>
        <div style="font-size:11px;color:var(--text3);flex-shrink:0">${item.took}s</div>
      </div>`).join('');
  }

  function pgRerun(i) {
    const item = _pgHistory[i];
    if (!item) return;
    document.getElementById('pg-input').value = item.input;
    const modeBtn = document.querySelector(`.pg-mode[data-mode="${item.mode}"]`);
    if (modeBtn) modeBtn.click();
    document.getElementById('pg-input').focus();
  }

  function pgClear() {
    document.getElementById('pg-input').value = '';
    document.getElementById('pg-elapsed').textContent = '';
    document.getElementById('pg-output').innerHTML = `
      <div class="empty-state" style="padding:40px" id="pg-output-empty">
        <div class="empty-icon">⚡</div>
        <h3>Output appears here</h3>
        <p>Type something and click Run</p>
      </div>`;
  }

  /* ══ Auth Management ════════════════════════════════════════════════ */
  async function checkAuth() {
    // Prevent recursive checkAuth calls
    if (_authCheckInProgress) return false;
    _authCheckInProgress = true;
  
    try {
      if (!_JWT_TOKEN) {
        showLandingPage();
        return false;
      }
    
      try {
        const r = await apiFetch('/api/auth/me');
        _CURRENT_USER = r.data;
        updateAuthUI();
        hideLandingPage();
        return true;
      } catch (e) {
        const message = String((e && e.message) || '');
      
        // Only logout and show auth modal on actual 401 errors
        if (message.includes('401')) {
          _JWT_TOKEN = '';
          _CURRENT_USER = null;
          localStorage.removeItem('aetheer_jwt_token');
          showLandingPage();
          return false;
        }
      
        // For network errors, just show landing page without clearing token
        if (_NETWORK_ERROR_RE.test(message)) {
          toast('Cannot reach API at ' + API_BASE + '. Update Backend API URL in Settings.', 'error');
          showLandingPage();
          return false;
        }
      
        // For other errors, show landing page
        showLandingPage();
        return false;
      }
    } finally {
      _authCheckInProgress = false;
    }
  }

  function showLandingPage() {
    closeSidebar();
    document.getElementById('landing-page').classList.remove('hidden');
    document.getElementById('sidebar').style.display = 'none';
    document.getElementById('main').style.display = 'none';
  }

  function hideLandingPage() {
    closeSidebar();
    document.getElementById('landing-page').classList.add('hidden');
    document.getElementById('sidebar').style.display = 'flex';
    document.getElementById('main').style.display = 'flex';
  }

  function updateAuthUI() {
    const user = _CURRENT_USER;
    const sidebarBottom = document.querySelector('.sidebar-bottom');
    const topbarProviderSelect = document.getElementById('topbar-provider-select');
    if (topbarProviderSelect) topbarProviderSelect.disabled = !user;
    updateTopbarProviderApplyState();
    if (!sidebarBottom) return;
    setText('topbar-user', user ? (user.username || user.email || 'Operator') : 'Guest');

    if (!user) {
      sidebarBottom.innerHTML = `
        <div class="provider-pill">
          <span class="dot" id="status-dot"></span>
          <span>API: </span>
          <b id="sidebar-provider">—</b>
          <span style="color:var(--text3)">/</span>
          <b id="sidebar-model" style="color:var(--accent2)">—</b>
        </div>
      `;
      return;
    }

    sidebarBottom.innerHTML = `
      <div class="provider-pill" style="margin-bottom:8px;">
        <span class="dot" id="status-dot"></span>
        <span>User:</span>
        <b>${escHtml(user.username || user.email || 'User')}</b>
      </div>
      <div class="provider-pill">
        <span>API: </span>
        <b id="sidebar-provider">—</b>
        <span style="color:var(--text3)">/</span>
        <b id="sidebar-model" style="color:var(--accent2)">—</b>
      </div>
    `;
  }

  function _setAuthModalState(open) {
    const authModal = document.getElementById('auth-modal');
    if (!authModal) return;
    authModal.style.display = open ? 'flex' : 'none';
    document.body.classList.toggle('auth-modal-open', open);
  }

  function _focusAuthField(id) {
    const el = document.getElementById(id);
    if (!el) return;
    requestAnimationFrame(() => el.focus());
  }

  function _setAuthMode(mode, shouldFocus = true) {
    const isRegister = mode === 'register';
    const loginForm = document.getElementById('auth-login-form');
    const registerForm = document.getElementById('auth-register-form');
    const title = document.getElementById('auth-modal-title');
    const subtitle = document.getElementById('auth-modal-subtitle');
    const eyebrow = document.getElementById('auth-modal-eyebrow');
    const loginTab = document.getElementById('auth-tab-login');
    const registerTab = document.getElementById('auth-tab-register');

    if (!loginForm || !registerForm || !title || !subtitle || !eyebrow || !loginTab || !registerTab) return;

    loginForm.style.display = isRegister ? 'none' : 'block';
    registerForm.style.display = isRegister ? 'block' : 'none';
    title.textContent = isRegister ? 'Create Account' : 'Sign In';
    subtitle.textContent = isRegister ? AUTH_REGISTER_SUBTITLE : AUTH_LOGIN_SUBTITLE;
    eyebrow.textContent = isRegister ? 'Create operator account' : 'Operator sign in';
    loginTab.classList.toggle('active', !isRegister);
    registerTab.classList.toggle('active', isRegister);
    loginTab.setAttribute('aria-selected', isRegister ? 'false' : 'true');
    registerTab.setAttribute('aria-selected', isRegister ? 'true' : 'false');
    loginTab.setAttribute('tabindex', isRegister ? '-1' : '0');
    registerTab.setAttribute('tabindex', isRegister ? '0' : '-1');
    if (shouldFocus) _focusAuthField(isRegister ? 'reg-email' : 'auth-email');
  }

  function _setAuthBusy(mode, busy) {
    _authBusy = busy;
    const loginSubmit = document.getElementById('auth-login-submit');
    const registerSubmit = document.getElementById('auth-register-submit');
    const controls = ['auth-tab-login', 'auth-tab-register', 'auth-login-alt', 'auth-register-alt'];

    controls.forEach(id => {
      const el = document.getElementById(id);
      if (el) el.disabled = busy;
    });

    if (loginSubmit) {
      loginSubmit.disabled = busy;
      loginSubmit.textContent = busy && mode === 'login' ? 'Signing In…' : 'Sign In';
    }
    if (registerSubmit) {
      registerSubmit.disabled = busy;
      registerSubmit.textContent = busy && mode === 'register' ? 'Creating…' : 'Create Account';
    }
  }

  function showAuthModal(mode = 'login') {
    if (!_JWT_TOKEN) showLandingPage();
    _setAuthBusy(mode, false);
    _setAuthModalState(true);
    _setAuthMode(mode);
  }

  function closeAuthModal(force = false) {
    if (_authBusy && !force) return;
    _setAuthModalState(false);
    ['auth-email', 'auth-password', 'reg-email', 'reg-password'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.value = '';
    });
    _setAuthMode('login', false);
  }

  function switchToRegister() {
    _setAuthMode('register');
  }

  function switchToLogin() {
    _setAuthMode('login');
  }

  function handleAuthKey(event, mode) {
    if (event.key !== 'Enter') return;
    if (_authBusy) return;
    event.preventDefault();
    if (mode === 'register') submitRegister();
    else submitLogin();
  }

  async function submitLogin() {
    if (_authBusy) return;
    const email = document.getElementById('auth-email').value.trim();
    const password = document.getElementById('auth-password').value.trim();

    if (!email || !password) {
      toast('Enter email and password', 'error');
      return;
    }

    _setAuthBusy('login', true);
    try {
      const r = await fetch(API_BASE + '/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });

      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error(err.detail || 'Login failed');
      }

      const data = await r.json();
      _JWT_TOKEN = data.access_token;
      _CURRENT_USER = data.user;
      localStorage.setItem('aetheer_jwt_token', _JWT_TOKEN);

      _setAuthBusy('login', false);
      toast('Welcome back!', 'success');
      closeAuthModal();
      updateAuthUI();
      hideLandingPage();

      if (data.requires_supabase_setup) {
        showOnboardingModal();
      } else {
        loadDashboard();
      }

    } catch (e) {
      toast('Login failed: ' + e.message, 'error');
    } finally {
      if (_authBusy) _setAuthBusy('login', false);
    }
  }

  async function submitRegister() {
    if (_authBusy) return;
    const email = document.getElementById('reg-email').value.trim();
    const password = document.getElementById('reg-password').value.trim();

    if (!email || !password) {
      toast('Fill in email and password', 'error');
      return;
    }

    _setAuthBusy('register', true);
    try {
      const r = await fetch(API_BASE + '/api/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });

      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        throw new Error(err.detail || 'Registration failed');
      }

      const data = await r.json();
      _JWT_TOKEN = data.access_token;
      _CURRENT_USER = data.user;
      localStorage.setItem('aetheer_jwt_token', _JWT_TOKEN);

      _setAuthBusy('register', false);
      toast('Account created successfully!', 'success');
      closeAuthModal();
      updateAuthUI();
      hideLandingPage();

      if (data.requires_supabase_setup) {
        showOnboardingModal();
      } else {
        loadDashboard();
      }

    } catch (e) {
      toast('Registration failed: ' + e.message, 'error');
    } finally {
      if (_authBusy) _setAuthBusy('register', false);
    }
  }

  async function logout() {
    try {
      // Use a timeout for the logout request (10 seconds)
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 10000);
    
      try {
        await fetch(API_BASE + '/api/auth/logout', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + _JWT_TOKEN,
          },
          signal: controller.signal,
        });
      } finally {
        clearTimeout(timeoutId);
      }
    } catch (err) {
      // Timeout or network error - log but continue with local logout
      if (err.name !== 'AbortError') {
        console.warn('Logout request error (continuing with local logout):', err.message);
      }
    }

    // Clear local session state
    _JWT_TOKEN = '';
    _CURRENT_USER = null;
    localStorage.removeItem('aetheer_jwt_token');
    updateAuthUI();
  
    // Close any open modals
    document.querySelectorAll('.modal-overlay').forEach(m => m.style.display = 'none');
    document.body.classList.remove('auth-modal-open');
  
    // Show landing page (not auth modal)
    showLandingPage();
  
    toast('Signed out successfully', 'success');
  }

  /* ══ Supabase Onboarding ═════════════════════════════════════════════ */
  async function showOnboardingModal() {
    document.getElementById('onboard-modal').style.display = 'flex';
    // Supabase setup is now automated - no SQL needed to be shown
  }

  const _authModal = document.getElementById('auth-modal');
  if (_authModal) {
    _authModal.addEventListener('click', event => {
      if (event.target === _authModal) closeAuthModal();
    });
  }

  document.addEventListener('keydown', event => {
    const authModal = document.getElementById('auth-modal');
    if (event.key === 'Escape' && authModal && authModal.style.display === 'flex') {
      closeAuthModal();
    }
  });

  async function saveSupabaseConfig() {
    const url     = document.getElementById('onboard-url').value.trim();
    const anonKey = document.getElementById('onboard-anon-key').value.trim();
    const svcKey  = document.getElementById('onboard-key').value.trim();

    if (!url || !anonKey) {
      toast('Supabase URL and Anon Key are required', 'error');
      return;
    }

    try {
      await apiFetch('/api/auth/setup/supabase', {
        method: 'PUT',
        body: JSON.stringify({
          supabase_url: url,
          supabase_anon_key: anonKey,
          supabase_service_role_key: svcKey || undefined,
        }),
      });

      toast('Supabase configuration saved!', 'success');
      document.getElementById('onboard-modal').style.display = 'none';
      loadDashboard();
    } catch (e) {
      toast('Failed to save: ' + e.message, 'error');
    }
  }

  function skipOnboarding() {
    document.getElementById('onboard-modal').style.display = 'none';
    loadDashboard();
  }

  /* ══ Init ════════════════════════════════════════════════════════════ */
  (async function init() {
    // Check auth first - this will show landing page if not authenticated
    const isAuthenticated = await checkAuth();
    if (isAuthenticated) {
      loadDashboard();
    } else {
      // Make sure landing page is visible
      showLandingPage();
    }

    // Poll dashboard every 30s (only if authenticated)
    setInterval(() => {
      if (_JWT_TOKEN && currentPage === 'dashboard') {
        loadDashboard();
      }
    }, 30000);
  })();
