// KeirstinLink frontend — runs under Tauri desktop or Android WebView bridge
const isTauri = !!(window.__TAURI__ && window.__TAURI__.core);
let backendHost = '127.0.0.1';
let backendPort = 3710;

function setBackend(host, port) {
  backendHost = host || backendHost;
  backendPort = port || backendPort;
  if (window.KeirstinLinkBackend) {
    window.KeirstinLinkBackend.host = backendHost;
    window.KeirstinLinkBackend.port = backendPort;
  }
}

window.KeirstinLinkBackend = { host: backendHost, port: backendPort, connect: setBackend };

async function invoke(command, payload = {}) {
  if (isTauri) {
    const { invoke: tauriInvoke } = window.__TAURI__.core;
    return tauriInvoke(command, payload);
  }
  return bridgeHttp(command, payload);
}

async function bridgeHttp(command, payload) {
  // Map Tauri command names to backend HTTP endpoints + form fields
  const host = window.KeirstinLinkBackend.host || (window.AndroidBridge ? window.AndroidBridge.getBackendHost() : '127.0.0.1');
  const port = window.KeirstinLinkBackend.port || (window.AndroidBridge ? window.AndroidBridge.getBackendPort() : 3710);
  const base = `http://${host}:${port}`;

  const formFor = (obj) => {
    const params = new URLSearchParams();
    for (const [k, v] of Object.entries(obj)) {
      if (v !== undefined && v !== null) params.append(k, typeof v === 'object' ? JSON.stringify(v) : String(v));
    }
    return params;
  };

  switch (command) {
    case 'get_state': {
      const res = await fetch(`${base}/state`);
      if (!res.ok) throw new Error(await res.text());
      return await res.json();
    }
    case 'get_settings': {
      const res = await fetch(`${base}/settings`);
      if (!res.ok) throw new Error(await res.text());
      return await res.json();
    }
    case 'save_settings': {
      const res = await fetch(`${base}/settings`, { method: 'POST', body: formFor(payload.payload || payload) });
      if (!res.ok) throw new Error(await res.text());
      return await res.json();
    }
    case 'pick_folder': {
      if (window.AndroidBridge && window.AndroidBridge.pickFolder) {
        window.AndroidBridge.pickFolder();
        // TODO: return a promise resolved by the bridge callback
        return null;
      }
      throw new Error('Folder picker not available on this platform');
    }
    case 'open_folder': {
      // No-op on Android; rely on bridge toast
      return null;
    }
    case 'add_device':
    case 'update_device': {
      const p = payload.payload || payload;
      const body = {
        id: p.id,
        name: p.name,
        host: p.host,
        port: String(p.port),
        capabilities: p.kind,
        shared_folders: p.shared_folders,
        sync_roots_json: p.sync_roots_json,
      };
      const url = command === 'update_device' ? `${base}/devices/${encodeURIComponent(p.id)}` : `${base}/devices`;
      const res = await fetch(url, { method: command === 'update_device' ? 'PUT' : 'POST', body: formFor(body) });
      if (!res.ok) throw new Error(await res.text());
      return await res.json();
    }
    case 'remove_device': {
      const id = payload.id || payload;
      const res = await fetch(`${base}/devices/${encodeURIComponent(id)}`, { method: 'DELETE' });
      if (!res.ok) throw new Error(await res.text());
      return await res.json();
    }
    case 'approve_device': {
      const id = payload.id || payload;
      const url = payload.approved ? `${base}/approve` : `${base}/reject`;
      const res = await fetch(url, { method: 'POST', body: formFor({ change_id: id }) });
      if (!res.ok) throw new Error(await res.text());
      return await res.json();
    }
    case 'resolve_conflict': {
      const res = await fetch(`${base}/resolve-conflict`, {
        method: 'POST',
        body: formFor({ change_id: payload.id, resolution: payload.resolution })
      });
      if (!res.ok) throw new Error(await res.text());
      return await res.json();
    }
    case 'pair_device': {
      const res = await fetch(`${base}/pair`, { method: 'POST', body: formFor({ device_id: payload.id, token: payload.token }) });
      if (!res.ok) throw new Error(await res.text());
      return await res.json();
    }
    case 'sync_device': {
      const res = await fetch(`${base}/pull`, { method: 'POST', body: formFor({ device_id: payload.id }) });
      if (!res.ok) throw new Error(await res.text());
      return await res.json();
    }
    case 'propose_device': {
      const scan = await fetch(`${base}/scan-local`, { method: 'POST', body: formFor({ device_id: payload.id }) });
      if (!scan.ok) throw new Error(await scan.text());
      const scanData = await scan.json();
      const changes = scanData.changes || [];
      const res = await fetch(`${base}/propose-files`, {
        method: 'POST',
        body: formFor({ device_id: payload.id, changes_json: JSON.stringify(changes) })
      });
      if (!res.ok) throw new Error(await res.text());
      return await res.json();
    }
    case 'restart_discovery': {
      const res = await fetch(`${base}/discovery/restart`, { method: 'POST' });
      if (!res.ok) throw new Error(await res.text());
      return await res.json();
    }
    default:
      throw new Error(`Unknown bridge command: ${command}`);
  }
}

