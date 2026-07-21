const { invoke } = window.__TAURI__.core;

const state = {
  devices: [],
  pending: [],
  files: [],
  activeTab: 'sync'
};

function $(sel) { return document.querySelector(sel); }
function $$(sel) { return document.querySelectorAll(sel); }

function setStatus(msg) {
  $('#status').textContent = msg;
}

function render() {
  renderDevices();
  renderPending();
}

function renderDevices() {
  const list = $('#device-list');
  $('#device-count').textContent = state.devices.length;
  if (state.devices.length === 0) {
    list.innerHTML = '<p class="empty">No devices yet. Click + Add Device to pair one.</p>';
    return;
  }
  list.innerHTML = state.devices.map(d => `
    <div class="card">
      <div class="card-info">
        <p class="card-title">${escapeHtml(d.name || 'Unknown')}</p>
        <p class="card-meta">${escapeHtml(d.host || 'unknown')}:${d.port || 0} • ${escapeHtml((d.capabilities || []).join(', ') || 'device')}</p>
      </div>
      <div class="card-actions">
        <button class="btn" data-action="sync" data-id="${d.id}">Sync</button>
        <button class="btn danger" data-action="remove-device" data-id="${d.id}">Remove</button>
      </div>
    </div>
  `).join('');
}

function renderPending() {
  const list = $('#approval-list');
  $('#approval-count').textContent = state.pending.length;
  if (state.pending.length === 0) {
    list.innerHTML = '<p class="empty">No pending approvals.</p>';
    return;
  }
  list.innerHTML = state.pending.map(a => `
    <div class="card">
      <div class="card-info">
        <p class="card-title">${escapeHtml(a.file_id || 'Unknown')}</p>
        <p class="card-meta">${escapeHtml(a.source_device || 'unknown device')} • ${escapeHtml(a.id)}</p>
      </div>
      <div class="card-actions">
        <button class="btn success" data-action="approve" data-id="${a.id}" data-approve="true">Approve</button>
        <button class="btn danger" data-action="approve" data-id="${a.id}" data-approve="false">Deny</button>
      </div>
    </div>
  `).join('');
}

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function randomId(prefix) {
  return `${prefix}_${Math.random().toString(36).slice(2, 9)}`;
}

function showTab(tab) {
  state.activeTab = tab;
  $$('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
  $$('.tab-panel').forEach(p => p.classList.toggle('active', p.id === tab));
}

// Stub data loaders / actions
async function refresh() {
  setStatus('Refreshing...');
  try {
    const data = await invoke('get_state');
    state.devices = data.devices || [];
    state.pending = data.pending || [];
    state.files = data.files || [];
    render();
    setStatus(`Loaded ${state.devices.length} devices, ${state.pending.length} pending`);
  } catch (e) {
    console.error(e);
    setStatus('Refresh failed: ' + e.message);
  }
}

async function addDevice() {
  const name = prompt('Device name:');
  if (!name) return;
  try {
    await invoke('add_device', { payload: { name, kind: 'mobile' } });
    await refresh();
  } catch (e) {
    console.error(e);
    setStatus('Add device failed: ' + e.message);
  }
}

async function approve(id, approved) {
  try {
    await invoke('approve_device', { payload: { id, approved } });
    await refresh();
  } catch (e) {
    console.error(e);
    setStatus('Approval failed: ' + e.message);
  }
}

async function removeDevice(id) {
  if (!confirm('Remove this device?')) return;
  try {
    await invoke('remove_device', { payload: { id } });
    await refresh();
  } catch (e) {
    console.error(e);
    setStatus('Remove failed: ' + e.message);
  }
}

async function syncDevice(id) {
  setStatus(`Syncing device ${id}...`);
  try {
    await invoke('sync_device', { payload: { id } });
    setStatus('Sync queued.');
  } catch (e) {
    console.error(e);
    setStatus('Sync failed: ' + e.message);
  }
}

// Event wiring
function init() {
  $$('.tab').forEach(t => t.addEventListener('click', () => showTab(t.dataset.tab)));

  $('#btn-refresh').addEventListener('click', refresh);
  $('#btn-add-device').addEventListener('click', addDevice);

  document.addEventListener('click', e => {
    const btn = e.target.closest('[data-action]');
    if (!btn) return;
    const action = btn.dataset.action;
    const id = btn.dataset.id;
    if (action === 'approve') approve(id, btn.dataset.approve === 'true');
    else if (action === 'remove-device') removeDevice(id);
    else if (action === 'sync') syncDevice(id);
  });

  refresh();
}

init();
