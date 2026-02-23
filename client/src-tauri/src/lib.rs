use std::sync::Mutex;

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Manager};
use tauri_plugin_shell::process::CommandChild;
#[cfg(not(dev))]
use tauri_plugin_shell::ShellExt;

// ---------------------------------------------------------------------------
// Credential types
// ---------------------------------------------------------------------------

#[derive(Serialize, Deserialize, Clone, Debug, Default)]
pub struct AwsCredentials {
    pub access_key_id: String,
    pub secret_access_key: String,
    pub region: String,
    pub session_token: Option<String>,
}

// ---------------------------------------------------------------------------
// Managed state — holds the sidecar child so we can kill/restart it.
// ---------------------------------------------------------------------------

pub struct SidecarState(pub Mutex<Option<CommandChild>>);

// ---------------------------------------------------------------------------
// Credential file helpers
// ---------------------------------------------------------------------------

fn credentials_path(app: &AppHandle) -> std::path::PathBuf {
    app.path()
        .app_config_dir()
        .expect("could not resolve app config dir")
        .join("credentials.json")
}

fn read_credentials(app: &AppHandle) -> Option<AwsCredentials> {
    let path = credentials_path(app);
    let content = std::fs::read_to_string(path).ok()?;
    serde_json::from_str(&content).ok()
}

fn write_credentials(app: &AppHandle, creds: &AwsCredentials) -> Result<(), String> {
    let path = credentials_path(app);
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let json = serde_json::to_string_pretty(creds).map_err(|e| e.to_string())?;
    std::fs::write(&path, json).map_err(|e| e.to_string())
}

// ---------------------------------------------------------------------------
// Sidecar helpers
// ---------------------------------------------------------------------------

/// Spawns the FastAPI sidecar with the given credentials injected as env vars.
#[cfg(not(dev))]
fn spawn_sidecar(app: &AppHandle, creds: &AwsCredentials) -> Result<CommandChild, String> {
    let cmd = app
        .shell()
        .sidecar("aws-cost-optimizer-api")
        .map_err(|e| e.to_string())?
        .env("AWS_ACCESS_KEY_ID", &creds.access_key_id)
        .env("AWS_SECRET_ACCESS_KEY", &creds.secret_access_key)
        .env("AWS_DEFAULT_REGION", &creds.region);

    let cmd = match &creds.session_token {
        Some(t) if !t.is_empty() => cmd.env("AWS_SESSION_TOKEN", t),
        _ => cmd,
    };

    let (_rx, child) = cmd.spawn().map_err(|e| e.to_string())?;
    Ok(child)
}

/// Polls the FastAPI health endpoint until it responds or the timeout is reached.
#[cfg(not(dev))]
fn wait_for_backend(timeout_secs: u64) -> bool {
    let deadline =
        std::time::Instant::now() + std::time::Duration::from_secs(timeout_secs);
    loop {
        if std::time::Instant::now() >= deadline {
            return false;
        }
        match ureq::get("http://127.0.0.1:8000/api/v1/health").call() {
            Ok(_) => return true,
            Err(_) => std::thread::sleep(std::time::Duration::from_millis(300)),
        }
    }
}

// ---------------------------------------------------------------------------
// Tauri commands
// ---------------------------------------------------------------------------

/// Returns stored AWS credentials, or null if none have been saved yet.
#[tauri::command]
fn load_credentials(app: AppHandle) -> Option<AwsCredentials> {
    read_credentials(&app)
}

/// Persists credentials and (in production builds) restarts the sidecar with
/// the new environment variables.
#[tauri::command]
fn save_credentials(
    app: AppHandle,
    creds: AwsCredentials,
    _state: tauri::State<'_, SidecarState>,
) -> Result<(), String> {
    write_credentials(&app, &creds)?;

    #[cfg(not(dev))]
    {
        let mut guard = _state.0.lock().map_err(|e| e.to_string())?;

        // Kill the old sidecar if one is running.
        if let Some(old) = guard.take() {
            let _ = old.kill();
        }

        // Spawn a fresh sidecar with the updated credentials.
        let child = spawn_sidecar(&app, &creds)?;

        if !wait_for_backend(15) {
            return Err("Backend did not start within 15 seconds".into());
        }

        *guard = Some(child);
    }

    Ok(())
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(SidecarState(Mutex::new(None)))
        .invoke_handler(tauri::generate_handler![load_credentials, save_credentials])
        .setup(|app| {
            // Spawn the sidecar in production builds only. In dev mode the
            // server is assumed to be running separately
            // (e.g. `uvicorn app.main:app --port 8000`).
            #[cfg(not(dev))]
            {
                let handle = app.handle().clone();
                if let Some(creds) = read_credentials(&handle) {
                    let child = spawn_sidecar(&handle, &creds)
                        .expect("failed to spawn aws-cost-optimizer-api sidecar");

                    // Store so save_credentials can kill and restart it.
                    let sidecar_state = app.state::<SidecarState>();
                    *sidecar_state.0.lock().unwrap() = Some(child);

                    if !wait_for_backend(10) {
                        return Err("Backend did not start within 10 seconds".into());
                    }
                }
                // No credentials saved yet: sidecar not started.
                // The UI detects this and redirects to /settings.
            }

            // Show the main window (created hidden in tauri.conf.json so we
            // can wait for the backend before revealing it).
            let window = app.get_webview_window("main").unwrap();
            window.show()?;

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