window.KeirstinLinkBridge = { onFilesPicked: () => {} };

const state = {
  devices: [],
  pending: [],
  files: [],
  discovered: [],
  settings: {},
  activeTab: 'sync'
};

function $(sel) { return document.querySelector(sel); }
function $$(sel) { return document.querySelectorAll(sel); }

let statusLockedUntil = 0;

function setStatus(msg, lockSeconds = 2) {
  const now = Date.now();
  if (now < statusLockedUntil) return;
  $('#status').textContent = msg;
  statusLockedUntil = now + lockSeconds * 1000;
}

function setStatusQuiet(msg) {
  const now = Date.now();
  if (now < statusLockedUntil) return;
  $('#status').textContent = msg;
}

function setError(msg) {
  setStatus(msg, 10);
}

function errorMessage(e) {
  if (e && typeof e.message === 'string' && e.message) return e.message;
  if (e && typeof e === 'string') return e;
  return String(e || 'Unknown error');
}

function render() {
  renderDiscoveryStatus();
  renderNearby();
  renderDevices();
  renderDiscovered();
  renderPending();
  renderFiles();
}

function renderDiscoveryStatus() {
  const indicator = $('#discovery-indicator');
  const text = $('#discovery-text');
  const lastSeen = $('#discovery-lastseen');
  const count = state.discovered.length;
  indicator.className = 'status-dot online';
  text.textContent = `Discovery: listening on LAN`;
  if (count > 0) {
    lastSeen.textContent = `${count} nearby device${count === 1 ? '' : 's'} seen`;
  } else {
    lastSeen.textContent = 'No nearby devices yet';
  }
}

