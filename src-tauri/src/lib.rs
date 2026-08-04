use serde::{Deserialize, Serialize};
use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tauri::menu::{MenuBuilder, MenuItemBuilder};
use tauri::tray::{TrayIconBuilder, TrayIconEvent};
use tauri::{Manager, RunEvent, WindowEvent};
use tauri_plugin_dialog::DialogExt;

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x08000000;

const PY_BASE_URL: &str = "http://127.0.0.1:3710";
const PY_START_TIMEOUT_SECONDS: u64 = 15;

#[derive(Clone, Debug, Serialize, Deserialize, Default)]
struct UiState {
    devices: Vec<serde_json::Value>,
    pending: Vec<serde_json::Value>,
    files: Vec<serde_json::Value>,
    discovered: Vec<serde_json::Value>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
struct DeviceAddPayload {
    id: String,
    name: String,
    host: String,
    port: u16,
    kind: String,
    shared_folders: String,
    sync_roots_json: String,
    #[serde(default)]
    token: String,
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
struct ResolvePayload {
    id: String,
    resolution: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
struct PairPayload {
    id: String,
    token: String,
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

/// Return the data directory used by the Python backend.
/// Mirrors the logic in `keirstin_link.config`.
fn data_dir() -> std::path::PathBuf {
    if let Ok(v) = std::env::var("KL_DATA_DIR") {
        return std::path::PathBuf::from(v);
    }
    #[cfg(windows)]
    {
        let local_app_data = std::env::var("LOCALAPPDATA").unwrap_or_else(|_| {
            std::env::var("USERPROFILE").unwrap_or_else(|_| String::from("."))
        });
        std::path::PathBuf::from(local_app_data)
            .join("KeirstinLink")
            .join("data")
    }
    #[cfg(not(windows))]
    {
        let home = std::env::var("HOME").unwrap_or_else(|_| String::from("."));
        std::path::PathBuf::from(home)
            .join(".local")
            .join("share")
            .join("KeirstinLink")
            .join("data")
    }
}

fn pid_file() -> std::path::PathBuf {
    data_dir().join("keirstinlink.pid")
}

/// Terminate any previous KeirstinLink backend process tree.
/// PyInstaller --onefile spawns a parent wrapper + a child Python process,
/// so PID-based killing often leaves the child backend running as a zombie.
fn kill_existing_backend() {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        // Kill by image name with /T to take the whole process tree.
        let _ = Command::new("taskkill")
            .args(["/F", "/T", "/IM", "keirstinlink_backend.exe"])
            .creation_flags(CREATE_NO_WINDOW)
            .spawn()
            .and_then(|mut c| c.wait());
    }
    #[cfg(not(windows))]
    {
        let _ = Command::new("pkill")
            .args(["-9", "-f", "keirstinlink_backend"])
            .spawn()
            .and_then(|mut c| c.wait());
    }
    // Give the OS a moment to release the socket.
    std::thread::sleep(Duration::from_millis(750));
    let _ = std::fs::remove_file(pid_file());
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

fn bundled_backend_exe() -> Option<std::path::PathBuf> {
    // Tauri v2 places bundled resources next to the executable under `../resources/`.
    let exe = std::env::current_exe().unwrap_or_default();
    let base = if exe.is_file() {
        exe.parent()?.to_path_buf()
    } else {
        std::env::current_dir().unwrap_or_default()
    };
    let candidates = [
        base.join("keirstinlink_backend.exe"),
        base.join("resources").join("keirstinlink_backend.exe"),
        base.join("..").join("resources").join("keirstinlink_backend.exe"),
    ];
    for path in &candidates {
        if path.is_file() {
            return Some(path.clone());
        }
    }
    None
}

fn start_backend() -> Result<Option<Child>, String> {
    // If a backend is already listening and healthy, reuse it. This avoids
    // spawning duplicate instances and allows users to launch the backend
    // manually for debugging.
    let probe_deadline = Instant::now() + Duration::from_secs(2);
    if wait_for_backend(probe_deadline).is_ok() {
        println!("[keirstinlink] existing backend on {} is healthy; reusing", PY_BASE_URL);
        return Ok(None);
    }

    // No healthy backend found; clear the way and start our own.
    kill_existing_backend();

    let (program, args, cwd): (String, Vec<String>, Option<std::path::PathBuf>);
    let dir = py_backend_dir();
    if dir.exists() {
        // Dev mode: run from the Python source tree.
        let python_cmd = if cfg!(windows) { "python" } else { "python3" };
        program = python_cmd.to_string();
        args = vec![
            "-m".to_string(),
            "keirstin_link.main".to_string(),
            "--host".to_string(),
            "0.0.0.0".to_string(),
            "--port".to_string(),
            "3710".to_string(),
        ];
        cwd = Some(dir);
    } else if let Some(exe_path) = bundled_backend_exe() {
        // Packaged build: run the bundled PyInstaller backend executable.
        program = exe_path.to_string_lossy().to_string();
        args = vec![
            "--host".to_string(),
            "0.0.0.0".to_string(),
            "--port".to_string(),
            "3710".to_string(),
        ];
        cwd = Some(exe_path.parent().unwrap_or(&exe_path).to_path_buf());
    } else {
        // No backend source or bundle found; assume it's already running.
        return Ok(None);
    }

    #[cfg(windows)]
    let mut child = {
        use std::os::windows::process::CommandExt;
        let mut c = Command::new(&program);
        c.creation_flags(CREATE_NO_WINDOW);
        c
    };
    #[cfg(not(windows))]
    let mut child = Command::new(&program);

    let mut child = child
        .args(&args)
        .current_dir(cwd.unwrap_or_else(|| std::env::current_dir().unwrap_or_default()))
        .spawn()
        .map_err(|e| format!("failed to spawn Python backend ({}): {}", program, e))?;

    let deadline = Instant::now() + Duration::from_secs(PY_START_TIMEOUT_SECONDS);
    match wait_for_backend(deadline) {
        Ok(()) => Ok(Some(child)),
        Err(e) => {
            let _ = child.kill();
            Err(e)
        }
    }
}

fn kill_backend(state: &BackendState) {
    // Best-effort kill of the child we spawned, plus any detached backend
    // process identified by the PID file. PyInstaller --onefile spawns a
    // child Python process, so on Windows we use taskkill /T to take the
    // whole process tree.
    if let Ok(mut guard) = state.child.lock() {
        if let Some(child) = guard.take() {
            #[cfg(windows)]
            {
                use std::os::windows::process::CommandExt;
                let pid = child.id();
                let _ = Command::new("taskkill")
                    .args(["/T", "/F", "/PID", &pid.to_string()])
                    .creation_flags(CREATE_NO_WINDOW)
                    .spawn()
                    .and_then(|mut c| c.wait());
            }
            #[cfg(not(windows))]
            {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    }
    kill_backend_by_pid_file();
}

fn kill_backend_by_pid_file() {
    let pid_path = pid_file();
    let Some(pid) = std::fs::read_to_string(&pid_path)
        .ok()
        .and_then(|s| s.trim().parse::<u32>().ok())
    else {
        return;
    };
    println!("[keirstinlink] terminating backend PID {} from pid file", pid);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        let _ = Command::new("taskkill")
            .args(["/T", "/F", "/PID", &pid.to_string()])
            .creation_flags(CREATE_NO_WINDOW)
            .spawn()
            .and_then(|mut c| c.wait());
    }
    #[cfg(not(windows))]
    {
        let _ = Command::new("kill").args(["-9", &pid.to_string()]).spawn().and_then(|mut c| c.wait());
    }
    let _ = std::fs::remove_file(&pid_path);
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

fn http_put_form(path: &str, form: &[(String, String)]) -> Result<serde_json::Value, String> {
    let url = format!("{}{}", PY_BASE_URL, path);
    let form_slice: Vec<(&str, &str)> = form.iter().map(|(k, v)| (k.as_str(), v.as_str())).collect();
    ureq::put(&url)
        .timeout(Duration::from_secs(10))
        .send_form(&form_slice)
        .map_err(|e| format!("HTTP PUT {} failed: {}", url, e))?
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
    let discovered = data.get("discovered").and_then(|v| v.as_array()).cloned().unwrap_or_default();
    Ok(UiState { devices, pending, files, discovered })
}

#[tauri::command]
fn add_device(payload: DeviceAddPayload) -> Result<serde_json::Value, String> {
    let id = if payload.id.is_empty() {
        format!("dev-{}", rand::random::<u32>())
    } else {
        payload.id
    };
    let mut form = vec![
        ("id".to_string(), id),
        ("name".to_string(), payload.name),
        ("host".to_string(), payload.host),
        ("port".to_string(), payload.port.to_string()),
        ("capabilities".to_string(), payload.kind),
        ("shared_folders".to_string(), payload.shared_folders),
        ("sync_roots_json".to_string(), payload.sync_roots_json),
    ];
    if !payload.token.is_empty() {
        form.push(("token".to_string(), payload.token));
    }
    http_post_form("/devices", &form)
}

#[tauri::command]
fn update_device(payload: DeviceAddPayload) -> Result<serde_json::Value, String> {
    let id = urlencoding::encode(&payload.id);
    let mut form = vec![
        ("name".to_string(), payload.name),
        ("host".to_string(), payload.host),
        ("port".to_string(), payload.port.to_string()),
        ("capabilities".to_string(), payload.kind),
        ("shared_folders".to_string(), payload.shared_folders),
        ("sync_roots_json".to_string(), payload.sync_roots_json),
    ];
    if !payload.token.is_empty() {
        form.push(("token".to_string(), payload.token));
    }
    http_put_form(&format!("/devices/{}", id), &form)
}

#[tauri::command]
fn remove_device(payload: ByIdPayload) -> Result<serde_json::Value, String> {
    http_delete(&format!("/devices/{}", urlencoding::encode(&payload.id)))
}

#[tauri::command]
fn approve_device(payload: ApprovePayload) -> Result<serde_json::Value, String> {
    if payload.id == "__all__" {
        return http_post_form("/approve-all", &[]);
    }
    let path = if payload.approved { "/approve" } else { "/reject" };
    http_post_form(path, &[("change_id".to_string(), payload.id)])
}

#[tauri::command]
fn resolve_conflict(payload: ResolvePayload) -> Result<serde_json::Value, String> {
    http_post_form(
        "/resolve-conflict",
        &[
            ("change_id".to_string(), payload.id),
            ("resolution".to_string(), payload.resolution),
        ],
    )
}

#[tauri::command]
fn pair_device(payload: PairPayload) -> Result<serde_json::Value, String> {
    let result = http_post_form(
        "/pair",
        &[
            ("device_id".to_string(), payload.id.clone()),
            ("token".to_string(), payload.token.clone()),
        ],
    )?;
    if let Some(master_token) = result.get("master_token").and_then(|v| v.as_str()) {
        let _ = update_device(DeviceAddPayload {
            id: payload.id.clone(),
            name: String::new(),
            host: String::new(),
            port: 0,
            kind: String::new(),
            shared_folders: String::new(),
            sync_roots_json: String::new(),
            token: master_token.to_string(),
        });
    }
    Ok(result)
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
fn restart_discovery() -> Result<serde_json::Value, String> {
    http_post_form("/discovery/restart", &[])
}

#[tauri::command]
fn open_folder(path: String) -> Result<(), String> {
    tauri_plugin_opener::open_path(path, None::<&str>)
        .map_err(|e| format!("failed to open folder: {}", e))
}

#[tauri::command]
async fn pick_folder(app: tauri::AppHandle) -> Result<Option<String>, String> {
    let (tx, rx) = std::sync::mpsc::channel();
    tauri_plugin_dialog::FileDialogBuilder::new(app.dialog().clone())
        .pick_folder(move |path| {
            let _ = tx.send(path.map(|p| p.to_string()));
        });
    rx.recv()
        .map_err(|e| format!("dialog channel closed: {}", e))
        .map(|opt| opt)
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
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            // A second launch attempt arrived. Bring the existing window forward.
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(BackendState { child: Mutex::new(None) })
        .setup(|app| {
            let handle = app.app_handle().clone();

            // Start backend in a background thread so the UI window opens quickly.
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

            // Tray icon + menu
            let show_i = MenuItemBuilder::with_id("show", "Show KeirstinLink").build(app)?;
            let quit_i = MenuItemBuilder::with_id("quit", "Quit").build(app)?;
            let menu = MenuBuilder::new(app).items(&[&show_i, &quit_i]).build()?;

            let tray = TrayIconBuilder::new()
                .icon(app.default_window_icon().cloned().unwrap_or_else(|| tauri::image::Image::new(include_bytes!("../icons/32x32.png"), 32, 32)))
                .tooltip("KeirstinLink")
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "show" => {
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                    "quit" => {
                        if let Some(state) = app.try_state::<BackendState>() {
                            kill_backend(&state);
                        }
                        app.exit(0);
                    }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: tauri::tray::MouseButton::Left,
                        button_state: tauri::tray::MouseButtonState::Up,
                        ..
                    } = event
                    {
                        let app = tray.app_handle();
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                })
                .build(app)?;

            // Window close hides to tray instead of exiting.
            if let Some(window) = app.get_webview_window("main") {
                let win_clone = window.clone();
                let app_clone = app.app_handle().clone();
                window.on_window_event(move |event| {
                    if let WindowEvent::CloseRequested { api, .. } = event {
                        let _ = win_clone.hide();
                        api.prevent_close();
                    }
                    if let WindowEvent::Destroyed { .. } = event {
                        if let Some(state) = app_clone.try_state::<BackendState>() {
                            kill_backend(&state);
                        }
                    }
                });
            }

            // Keep tray reference alive for the lifetime of the app.
            app.manage(tray);

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_state,
            get_settings,
            save_settings,
            add_device,
            update_device,
            remove_device,
            approve_device,
            resolve_conflict,
            pair_device,
            sync_device,
            propose_device,
            get_folder_index,
            restart_discovery,
            open_folder,
            pick_folder,
            connect_remote,
            disconnect_remote,
            sync_remote
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|app_handle, event| {
        if let RunEvent::ExitRequested { .. } = event {
            if let Some(state) = app_handle.try_state::<BackendState>() {
                kill_backend(&state);
            }
        }
    });
}
