use serde::{Deserialize, Serialize};
use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tauri::Manager;

const PY_BASE_URL: &str = "http://127.0.0.1:3710";
const PY_START_TIMEOUT_SECONDS: u64 = 15;

#[derive(Clone, Debug, Serialize, Deserialize, Default)]
struct UiState {
    devices: Vec<serde_json::Value>,
    pending: Vec<serde_json::Value>,
    files: Vec<serde_json::Value>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
struct DeviceAddPayload {
    name: String,
    kind: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
struct ByIdPayload {
    id: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
struct ApprovePayload {
    id: String,
    approved: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
struct ConnectRemotePayload {
    host: String,
    port: u16,
}

struct BackendState {
    child: Mutex<Option<Child>>,
}

fn project_root() -> std::path::PathBuf {
    // Walk up from the executable until we find a directory containing src-python.
    let exe = std::env::current_exe().unwrap_or_default();
    let start = if exe.is_file() { exe.parent().unwrap_or(&exe).to_path_buf() } else { exe };
    for ancestor in start.ancestors() {
        if ancestor.join("src-python").is_dir() {
            return ancestor.to_path_buf();
        }
    }
    std::env::current_dir().unwrap_or_default()
}

fn py_backend_dir() -> std::path::PathBuf {
    project_root().join("src-python")
}

fn wait_for_backend(deadline: Instant) -> Result<(), String> {
    while Instant::now() < deadline {
        if ureq::get(&format!("{}/health", PY_BASE_URL))
            .timeout(Duration::from_secs(1))
            .call()
            .is_ok()
        {
            return Ok(());
        }
        std::thread::sleep(Duration::from_millis(250));
    }
    Err("Python backend did not start in time".to_string())
}

fn start_backend() -> Result<Option<Child>, String> {
    let dir = py_backend_dir();
    if !dir.exists() {
        // Packaged builds may bundle the backend differently; fall back to assuming it's already running.
        return Ok(None);
    }

    let python_cmd = if cfg!(windows) { "python" } else { "python3" };

    let mut child = Command::new(python_cmd)
        .arg("-m")
        .arg("keirstin_link.main")
        .arg("--host")
        .arg("127.0.0.1")
        .arg("--port")
        .arg("3710")
        .arg("--no-discovery")
        .current_dir(&dir)
        .spawn()
        .map_err(|e| format!("failed to spawn Python backend: {}", e))?;

    let deadline = Instant::now() + Duration::from_secs(PY_START_TIMEOUT_SECONDS);
    match wait_for_backend(deadline) {
        Ok(()) => Ok(Some(child)),
        Err(e) => {
            let _ = child.kill();
            Err(e)
        }
    }
}

fn http_get(path: &str) -> Result<serde_json::Value, String> {
    let url = format!("{}{}", PY_BASE_URL, path);
    ureq::get(&url)
        .timeout(Duration::from_secs(10))
        .call()
        .map_err(|e| format!("HTTP GET {} failed: {}", url, e))?
        .into_json()
        .map_err(|e| format!("failed to parse JSON from {}: {}", url, e))
}

fn http_post_form(path: &str, form: &[(String, String)]) -> Result<serde_json::Value, String> {
    let url = format!("{}{}", PY_BASE_URL, path);
    let form_slice: Vec<(&str, &str)> = form.iter().map(|(k, v)| (k.as_str(), v.as_str())).collect();
    ureq::post(&url)
        .timeout(Duration::from_secs(10))
        .send_form(&form_slice)
        .map_err(|e| format!("HTTP POST {} failed: {}", url, e))?
        .into_json()
        .map_err(|e| format!("failed to parse JSON from {}: {}", url, e))
}

fn http_delete(path: &str) -> Result<serde_json::Value, String> {
    let url = format!("{}{}", PY_BASE_URL, path);
    ureq::delete(&url)
        .timeout(Duration::from_secs(10))
        .call()
        .map_err(|e| format!("HTTP DELETE {} failed: {}", url, e))?
        .into_json()
        .map_err(|e| format!("failed to parse JSON from {}: {}", url, e))
}

#[tauri::command]
fn get_state() -> Result<UiState, String> {
    let data = http_get("/state")?;
    let devices = data.get("devices").and_then(|v| v.as_array()).cloned().unwrap_or_default();
    let pending = data.get("pending").and_then(|v| v.as_array()).cloned().unwrap_or_default();
    let files = data.get("files").and_then(|v| v.as_array()).cloned().unwrap_or_default();
    Ok(UiState { devices, pending, files })
}

#[tauri::command]
fn add_device(payload: DeviceAddPayload) -> Result<serde_json::Value, String> {
    let id = format!("dev-{}", rand::random::<u32>());
    http_post_form(
        "/devices",
        &[
            ("id".to_string(), id),
            ("name".to_string(), payload.name),
            ("host".to_string(), "127.0.0.1".to_string()),
            ("port".to_string(), "3710".to_string()),
            ("capabilities".to_string(), payload.kind),
        ],
    )
}

#[tauri::command]
fn remove_device(payload: ByIdPayload) -> Result<serde_json::Value, String> {
    http_delete(&format!("/devices/{}", urlencoding::encode(&payload.id)))
}

#[tauri::command]
fn approve_device(payload: ApprovePayload) -> Result<serde_json::Value, String> {
    let path = if payload.approved { "/approve" } else { "/reject" };
    http_post_form(path, &[("change_id".to_string(), payload.id)])
}

#[tauri::command]
fn get_settings() -> Result<serde_json::Value, String> {
    http_get("/settings")
}

#[tauri::command]
fn save_settings(payload: serde_json::Value) -> Result<serde_json::Value, String> {
    let mut form: Vec<(String, String)> = Vec::new();
    if let Some(v) = payload.get("device_name").and_then(|x| x.as_str()) {
        form.push(("device_name".to_string(), v.to_string()));
    }
    if let Some(v) = payload.get("mode").and_then(|x| x.as_str()) {
        form.push(("mode".to_string(), v.to_string()));
    }
    if let Some(v) = payload.get("sync_folder").and_then(|x| x.as_str()) {
        form.push(("sync_folder".to_string(), v.to_string()));
    }
    if let Some(v) = payload.get("master_sync_folder").and_then(|x| x.as_str()) {
        form.push(("master_sync_folder".to_string(), v.to_string()));
    }
    http_post_form("/settings", &form)
}

#[tauri::command]
fn sync_device(payload: ByIdPayload) -> Result<serde_json::Value, String> {
    http_post_form("/pull", &[("device_id".to_string(), payload.id)])
}

#[tauri::command]
fn propose_device(payload: ByIdPayload) -> Result<serde_json::Value, String> {
    http_post_form("/scan-local", &[("device_id".to_string(), payload.id.clone())])
        .and_then(|scan| {
            let changes = scan.get("changes").cloned().unwrap_or(serde_json::Value::Array(vec![]));
            http_post_form(
                "/propose-files",
                &[
                    ("device_id".to_string(), payload.id),
                    ("changes_json".to_string(), changes.to_string()),
                ],
            )
        })
}

#[tauri::command]
fn get_folder_index() -> Result<serde_json::Value, String> {
    http_get("/folder-index")
}

#[tauri::command]
fn connect_remote(payload: ConnectRemotePayload) -> Result<serde_json::Value, String> {
    let _ = payload;
    Ok(serde_json::json!({"status": "stub"}))
}

#[tauri::command]
fn disconnect_remote(payload: ByIdPayload) -> Result<(), String> {
    let _ = payload;
    Ok(())
}

#[tauri::command]
fn sync_remote(payload: ByIdPayload) -> Result<(), String> {
    let _ = payload;
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .manage(BackendState { child: Mutex::new(None) })
        .setup(|app| {
            let handle = app.app_handle().clone();
            std::thread::spawn(move || {
                match start_backend() {
                    Ok(Some(child)) => {
                        if let Some(state) = handle.try_state::<BackendState>() {
                            let _ = state.child.lock().map_err(|e| e.to_string()).map(|mut guard| {
                                *guard = Some(child);
                            });
                        }
                    }
                    Ok(None) => {
                        eprintln!("[keirstinlink] no bundled backend found; assuming it is already running");
                    }
                    Err(e) => {
                        eprintln!("[keirstinlink] backend start failed: {}", e);
                    }
                }
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_state,
            get_settings,
            save_settings,
            add_device,
            remove_device,
            approve_device,
            sync_device,
            propose_device,
            get_folder_index,
            connect_remote,
            disconnect_remote,
            sync_remote
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
