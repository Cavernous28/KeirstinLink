const { invoke } = window.__TAURI__.core;

const state = {
  devices: [],
  pending: [],
  files: [],
  settings: {},
  activeTab: 'sync'
};

function $(sel) { return document.querySelector(sel); }
function $$(sel) { return document.querySelectorAll(sel); }

let statusLockedUntil = 0;

function setStatus(msg, lockSeconds = 0) {
  const now = Date.now();
  if (now < statusLockedUntil) return;
  $('#status').textContent = msg;
  if (lockSeconds > 0) {
    statusLockedUntil = now + lockSeconds * 1000;
  }
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
  renderDevices();
  renderPending();
  renderFiles();
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
      </div>
      <div class="card-actions">
        <button class="btn" data-action="propose" data-id="${d.id}">Propose</button>
        <button class="btn" data-action="sync" data-id="${d.id}">Sync</button>
        <button class="btn" data-action="edit-device" data-id="${d.id}">Edit</button>
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

function renderFiles() {
  const list = $('#file-list');
  $('#file-count').textContent = state.files.length;
  if (state.files.length === 0) {
    list.innerHTML = '<p class="empty">No synced files yet.</p>';
    return;
  }
  list.innerHTML = state.files.map(f => `
    <div class="card">
      <div class="card-info">
        <p class="card-title">${escapeHtml(f.name || 'Unknown')}</p>
        <p class="card-meta">${formatBytes(f.size || 0)} • ${escapeHtml(f.path || '')}</p>
      </div>
    </div>
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
    setStatus('Settings saved.');
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
  if (!path) return setStatus('No sync folder set');
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
  if (!path) return setStatus('No master folder set');
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
    <input type="text" class="sync-root-local" placeholder="Local folder path" />
    <span class="sync-root-arrow">→</span>
    <input type="text" class="sync-root-remote" placeholder="Master prefix (e.g. obsidian)" />
    <button type="button" class="btn icon btn-pick-sync-root" title="Pick folder">📁</button>
    <button type="button" class="btn icon btn-remove-sync-root" title="Remove">×</button>
  `;
  container.appendChild(row);
}

async function saveDevice(e) {
  e.preventDefault();
  const rawId = editingDeviceId || $('#device-id').value.trim();
  const name = $('#device-name').value.trim() || 'New Device';
  const payload = {
    id: rawId || generateDeviceId(name),
    name: name,
    host: $('#device-host').value.trim() || '127.0.0.1',
    port: parseInt($('#device-port').value || '3710', 10),
    kind: $('#device-kind').value,
    shared_folders: $('#device-shared-folders').value.trim(),
    sync_roots_json: JSON.stringify(collectSyncRoots()),
  };
  try {
    const command = editingDeviceId ? 'update_device' : 'add_device';
    await invoke(command, { payload });
    closeDeviceModal();
    await refresh();
    setStatus(editingDeviceId ? 'Device updated.' : 'Device added.');
  } catch (err) {
    console.error(err);
    setError('Save device failed: ' + errorMessage(err));
  }
}

async function refresh() {
  setStatus('Refreshing...');
  try {
    const data = await invoke('get_state');
    state.devices = data.devices || [];
    state.pending = data.pending || [];
    state.files = data.files || [];
    state.settings = data.settings || {};
    render();
    setStatus(`Loaded ${state.devices.length} devices, ${state.pending.length} pending, ${state.files.length} files`);
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

async function syncDevice(id) {
  setStatus(`Syncing device ${id}...`);
  try {
    const result = await invoke('sync_device', { payload: { id } });
    await refresh();
    const pulled = result.pulled || [];
    const skipped = result.skipped || [];
    const count = pulled.length;
    if (count > 0) {
      setStatus(`✨ Sync complete: pulled ${count} file(s)`);
    } else if (skipped.length > 0) {
      setStatus(`Sync complete: ${skipped.length} file(s) already up to date`);
    } else {
      setStatus('Sync complete: no files found');
    }
  } catch (e) {
    console.error(e);
    setError('Sync failed: ' + errorMessage(e));
  }
}

async function proposeDevice(id) {
  setStatus(`Scanning + proposing changes for ${id}...`);
  try {
    const result = await invoke('propose_device', { payload: { id } });
    await refresh();
    const count = result.count || 0;
    if (count > 0) {
      setStatus(`✨ Proposed ${count} change(s) for approval`);
    } else {
      setStatus('No changes to propose');
    }
  } catch (e) {
    console.error(e);
    setError('Propose failed: ' + errorMessage(e));
  }
}

// Event wiring
function init() {
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
  $('#settings-form').addEventListener('submit', saveSettings);
  $('#device-form').addEventListener('submit', saveDevice);

  document.addEventListener('click', e => {
    const btn = e.target.closest('[data-action]');
    if (!btn) return;
    const action = btn.dataset.action;
    const id = btn.dataset.id;
    if (action === 'approve') approve(id, btn.dataset.approve === 'true');
    else if (action === 'remove-device') removeDevice(id);
    else if (action === 'edit-device') openEditDevice(id);
    else if (action === 'sync') syncDevice(id);
    else if (action === 'propose') proposeDevice(id);
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
