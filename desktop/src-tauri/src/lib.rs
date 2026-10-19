use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    Manager, WebviewWindowBuilder,
};

/// 当前窗口的 label：前端据此决定渲染桌宠还是主界面
/// （两个窗口加载同一个 URL，只能靠 label 区分）
#[tauri::command]
fn window_label(window: tauri::WebviewWindow) -> String {
    window.label().to_string()
}

/// 点桌宠：把主窗口叫到前台
#[tauri::command]
fn pet_focus_main(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.unminimize();
        w.show().map_err(|e| e.to_string())?;
        w.set_focus().map_err(|e| e.to_string())?;
        println!("[pet] focus_main -> ok");
    } else {
        println!("[pet] focus_main -> main window missing");
    }
    Ok(())
}

/// 拖动桌宠：交给系统原生拖动（松手后才返回，前端据此存位置）
#[tauri::command]
fn pet_start_drag(window: tauri::WebviewWindow) -> Result<(), String> {
    window.start_dragging().map_err(|e| e.to_string())
}

/// 桌宠窗口的调试打点（前端把事件名发回来，打到终端）
#[tauri::command]
fn pet_debug(msg: String) {
    println!("[pet-debug] {msg}");
}

/// 桌宠窗口的几何（物理像素 + 缩放），前端据此按"锚点"算位置
#[tauri::command]
fn pet_metrics(window: tauri::WebviewWindow) -> Result<(i32, i32, u32, u32, f64), String> {
    let pos = window.outer_position().map_err(|e| e.to_string())?;
    let size = window.outer_size().map_err(|e| e.to_string())?;
    let sf = window.scale_factor().map_err(|e| e.to_string())?;
    Ok((pos.x, pos.y, size.width, size.height, sf))
}

/// 一次性设置桌宠窗口的位置 + 尺寸。
/// 位置由前端按「右下角锚点 - 新尺寸」算出 —— 不要在这里读旧尺寸做增量，
/// 窗口服务器的 size 是异步生效的，读到的会是上一次的值。
#[tauri::command]
fn pet_set_frame(
    window: tauri::WebviewWindow,
    x: i32,
    y: i32,
    width: f64,
    height: f64,
) -> Result<(), String> {
    window
        .set_size(tauri::LogicalSize::new(width, height))
        .map_err(|e| e.to_string())?;
    window
        .set_position(tauri::PhysicalPosition::new(x, y))
        .map_err(|e| e.to_string())?;
    Ok(())
}

/// 显示 / 隐藏桌宠窗口
#[tauri::command]
fn pet_set_visible(app: tauri::AppHandle, visible: bool) -> Result<(), String> {
    let Some(w) = app.get_webview_window("pet") else {
        return Ok(());
    };
    if visible {
        w.show().map_err(|e| e.to_string())?;
    } else {
        w.hide().map_err(|e| e.to_string())?;
    }
    println!("[pet] set_visible({visible}) -> visible={:?} pos={:?}", w.is_visible(), w.outer_position().ok());
    Ok(())
}

/// 本机后端管理 CLI：跑 `python -m backend.service_cli <args>` 并解析其单 JSON 出口。
/// 仅本地模式由 React ConnectionGate 调用；远端模式不会走这条启动链。
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

/// 引导页曾把 WebView 跳到本机后端首页；现在 SPA 自托管，主界面留在
/// tauri:// 或 Vite origin，只通过 fetch 访问 API。
#[tauri::command]
fn navigate(webview_window: tauri::WebviewWindow, url: String) -> Result<(), String> {
    let parsed: tauri::Url = url.parse().map_err(|e| format!("bad url: {e}"))?;
    if !is_app_webview_url(url.as_str()) {
        return Err("refusing to navigate WebView off the bundled UI".into());
    }
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
        "http" | "https" => {
            let host = parsed.host_str();
            let port = parsed.port_or_known_default();
            // 壳自身（Vite 开发 / 回环 UI）。不要把后端 8686 当 WebView 文档。
            matches!(host, Some("127.0.0.1" | "localhost" | "tauri.localhost"))
                && matches!(port, None | Some(80) | Some(443) | Some(5173) | Some(1420))
        }
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
        .invoke_handler(tauri::generate_handler![
            service_cli,
            navigate,
            open_external,
            window_label,
            pet_focus_main,
            pet_start_drag,
            pet_set_visible,
            pet_debug,
            pet_metrics,
            pet_set_frame
        ])
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

            // 桌宠窗口：透明、置顶、无边框、不抢焦点。先建好并藏在右下角，
            // 是否显示由前端的「显示桌宠」开关通过 pet_set_visible 决定。
            if let Some(pet_cfg) = app
                .config()
                .app
                .windows
                .iter()
                .find(|w| w.label == "pet")
                .cloned()
            {
                let pet = WebviewWindowBuilder::from_config(app.handle(), &pet_cfg)?
                    .on_navigation(|url| is_app_webview_url(url.as_str()))
                    .build()?;
                // 右下角：用 work_area（已排除菜单栏与 Dock），别压到 Dock 上
                if let Ok(Some(mon)) = app.primary_monitor() {
                    let sf = mon.scale_factor();
                    let w = (pet_cfg.width * sf) as i32;
                    let h = (pet_cfg.height * sf) as i32;
                    let margin = (24.0 * sf) as i32;
                    let area = mon.work_area();
                    let _ = pet.set_position(tauri::PhysicalPosition::new(
                        area.position.x + area.size.width as i32 - w - margin,
                        area.position.y + area.size.height as i32 - h - margin,
                    ));
                }
                // 启动即显示；前端按「显示桌宠」开关再决定是否隐藏
                let _ = pet.show();
                println!(
                    "[pet] window created: label={} visible={:?} pos={:?}",
                    pet.label(),
                    pet.is_visible(),
                    pet.outer_position().ok()
                );
            } else {
                println!("[pet] window config not found");
            }

            // 空白页自愈：webview 停在 about:blank 时拉回壳首页（bundled SPA / Vite）。
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

#[cfg(test)]
mod tests {
    use super::is_app_webview_url;

    #[test]
    fn keeps_webview_on_bundled_ui() {
        assert!(is_app_webview_url("tauri://localhost"));
        assert!(is_app_webview_url("http://localhost:5173/"));
        assert!(is_app_webview_url("http://127.0.0.1:5173/"));
        assert!(!is_app_webview_url("http://127.0.0.1:8686/"));
        assert!(!is_app_webview_url("http://example.com:8686/"));
    }
}
