fn main() {
    tauri_build::try_build(
        tauri_build::Attributes::new().app_manifest(
            tauri_build::AppManifest::new().commands(&[
                "service_cli",
                "navigate",
                "open_external",
                "window_label",
                "pet_focus_main",
                "pet_start_drag",
                "pet_set_visible",
                "pet_debug",
                "pet_metrics",
                "pet_set_frame",
            ]),
        ),
    )
    .expect("failed to run tauri build");
}
