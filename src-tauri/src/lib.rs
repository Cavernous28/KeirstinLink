use serde::{Deserialize, Serialize};
use std::sync::Mutex;
use tauri::State;

#[derive(Clone, Debug, Serialize, Deserialize)]
struct Device {
    id: String,
    name: String,
    kind: String,
    status: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
struct Approval {
    id: String,
    name: String,
    kind: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
struct RemoteHermes {
    id: String,
    name: String,
    host: String,
    port: u16,
    status: String,
}

#[derive(Clone, Debug, Serialize, Deserialize, Default)]
struct AppState {
    devices: Vec<Device>,
    approvals: Vec<Approval>,
    remotes: Vec<RemoteHermes>,
}

struct AppStateMutex(Mutex<AppState>);

#[derive(Clone, Debug, Serialize, Deserialize)]
struct StateSnapshot {
    devices: Vec<Device>,
    approvals: Vec<Approval>,
    remotes: Vec<RemoteHermes>,
}

#[derive(Debug, Deserialize)]
struct AddDevicePayload {
    name: String,
    kind: String,
}

#[derive(Debug, Deserialize)]
struct ByIdPayload {
    id: String,
}

#[derive(Debug, Deserialize)]
struct ApprovePayload {
    id: String,
    approved: bool,
}

#[derive(Debug, Deserialize)]
struct ConnectRemotePayload {
    host: String,
    port: u16,
}

fn random_id(prefix: &str) -> String {
    format!("{}_{:06x}", prefix, rand::random::<u32>() & 0xffffff)
}

#[tauri::command]
fn get_state(state: State<AppStateMutex>) -> Result<StateSnapshot, String> {
    let guard = state.0.lock().map_err(|e| e.to_string())?;
    Ok(StateSnapshot {
        devices: guard.devices.clone(),
        approvals: guard.approvals.clone(),
        remotes: guard.remotes.clone(),
    })
}

#[tauri::command]
fn add_device(
    state: State<AppStateMutex>,
    payload: AddDevicePayload,
) -> Result<Device, String> {
    let mut guard = state.0.lock().map_err(|e| e.to_string())?;
    let device = Device {
        id: random_id("dev"),
        name: payload.name,
        kind: payload.kind,
        status: "offline".to_string(),
    };
    guard.devices.push(device.clone());
    Ok(device)
}

#[tauri::command]
fn remove_device(state: State<AppStateMutex>, payload: ByIdPayload) -> Result<(), String> {
    let mut guard = state.0.lock().map_err(|e| e.to_string())?;
    guard.devices.retain(|d| d.id != payload.id);
    Ok(())
}

#[tauri::command]
fn approve_device(
    state: State<AppStateMutex>,
    payload: ApprovePayload,
) -> Result<(), String> {
    let mut guard = state.0.lock().map_err(|e| e.to_string())?;
    if let Some(pos) = guard.approvals.iter().position(|a| a.id == payload.id) {
        let approval = guard.approvals.remove(pos);
        if payload.approved {
            guard.devices.push(Device {
                id: approval.id,
                name: approval.name,
                kind: approval.kind,
                status: "online".to_string(),
            });
        }
    }
    Ok(())
}

#[tauri::command]
fn sync_device(_state: State<AppStateMutex>, _payload: ByIdPayload) -> Result<(), String> {
    // TODO: wire to real sync engine
    Ok(())
}

#[tauri::command]
fn connect_remote(
    state: State<AppStateMutex>,
    payload: ConnectRemotePayload,
) -> Result<RemoteHermes, String> {
    let mut guard = state.0.lock().map_err(|e| e.to_string())?;
    let id = random_id("remote");
    let remote = RemoteHermes {
        id: id.clone(),
        name: format!("{}:{}", payload.host, payload.port),
        host: payload.host,
        port: payload.port,
        status: "offline".to_string(),
    };
    guard.remotes.push(remote.clone());
    Ok(remote)
}

#[tauri::command]
fn disconnect_remote(state: State<AppStateMutex>, payload: ByIdPayload) -> Result<(), String> {
    let mut guard = state.0.lock().map_err(|e| e.to_string())?;
    guard.remotes.retain(|r| r.id != payload.id);
    Ok(())
}

#[tauri::command]
fn sync_remote(_state: State<AppStateMutex>, _payload: ByIdPayload) -> Result<(), String> {
    // TODO: wire to real remote sync engine
    Ok(())
}

// Seed a few demo approvals so the UI isn't empty on first load.
fn seed_state(_app: &mut tauri::App) {
    // State is already pre-seeded in manage(); future dynamic seeding can go here.
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .manage(AppStateMutex(Mutex::new(AppState {
            devices: vec![],
            approvals: vec![
                Approval {
                    id: random_id("req"),
                    name: "Chris’s iPhone".to_string(),
                    kind: "mobile".to_string(),
                },
                Approval {
                    id: random_id("req"),
                    name: "Work Laptop".to_string(),
                    kind: "desktop".to_string(),
                },
            ],
            remotes: vec![],
        })))
        .setup(|app| {
            seed_state(app);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_state,
            add_device,
            remove_device,
            approve_device,
            sync_device,
            connect_remote,
            disconnect_remote,
            sync_remote
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
