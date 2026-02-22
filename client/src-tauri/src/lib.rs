use tauri::Manager;
use tauri_plugin_shell::ShellExt;

/// Polls the FastAPI health endpoint until it responds or the timeout is reached.
/// Returns true if the server came up within the timeout.
fn wait_for_backend(timeout_secs: u64) -> bool {
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(timeout_secs);
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

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            // Spawn the FastAPI sidecar. In dev mode the sidecar is not
            // bundled, so we skip this and assume the server is already
            // running (e.g. `uvicorn app.main:app --port 8000`).
            #[cfg(not(dev))]
            {
                let sidecar_cmd = app
                    .shell()
                    .sidecar("aws-cost-optimizer-api")
                    .expect("sidecar binary not found — run PyInstaller first");

                let (_rx, _child) = sidecar_cmd
                    .spawn()
                    .expect("failed to spawn aws-cost-optimizer-api sidecar");

                // Keep the child handle alive for the duration of the app.
                // Tauri will kill it when the last window closes.
                app.manage(_child);

                // Wait up to 10 seconds for the backend to be ready.
                if !wait_for_backend(10) {
                    return Err("Backend did not start within 10 seconds".into());
                }
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