function renderNearby() {
  const list = $('#nearby-list');
  const countBadge = $('#nearby-count');
  if (!list) return;
  countBadge.textContent = state.discovered.length;
  if (state.discovered.length === 0) {
    list.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-icon">📡</div>
        <p>No KeirstinLink devices found on your network yet.</p>
        <p class="hint">Make sure another device is running KeirstinLink on the same Wi-Fi or LAN.</p>
      </div>`;
    return;
  }
  // Hide devices already in the device list
  const knownIds = new Set((state.devices || []).map(d => `${d.host}:${d.port}`));
  const nearby = state.discovered.filter(d => !knownIds.has(`${d.host}:${d.port}`));
  countBadge.textContent = nearby.length;
  list.innerHTML = nearby.map(d => `
    <div class="card">
      <div class="card-info">
        <p class="card-title">${escapeHtml(d.name || 'Unknown')}</p>
        <p class="card-meta">${escapeHtml(d.host || 'unknown')}:${d.port || 0} • ${escapeHtml((d.capabilities || []).join(', ') || 'device')}</p>
      </div>
      <div class="card-actions">
        <button class="btn success" data-action="add-discovered" data-host="${d.host}" data-port="${d.port || 3710}" data-name="${escapeHtml(d.name || 'Unknown')}">Add</button>
      </div>
    </div>
  `).join('');
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
        <p class="card-meta">Shared: ${escapeHtml((d.shared_folders || []).join(', ') || 'all')}</p>
        <p class="card-meta">Roots: ${escapeHtml((d.sync_roots || []).map(r => r.local_path + (r.remote_prefix ? ' → ' + r.remote_prefix : '')).join(', ') || 'none')}</p>
        <p class="card-meta text-muted">ID: ${escapeHtml(d.id)} • Token: ${d.token ? 'set' : 'not set'}</p>
      </div>
      <div class="card-actions">
        <button class="btn" data-action="propose" data-id="${d.id}">Propose</button>
        <button class="btn" data-action="sync" data-id="${d.id}">Sync</button>
        <button class="btn" data-action="pair" data-id="${d.id}" ${d.token ? 'disabled title="Paired"' : ''}>${d.token ? 'Paired' : 'Pair'}</button>
        <button class="btn" data-action="edit-device" data-id="${d.id}">Edit</button>
        <button class="btn danger" data-action="remove-device" data-id="${d.id}">Remove</button>
      </div>
    </div>
  `).join('');
}

