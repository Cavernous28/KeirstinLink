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

function setStatus(msg) {
  $('#status').textContent = msg;
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
      </div>
      <div class="card-actions">
        <button class="btn" data-action="propose" data-id="${d.id}">Propose</button>
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
    setStatus('Could not load settings: ' + e.message);
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
    setStatus('Save settings failed: ' + err.message);
  }
}

async function browseFolder() {
  const current = $('#setting-folder').value.trim();
  const path = prompt('Enter sync folder path:', current);
  if (path) $('#setting-folder').value = path;
}

async function browseMasterFolder() {
  const current = $('#setting-master-folder').value.trim();
  const path = prompt('Enter master sync folder path:', current);
  if (path) $('#setting-master-folder').value = path;
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
    setStatus('Sync failed: ' + e.message);
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
    setStatus('Propose failed: ' + e.message);
  }
}

// Event wiring
function init() {
  $$('.tab').forEach(t => t.addEventListener('click', () => showTab(t.dataset.tab)));

  $('#btn-refresh').addEventListener('click', refresh);
  $('#btn-add-device').addEventListener('click', addDevice);
  $('#btn-settings').addEventListener('click', openSettings);
  $('#btn-close-settings').addEventListener('click', closeSettings);
  $('#btn-browse-folder').addEventListener('click', browseFolder);
  $('#btn-browse-master-folder').addEventListener('click', browseMasterFolder);
  $('#settings-form').addEventListener('submit', saveSettings);

  document.addEventListener('click', e => {
    const btn = e.target.closest('[data-action]');
    if (!btn) return;
    const action = btn.dataset.action;
    const id = btn.dataset.id;
    if (action === 'approve') approve(id, btn.dataset.approve === 'true');
    else if (action === 'remove-device') removeDevice(id);
    else if (action === 'sync') syncDevice(id);
    else if (action === 'propose') proposeDevice(id);
  });

  refresh();
  // Auto-refresh every 3s so the UI stays in sync with the backend
  setInterval(refresh, 3000);
}

init();
