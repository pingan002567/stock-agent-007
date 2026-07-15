use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    Manager,
};

/// 引导 UI 与后端服务管理 CLI 之间的唯一桥：跑 `python -m backend.service_cli <args>`
/// 并解析其单 JSON 出口（doc/DESKTOP_APP_PLAN.md §3.1.1：探测判定全在 doctor，
/// 壳只做转发与渲染）。阶段 1 开发形态直接用仓库 .venv；阶段 2 打包后换 portable runtime。
#[tauri::command]
fn service_cli(args: Vec<String>) -> Result<serde_json::Value, String> {
    let repo = repo_root();
    let python = repo.join(".venv/bin/python");
    if !python.is_file() {
        return Err(format!("venv python not found: {}", python.display()));
    }
    let output = std::process::Command::new(&python)
        .arg("-m")
        .arg("backend.service_cli")
        .args(&args)
        .current_dir(&repo)
        .output()
        .map_err(|e| format!("spawn failed: {e}"))?;
    let stdout = String::from_utf8_lossy(&output.stdout);
    serde_json::from_str(stdout.trim())
        .map_err(|e| format!("bad cli json ({e}): {stdout}"))
}

/// 引导页 → 后端主界面的跳转。WKWebView 对 `tauri://` 页面发起的 `http://`
/// 顶层跳转会静默拦截（location.replace 无效也无报错），必须走 Rust 侧原生导航。
#[tauri::command]
fn navigate(webview_window: tauri::WebviewWindow, url: String) -> Result<(), String> {
    let parsed: tauri::Url = url.parse().map_err(|e| format!("bad url: {e}"))?;
    webview_window.navigate(parsed).map_err(|e| e.to_string())
}

fn repo_root() -> std::path::PathBuf {
    // 开发形态：desktop/src-tauri 相对仓库根固定为 ../..；可用 STOCKAGENT_REPO_ROOT 覆盖
    if let Ok(dir) = std::env::var("STOCKAGENT_REPO_ROOT") {
        return std::path::PathBuf::from(dir);
    }
    std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()
        .unwrap_or_else(|_| std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../.."))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![service_cli, navigate])
        .setup(|app| {
            // 空白页自愈：实测两种情况会让 webview 停在 about:blank——
            // (1) wry 初始导航偶发不触发（启动竞态）；(2) navigate 到不可达端口
            // 加载失败。轮询检测到 blank 就拉回引导页，引导页自会重新决策。
            {
                let handle = app.handle().clone();
                let home_url = app
                    .config()
                    .build
                    .dev_url
                    .clone()
                    .map(|u| u.to_string())
                    .unwrap_or_else(|| "tauri://localhost".into());
                std::thread::spawn(move || loop {
                    std::thread::sleep(std::time::Duration::from_secs(3));
                    if let Some(w) = handle.get_webview_window("main") {
                        let url = w.url().map(|u| u.to_string()).unwrap_or_default();
                        if url == "about:blank" {
                            let _ = w.navigate(home_url.parse().unwrap());
                        }
                    }
                });
            }
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }
            // 托盘：Show / Quit（§2 改造清单 5）。后端由 launchd 常驻，
            // 壳退出与否不影响盯盘告警，Quit 只是关壳。
            let show = MenuItem::with_id(app, "show", "显示主窗口", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "退出", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &quit])?;
            TrayIconBuilder::new()
                .icon(app.default_window_icon().unwrap().clone())
                .menu(&menu)
                .show_menu_on_left_click(true)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "show" => {
                        if let Some(w) = app.get_webview_window("main") {
                            let _ = w.show();
                            let _ = w.set_focus();
                        }
                    }
                    "quit" => app.exit(0),
                    _ => {}
                })
                .build(app)?;
            Ok(())
        })
        // 关窗即隐藏：常驻托盘，避免误关杀掉正在看的流式对话
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