function renderDiscovered() {
  const list = $('#discovered-list');
  const tabCount = $('#discovered-tab-count');
  if (tabCount) tabCount.textContent = state.discovered.length;
  if (!list) return;
  $('#discovered-count').textContent = state.discovered.length;
  if (state.discovered.length === 0) {
    list.innerHTML = '<p class="empty">No LAN devices discovered yet. Make sure another KeirstinLink device is on the same network.</p>';
    return;
  }
  list.innerHTML = state.discovered.map(d => `
    <div class="card">
      <div class="card-info">
        <p class="card-title">${escapeHtml(d.name || 'Unknown')}</p>
        <p class="card-meta">${escapeHtml(d.host || 'unknown')}:${d.port || 0} • ${escapeHtml((d.capabilities || []).join(', ') || 'device')}</p>
      </div>
      <div class="card-actions">
        <button class="btn success" data-action="add-discovered" data-host="${d.host}" data-port="${d.port || 3710}" data-name="${escapeHtml(d.name || 'Unknown')}">Add</button>
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
  list.innerHTML = state.pending.map(a => {
    const payload = a.payload || {};
    const target = payload.target_filename || payload.relative_path || a.relative_path || 'unknown';
    const targetDisplay = String(target).replace(/\\\\/g, '\\');
    const actionLabel = a.action ? a.action.toUpperCase() : 'CHANGE';
    const actionClass = a.action === 'delete' ? 'danger' : (a.action === 'update' ? 'warning' : 'success');
    const conflict = payload.conflict;
    const conflictBadge = conflict ? '<span class="badge danger">CONFLICT</span> ' : '';

    const incomingSize = formatBytes(payload.size || 0);
    const masterSize = formatBytes(payload.original_size || 0);
    const sizeInfo = a.action === 'delete'
      ? `<span class="text-muted">will delete master file (${masterSize})</span>`
      : (conflict
        ? `<span class="text-warning">Incoming ${incomingSize}</span> vs <span class="text-muted">Master ${masterSize}</span>`
        : `<span class="text-muted">incoming ${incomingSize}</span>`);

    const actions = conflict
      ? `
        <button class="btn success" data-action="resolve" data-id="${a.id}" data-resolution="accept" title="Overwrite master with incoming">Accept Incoming</button>
        <button class="btn" data-action="resolve" data-id="${a.id}" data-resolution="keep" title="Keep current master file">Keep Master</button>
        <button class="btn danger" data-action="resolve" data-id="${a.id}" data-resolution="reject" title="Reject and discard incoming">Reject</button>
      `
      : `
        <button class="btn success" data-action="approve" data-id="${a.id}" data-approve="true">Approve</button>
        <button class="btn danger" data-action="approve" data-id="${a.id}" data-approve="false">Deny</button>
      `;
    return `
    <div class="card ${conflict ? 'conflict' : ''}">
      <div class="card-info">
        <p class="card-title">${escapeHtml(a.file_id || 'Unknown')}</p>
        <p class="card-meta">${conflictBadge}<span class="badge ${actionClass}">${escapeHtml(actionLabel)}</span> ${escapeHtml(a.source_device || 'unknown device')} → ${escapeHtml(targetDisplay)}</p>
        <p class="card-meta">${sizeInfo}</p>
        <p class="card-meta text-muted">${escapeHtml(a.id)}</p>
      </div>
      <div class="card-actions">
        ${actions}
      </div>
    </div>
  `}).join('');
}

function renderFiles() {
  const list = $('#file-list');
  $('#file-count').textContent = state.files.length;
  if (state.files.length === 0) {
    list.innerHTML = '<p class="empty">No synced files yet.</p>';
    return;
  }

  // Capture currently closed groups before re-rendering
  const closed = new Set();
  list.querySelectorAll('.sync-group').forEach(group => {
    const summary = group.querySelector('.sync-group-header span');
    if (summary && !group.open) {
      closed.add(summary.textContent);
    }
  });

  // Group files by source device
  const groups = {};
  state.files.forEach(f => {
    const source = f.source_device || 'Unknown device';
    if (!groups[source]) groups[source] = [];
    groups[source].push(f);
  });

  list.innerHTML = Object.entries(groups).map(([source, files]) => `
    <details class="sync-group" ${closed.has(source) ? '' : 'open'}>
      <summary class="sync-group-header">
        <span>${escapeHtml(source)}</span>
        <span class="badge">${files.length}</span>
      </summary>
      <div class="sync-group-list">
        ${files.map(f => `
          <div class="card small">
            <div class="card-info">
              <p class="card-title">${escapeHtml(f.name || 'Unknown')}</p>
              <p class="card-meta">${formatBytes(f.size || 0)} • ${escapeHtml((f.path || '').replace(/\\\\/g, '\\'))}</p>
            </div>
          </div>
        `).join('')}
      </div>
    </details>
  `).join('');
}

function formatBytes(bytes) {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function showTab(tab) {
  state.activeTab = tab;
  $$('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
  $$('.tab-panel').forEach(p => p.classList.toggle('active', p.id === tab));
}

// Settings modal
async function openSettings() {
  try {
    const s = await invoke('get_settings');
    state.settings = s || {};
    $('#setting-device-name').value = s.device_name || '';
    $('#setting-mode').value = s.mode || 'master';
    $('#setting-folder').value = s.sync_folder || '';
    $('#setting-master-folder').value = s.master_sync_folder || '';
  } catch (e) {
    console.error(e);
    setError('Could not load settings: ' + errorMessage(e));
  }
  $('#settings-modal').classList.add('open');
}

function closeSettings() {
  $('#settings-modal').classList.remove('open');
}

async function saveSettings(e) {
  e.preventDefault();
  const payload = {
    device_name: $('#setting-device-name').value.trim(),
    mode: $('#setting-mode').value,
    sync_folder: $('#setting-folder').value.trim(),
    master_sync_folder: $('#setting-master-folder').value.trim(),
  };
  try {
    await invoke('save_settings', { payload });
    closeSettings();
    await refresh();
    setStatus('Settings saved.', 0);
  } catch (err) {
    console.error(err);
    setError('Save settings failed: ' + errorMessage(err));
  }
}

async function browseFolder() {
  try {
    const selected = await invoke('pick_folder');
    if (selected) $('#setting-folder').value = selected;
  } catch (e) {
    console.error(e);
    setError('Browse folder failed: ' + errorMessage(e));
  }
}

async function openFolder() {
  const path = $('#setting-folder').value.trim();
  if (!path) return setStatus('No sync folder set', 0);
  try {
    await invoke('open_folder', { path });
  } catch (e) {
    console.error(e);
    setError('Open folder failed: ' + errorMessage(e));
  }
}

async function browseMasterFolder() {
  try {
    const selected = await invoke('pick_folder');
    if (selected) $('#setting-master-folder').value = selected;
  } catch (e) {
    console.error(e);
    setError('Browse folder failed: ' + errorMessage(e));
  }
}

async function openMasterFolder() {
  const path = $('#setting-master-folder').value.trim();
  if (!path) return setStatus('No master folder set', 0);
  try {
    await invoke('open_folder', { path });
  } catch (e) {
    console.error(e);
    setError('Open folder failed: ' + errorMessage(e));
  }
}

// Device modal
let editingDeviceId = null;

function openAddDevice() {
  editingDeviceId = null;
  $('#device-modal-title').textContent = 'Add Device';
  $('#device-id').value = '';
  $('#device-name').value = '';
  $('#device-host').value = '127.0.0.1';
  $('#device-port').value = '3710';
  $('#device-kind').value = 'mobile';
  $('#device-shared-folders').value = '';
  renderSyncRoots([]);
  $('#device-modal').classList.add('open');
}

function generateDeviceId(name) {
  const base = (name || 'device').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  const suffix = Math.floor(Math.random() * 10000);
  return `${base}-${suffix}`;
}

function openEditDevice(id) {
  const d = state.devices.find(x => x.id === id);
  if (!d) return;
  editingDeviceId = id;
  $('#device-modal-title').textContent = 'Edit Device';
  $('#device-id').value = d.id || '';
  $('#device-name').value = d.name || '';
  $('#device-host').value = d.host || '127.0.0.1';
  $('#device-port').value = String(d.port || 3710);
  $('#device-kind').value = (d.capabilities && d.capabilities[0]) || 'mobile';
  $('#device-shared-folders').value = (d.shared_folders || []).join(', ');
  renderSyncRoots(d.sync_roots || []);
  $('#device-modal').classList.add('open');
}

function closeDeviceModal() {
  $('#device-modal').classList.remove('open');
  editingDeviceId = null;
}

function renderSyncRoots(roots) {
  const container = $('#sync-roots-list');
  container.innerHTML = '';
  const rows = roots.length ? roots : [{ local_path: '', remote_prefix: '' }];
  rows.forEach((root) => {
    const row = document.createElement('div');
    row.className = 'sync-root-row';
    row.innerHTML = `
      <input type="text" class="sync-root-local" placeholder="Local folder path" value="${escapeHtml(root.local_path || '')}" />
      <span class="sync-root-arrow">→</span>
      <input type="text" class="sync-root-remote" placeholder="Master prefix (e.g. obsidian)" value="${escapeHtml(root.remote_prefix || '')}" />
      <button type="button" class="btn icon btn-pick-sync-root" title="Pick folder">📁</button>
      <button type="button" class="btn icon btn-remove-sync-root" title="Remove">×</button>
    `;
    container.appendChild(row);
  });
}

function collectSyncRoots() {
  const rows = $$('.sync-root-row');
  const roots = [];
  rows.forEach(row => {
    const local = row.querySelector('.sync-root-local').value.trim();
    const remote = row.querySelector('.sync-root-remote').value.trim().replace(/\\/g, '/').replace(/^\/+|\/+$/g, '');
    if (local) {
      roots.push({ local_path: local, remote_prefix: remote });
    }
  });
  return roots;
}

async function pickSyncRootFolder(btn) {
  try {
    const selected = await invoke('pick_folder');
    if (!selected) return;
    const row = btn.closest('.sync-root-row');
    if (!row) return;
    row.querySelector('.sync-root-local').value = selected;
  } catch (e) {
    console.error(e);
    setError('Pick folder failed: ' + errorMessage(e));
  }
}

function addSyncRootRow() {
  const container = $('#sync-roots-list');
  const row = document.createElement('div');
  row.className = 'sync-root-row';
  row.innerHTML = `
    <div class="sync-root-fields">
      <div class="sync-root-field">
        <label>Local folder on this device</label>
        <div class="sync-root-input-group">
          <input type="text" class="sync-root-local" placeholder="C:\Users\me\Obsidian" />
          <button type="button" class="btn icon btn-pick-sync-root" title="Pick folder">📁</button>
        </div>
      </div>
      <div class="sync-root-field">
        <label>Master prefix (optional)</label>
        <input type="text" class="sync-root-remote" placeholder="e.g. obsidian / phone-photos" />
      </div>
      <button type="button" class="btn icon btn-remove-sync-root" title="Remove">×</button>
    </div>
    <p class="sync-root-hint">Files from the local folder will appear under <code>KeirstinLinkSync/[prefix]/</code> on the master.</p>
  `;
  container.appendChild(row);
}

async function saveDevice(e) {
  e.preventDefault();
  const rawId = editingDeviceId || $('#device-id').value.trim();
  const name = $('#device-name').value.trim() || 'New Device';
  const roots = collectSyncRoots();
  const payload = {
    id: rawId || generateDeviceId(name),
    name: name,
    host: $('#device-host').value.trim() || '127.0.0.1',
    port: parseInt($('#device-port').value || '3710', 10),
    kind: $('#device-kind').value,
    shared_folders: $('#device-shared-folders').value.trim(),
    sync_roots_json: JSON.stringify(roots),
  };
  console.log('Saving device payload:', payload);
  try {
    const command = editingDeviceId ? 'update_device' : 'add_device';
    const result = await invoke(command, { payload });
    console.log('Save device result:', result);
    closeDeviceModal();
    await refresh();
    setStatus(editingDeviceId ? 'Device updated.' : 'Device added.', 3);
  } catch (err) {
    console.error('Save device error:', err);
    setError('Save device failed: ' + errorMessage(err));
  }
}

async function refresh() {
  setStatusQuiet('Refreshing...');
  try {
    const data = await invoke('get_state');
    const before = JSON.stringify(state);
    state.devices = data.devices || [];
    state.pending = data.pending || [];
    state.files = data.files || [];
    state.settings = data.settings || {};
    state.discovered = data.discovered || [];
    const after = JSON.stringify({
      devices: state.devices,
      pending: state.pending,
      files: state.files,
      discovered: state.discovered,
    });
    if (after !== before) {
      render();
    }
    setStatusQuiet(`Loaded ${state.devices.length} devices, ${state.pending.length} pending, ${state.files.length} files`);
  } catch (e) {
    console.error(e);
    setError('Refresh failed: ' + errorMessage(e));
  }
  }

async function removeDevice(id) {
  if (!confirm('Remove this device?')) return;
  try {
    await invoke('remove_device', { payload: { id } });
    await refresh();
  } catch (e) {
    console.error(e);
    setError('Remove failed: ' + errorMessage(e));
  }
}

async function approve(id, approved) {
  try {
    await invoke('approve_device', { payload: { id, approved } });
    await refresh();
  } catch (e) {
    console.error(e);
    setError('Approval failed: ' + errorMessage(e));
  }
}

async function approveAll() {
  if (!state.pending.length) return setStatus('No pending approvals', 3);
  if (!confirm(`Approve all ${state.pending.length} pending file(s)?`)) return;
  setStatus(`Approving ${state.pending.length} change(s)...`, 0);
  try {
    const result = await invoke('approve_device', { payload: { id: '__all__', approved: true } });
    await refresh();
    const count = result.count || 0;
    const failed = result.failed || [];
    if (failed.length) {
      setError(`Approved ${count}, failed ${failed.length}`);
    } else {
      setStatus(`✨ Approved ${count} change(s)`, 3);
    }
  } catch (e) {
    console.error(e);
    setError('Approve all failed: ' + errorMessage(e));
  }
}

async function syncDevice(id) {
  setStatus(`Syncing device ${id}...`, 0);
  try {
    const result = await invoke('sync_device', { payload: { id } });
    await refresh();
    const pulled = result.pulled || [];
    const skipped = result.skipped || [];
    const count = pulled.length;
    if (count > 0) {
      setStatus(`✨ Sync complete: pulled ${count} file(s)`, 3);
    } else if (skipped.length > 0) {
      setStatus(`Sync complete: ${skipped.length} file(s) already up to date`, 3);
    } else {
      setStatus('Sync complete: no files found', 3);
    }
  } catch (e) {
    console.error(e);
    setError('Sync failed: ' + errorMessage(e));
  }
}

async function addDiscoveredDevice(name, host, port) {
  try {
    const payload = {
      id: generateDeviceId(name),
      name: name,
      host: host,
      port: port,
      kind: 'mobile',
      shared_folders: '',
      sync_roots_json: JSON.stringify([]),
    };
    await invoke('add_device', { payload });
    await refresh();
    setStatus('Discovered device added', 3);
  } catch (e) {
    console.error(e);
    setError('Add discovered device failed: ' + errorMessage(e));
  }
}

async function resolveConflict(id, resolution) {
  try {
    await invoke('resolve_conflict', { payload: { id, resolution } });
    await refresh();
    const labels = { accept: 'Accepted incoming', keep: 'Kept master', reject: 'Rejected' };
    setStatus(labels[resolution] || 'Resolved', 3);
  } catch (e) {
    console.error(e);
    setError('Resolve conflict failed: ' + errorMessage(e));
  }
}

async function pairDevice(id) {
  const d = state.devices.find(x => x.id === id);
  if (!d) return setError('Device not found');
  setStatus(`Pairing with ${d.name || id}...`, 0);
  try {
    let token;
    if (isTauri) {
      const myTokenResp = await fetch('http://127.0.0.1:3710/my-token');
      if (!myTokenResp.ok) throw new Error('Could not fetch local device token');
      const data = await myTokenResp.json();
      token = data.token;
    } else {
      // Mobile client: generate a token locally and persist it in localStorage.
      token = localStorage.getItem('kl_device_token');
      if (!token) {
        token = generateDeviceToken();
        localStorage.setItem('kl_device_token', token);
      }
    }
    await invoke('pair_device', { payload: { id, token } });
    await refresh();
    setStatus(`✨ Paired with ${d.name || id}`, 3);
  } catch (e) {
    console.error(e);
    setError('Pairing failed: ' + errorMessage(e));
  }
}

function generateDeviceToken() {
  const arr = new Uint8Array(32);
  if (window.crypto && window.crypto.getRandomValues) {
    window.crypto.getRandomValues(arr);
  } else {
    for (let i = 0; i < arr.length; i++) arr[i] = Math.floor(Math.random() * 256);
  }
  return btoa(String.fromCharCode(...arr)).replace(/[^a-zA-Z0-9]/g, '').slice(0, 43);
}

async function proposeDevice(id) {
  setStatus(`Scanning + proposing changes for ${id}...`, 0);
  try {
    const result = await invoke('propose_device', { payload: { id } });
    await refresh();
    const count = result.count || 0;
    if (count > 0) {
      setStatus(`✨ Proposed ${count} change(s) for approval`, 3);
    } else {
      setStatus('No changes to propose', 3);
    }
  } catch (e) {
    console.error(e);
    setError('Propose failed: ' + errorMessage(e));
  }
}

async function restartDiscovery() {
  setStatus('Restarting discovery...', 0);
  try {
    const result = await invoke('restart_discovery');
    await refresh();
    const restarted = result && result.restarted;
    setStatus(restarted ? '✨ Discovery restarted' : 'Discovery restart failed', 3);
  } catch (e) {
    console.error(e);
    setError('Restart discovery failed: ' + errorMessage(e));
  }
}

async function addDeviceByIp() {
  const host = $('#manual-ip').value.trim();
  const port = parseInt($('#manual-port').value || '3710', 10);
  if (!host) return setStatus('Enter an IP address', 3);
  setStatus(`Adding ${host}:${port}...`, 0);
  try {
    const resp = await fetch(`http://${host}:${port}/health`, { method: 'GET', mode: 'cors' });
    if (!resp.ok) throw new Error(`No KeirstinLink at ${host}:${port}`);
    const info = await resp.json();
    const name = info.service || host;
    await addDiscoveredDevice(name, host, port);
    $('#manual-ip').value = '';
  } catch (e) {
    console.error(e);
    setError('Add by IP failed: ' + errorMessage(e));
  }
}

