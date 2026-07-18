const { invoke } = window.__TAURI__.core;

const state = {
  devices: [],
  approvals: [],
  remotes: [],
  activeTab: 'sync'
};

function $(sel) { return document.querySelector(sel); }
function $$(sel) { return document.querySelectorAll(sel); }

function setStatus(msg) {
  $('#status').textContent = msg;
}

function render() {
  renderDevices();
  renderApprovals();
  renderRemotes();
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
      <span class="status-dot ${d.status}"></span>
      <div class="card-info">
        <p class="card-title">${escapeHtml(d.name)}</p>
        <p class="card-meta">${escapeHtml(d.kind)} • ${escapeHtml(d.id)}</p>
      </div>
      <div class="card-actions">
        <button class="btn" data-action="sync" data-id="${d.id}">Sync</button>
        <button class="btn danger" data-action="remove-device" data-id="${d.id}">Remove</button>
      </div>
    </div>
  `).join('');
}

function renderApprovals() {
  const list = $('#approval-list');
  $('#approval-count').textContent = state.approvals.length;
  if (state.approvals.length === 0) {
    list.innerHTML = '<p class="empty">No pending approvals.</p>';
    return;
  }
  list.innerHTML = state.approvals.map(a => `
    <div class="card">
      <div class="card-info">
        <p class="card-title">${escapeHtml(a.name || 'Unknown device')}</p>
        <p class="card-meta">${escapeHtml(a.kind || 'device')} • ${escapeHtml(a.id)}</p>
      </div>
      <div class="card-actions">
        <button class="btn success" data-action="approve" data-id="${a.id}" data-approve="true">Approve</button>
        <button class="btn danger" data-action="approve" data-id="${a.id}" data-approve="false">Deny</button>
      </div>
    </div>
  `).join('');
}

function renderRemotes() {
  const list = $('#remote-list');
  $('#remote-count').textContent = state.remotes.length;
  if (state.remotes.length === 0) {
    list.innerHTML = '<p class="empty">No remote Hermes connections.</p>';
    return;
  }
  list.innerHTML = state.remotes.map(r => `
    <div class="card">
      <span class="status-dot ${r.status}"></span>
      <div class="card-info">
        <p class="card-title">${escapeHtml(r.name || r.host)}</p>
        <p class="card-meta">${escapeHtml(r.host)}:${r.port} • ${escapeHtml(r.status)}</p>
      </div>
      <div class="card-actions">
        <button class="btn" data-action="remote-sync" data-id="${r.id}">Sync</button>
        <button class="btn danger" data-action="disconnect" data-id="${r.id}">Disconnect</button>
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
    state.approvals = data.approvals || [];
    state.remotes = data.remotes || [];
    render();
    setStatus(`Loaded ${state.devices.length} devices, ${state.approvals.length} approvals, ${state.remotes.length} remotes`);
  } catch (e) {
    console.error(e);
    setStatus('Refresh failed: ' + e.message);
  }
}

async function addDevice() {
  const name = prompt('Device name:');
  if (!name) return;
  try {
    await invoke('add_device', { name, kind: 'mobile' });
    await refresh();
  } catch (e) {
    console.error(e);
    setStatus('Add device failed: ' + e.message);
  }
}

async function approve(id, approved) {
  try {
    await invoke('approve_device', { id, approved });
    await refresh();
  } catch (e) {
    console.error(e);
    setStatus('Approval failed: ' + e.message);
  }
}

async function removeDevice(id) {
  if (!confirm('Remove this device?')) return;
  try {
    await invoke('remove_device', { id });
    await refresh();
  } catch (e) {
    console.error(e);
    setStatus('Remove failed: ' + e.message);
  }
}

async function syncDevice(id) {
  setStatus(`Syncing device ${id}...`);
  try {
    await invoke('sync_device', { id });
    setStatus('Sync queued.');
  } catch (e) {
    console.error(e);
    setStatus('Sync failed: ' + e.message);
  }
}

async function connectRemote() {
  const host = $('#remote-host').value.trim();
  const port = parseInt($('#remote-port').value, 10);
  if (!host || !port) return;
  try {
    await invoke('connect_remote', { host, port });
    $('#remote-host').value = '';
    await refresh();
  } catch (e) {
    console.error(e);
    setStatus('Connect failed: ' + e.message);
  }
}

async function disconnectRemote(id) {
  try {
    await invoke('disconnect_remote', { id });
    await refresh();
  } catch (e) {
    console.error(e);
    setStatus('Disconnect failed: ' + e.message);
  }
}

async function syncRemote(id) {
  setStatus(`Syncing remote ${id}...`);
  try {
    await invoke('sync_remote', { id });
    setStatus('Remote sync queued.');
  } catch (e) {
    console.error(e);
    setStatus('Remote sync failed: ' + e.message);
  }
}

// Event wiring
function init() {
  $$('.tab').forEach(t => t.addEventListener('click', () => showTab(t.dataset.tab)));

  $('#btn-refresh').addEventListener('click', refresh);
  $('#btn-add-device').addEventListener('click', addDevice);
  $('#btn-connect').addEventListener('click', connectRemote);

  document.addEventListener('click', e => {
    const btn = e.target.closest('[data-action]');
    if (!btn) return;
    const action = btn.dataset.action;
    const id = btn.dataset.id;
    if (action === 'approve') approve(id, btn.dataset.approve === 'true');
    else if (action === 'remove-device') removeDevice(id);
    else if (action === 'sync') syncDevice(id);
    else if (action === 'disconnect') disconnectRemote(id);
    else if (action === 'remote-sync') syncRemote(id);
  });

  refresh();
}

init();
