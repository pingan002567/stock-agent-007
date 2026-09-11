use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    Manager, WebviewWindowBuilder,
};

/// 引导 UI 与后端服务管理 CLI 之间的唯一桥：跑 `python -m backend.service_cli <args>`
/// 并解析其单 JSON 出口（doc/DESKTOP_APP_PLAN.md §3.1.1：探测判定全在 doctor，
/// 壳只做转发与渲染）。阶段 1 开发形态直接用仓库 .venv；阶段 2 打包后换 portable runtime。

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
    let parsed: serde_json::Value = serde_json::from_str(stdout.trim())
        .map_err(|e| format!("bad cli json ({e}): {stdout}"))?;
    if !output.status.success() {
        if let Some(err) = parsed.get("error").and_then(|v| v.as_str()) {
            return Err(err.to_string());
        }
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(format!(
            "service_cli exit {}: {}{}",
            output.status,
            stdout.trim(),
            if stderr.trim().is_empty() {
                String::new()
            } else {
                format!(" | stderr: {}", stderr.trim())
            }
        ));
    }
    Ok(parsed)
}

/// 引导页 → 后端主界面的跳转。WKWebView 对 `tauri://` 页面发起的 `http://`
/// 顶层跳转会静默拦截（location.replace 无效也无报错），必须走 Rust 侧原生导航。
#[tauri::command]
fn navigate(webview_window: tauri::WebviewWindow, url: String) -> Result<(), String> {
    let parsed: tauri::Url = url.parse().map_err(|e| format!("bad url: {e}"))?;
    webview_window.navigate(parsed).map_err(|e| e.to_string())
}

/// 聊天/情报里的外链在 WebView 里点开会顶掉整个工作台，改走系统浏览器。
#[tauri::command]
fn open_external(url: String) -> Result<(), String> {
    open_in_system_browser(&url)
}

fn is_app_webview_url(url: &str) -> bool {
    if url == "about:blank" || url.is_empty() {
        return false;
    }
    let Ok(parsed) = url.parse::<tauri::Url>() else {
        return false;
    };
    match parsed.scheme() {
        "tauri" => true,
        "http" | "https" => matches!(
            parsed.host_str(),
            Some("127.0.0.1" | "localhost" | "tauri.localhost")
        ),
        _ => false,
    }
}

fn open_in_system_browser(url: &str) -> Result<(), String> {
    let parsed: tauri::Url = url.parse().map_err(|e| format!("bad url: {e}"))?;
    match parsed.scheme() {
        "http" | "https" | "mailto" => {}
        other => return Err(format!("unsupported url scheme: {other}")),
    }
    #[cfg(target_os = "macos")]
    let status = std::process::Command::new("open").arg(url).status();
    #[cfg(target_os = "windows")]
    let status = std::process::Command::new("cmd")
        .args(["/C", "start", "", url])
        .status();
    #[cfg(target_os = "linux")]
    let status = std::process::Command::new("xdg-open").arg(url).status();
    match status {
        Ok(s) if s.success() => Ok(()),
        Ok(s) => Err(format!("open browser exited {s}")),
        Err(e) => Err(format!("open browser failed: {e}")),
    }
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
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![service_cli, navigate, open_external])
        .setup(|app| {
            let window_cfg = app
                .config()
                .app
                .windows
                .first()
                .cloned()
                .ok_or("missing window config")?;
            WebviewWindowBuilder::from_config(app.handle(), &window_cfg)?
                .on_navigation(|url| {
                    let href = url.as_str();
                    if href == "about:blank" || is_app_webview_url(href) {
                        true
                    } else {
                        let _ = open_in_system_browser(href);
                        false
                    }
                })
                .on_new_window(|url, _features| {
                    // target=_blank / window.open 默认会新开 WebView，打到本机后端就是 {"detail":"Not Found"}
                    let href = url.as_str();
                    if !is_app_webview_url(href) && href != "about:blank" {
                        let _ = open_in_system_browser(href);
                    }
                    tauri::webview::NewWindowResponse::Deny
                })
                .build()?;

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
                std::thread::spawn(move || {
                    let mut last_good = home_url.clone();
                    loop {
                        std::thread::sleep(std::time::Duration::from_secs(3));
                        let Some(w) = handle.get_webview_window("main") else { continue };
                        let url = w.url().map(|u| u.to_string()).unwrap_or_default();
                        if url == "about:blank" {
                            if let Ok(home) = last_good.parse() {
                                let _ = w.navigate(home);
                            }
                        } else if is_app_webview_url(&url) {
                            last_good = url;
                        } else {
                            let _ = open_in_system_browser(&url);
                            if let Ok(home) = last_good.parse() {
                                let _ = w.navigate(home);
                            }
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
            if window.label() != "main" {
                return;
            }
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