// Event wiring
function init() {
  // If running inside Android WebView, try to load saved backend host/port
  try {
    if (window.AndroidBridge && window.AndroidBridge.getBackendHost) {
      const androidHost = window.AndroidBridge.getBackendHost();
      const androidPort = window.AndroidBridge.getBackendPort();
      if (androidHost) {
        setBackend(androidHost, androidPort);
        console.log('[init] Android backend host', androidHost, androidPort);
      }
    }
  } catch (e) {
    console.log('[init] not running under Android bridge');
  }

  $$('.tab').forEach(t => t.addEventListener('click', () => showTab(t.dataset.tab)));

  $('#btn-refresh').addEventListener('click', refresh);
  $('#btn-add-device').addEventListener('click', openAddDevice);
  $('#btn-settings').addEventListener('click', openSettings);
  $('#btn-close-settings').addEventListener('click', closeSettings);
  $('#btn-close-device').addEventListener('click', closeDeviceModal);
  $('#btn-browse-folder').addEventListener('click', browseFolder);
  $('#btn-open-folder').addEventListener('click', openFolder);
  $('#btn-browse-master-folder').addEventListener('click', browseMasterFolder);
  $('#btn-open-master-folder').addEventListener('click', openMasterFolder);
  $('#btn-add-sync-root').addEventListener('click', addSyncRootRow);
  $('#btn-approve-all').addEventListener('click', approveAll);
  $('#settings-form').addEventListener('submit', saveSettings);
  $('#device-form').addEventListener('submit', saveDevice);
  $('#btn-add-by-ip').addEventListener('click', addDeviceByIp);
  $('#btn-restart-discovery').addEventListener('click', restartDiscovery);

  document.addEventListener('click', e => {
    const btn = e.target.closest('[data-action]');
    if (!btn) return;
    const action = btn.dataset.action;
    const id = btn.dataset.id;
    if (action === 'approve') approve(id, btn.dataset.approve === 'true');
    else if (action === 'resolve') resolveConflict(id, btn.dataset.resolution);
    else if (action === 'remove-device') removeDevice(id);
    else if (action === 'edit-device') openEditDevice(id);
    else if (action === 'sync') syncDevice(id);
    else if (action === 'pair') pairDevice(id);
    else if (action === 'propose') proposeDevice(id);
    else if (action === 'add-discovered') addDiscoveredDevice(btn.dataset.name, btn.dataset.host, parseInt(btn.dataset.port || '3710', 10));
  });

  $('#device-form').addEventListener('click', e => {
    const btn = e.target.closest('.btn-pick-sync-root');
    if (btn) {
      e.preventDefault();
      pickSyncRootFolder(btn);
      return;
    }
    const removeBtn = e.target.closest('.btn-remove-sync-root');
    if (removeBtn) {
      e.preventDefault();
      removeBtn.closest('.sync-root-row').remove();
    }
  });

  refresh();
  // Auto-refresh every 3s so the UI stays in sync with the backend
  setInterval(refresh, 3000);
}

init();
