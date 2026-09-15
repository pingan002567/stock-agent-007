import SwiftUI
import PhotosUI

struct ChatAppearanceSettingsView: View {
    @ObservedObject private var theme = AppThemeStore.shared
    @ObservedObject private var appearance = ChatAppearanceStore.shared
    @State private var photoItem: PhotosPickerItem?
    @State private var busy = false
    @State private var message = ""
    @State private var customColor: Color = AppThemeStore.shared.accentColor

    private let columns = [GridItem(.adaptive(minimum: 72), spacing: 12)]

    var body: some View {
        List {
            themeSection
            schemeSection
            wallpaperPreviewSection
            wallpaperActionsSection
            if appearance.hasBackground {
                dimSection
            }
            if !message.isEmpty {
                Section {
                    Text(message).font(.caption).foregroundStyle(.secondary)
                }
            }
        }
        .navigationTitle("外观与主题")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear { customColor = theme.accentColor }
        .onChange(of: photoItem) { _, item in
            guard let item else { return }
            Task { await importPhoto(item) }
        }
    }

    private var themeSection: some View {
        Section {
            LazyVGrid(columns: columns, spacing: 12) {
                ForEach(AppThemeStore.presets) { preset in
                    Button {
                        theme.applyPreset(preset)
                        customColor = theme.accentColor
                    } label: {
                        VStack(spacing: 6) {
                            ZStack {
                                Circle()
                                    .fill(Color(hex: preset.hex) ?? .gray)
                                    .frame(width: 36, height: 36)
                                if theme.selectedPresetId == preset.id {
                                    Image(systemName: "checkmark")
                                        .font(.caption.bold())
                                        .foregroundStyle(.white)
                                }
                            }
                            Text(preset.name)
                                .font(.caption2)
                                .foregroundStyle(.primary)
                                .lineLimit(1)
                        }
                        .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.vertical, 4)

            ColorPicker("自定义主题色", selection: $customColor, supportsOpacity: false)
                .onChange(of: customColor) { _, color in
                    theme.setCustomColor(color)
                }

            HStack {
                Text("当前")
                Spacer()
                Circle()
                    .fill(theme.accentColor)
                    .frame(width: 18, height: 18)
                Text(theme.accentHex)
                    .font(.caption.monospaced())
                    .foregroundStyle(.secondary)
            }
        } header: {
            Text("主题颜色")
        } footer: {
            Text("会作用于按钮、链接、选中态与 Tab 高亮。")
        }
    }

    private var schemeSection: some View {
        Section("显示模式") {
            Picker("显示模式", selection: $theme.scheme) {
                ForEach(AppThemeStore.SchemeOption.allCases) { opt in
                    Text(opt.title).tag(opt)
                }
            }
            .pickerStyle(.segmented)
        }
    }

    private var wallpaperPreviewSection: some View {
        Section("对话背景") {
            if let image = appearance.backgroundImage {
                Image(uiImage: image)
                    .resizable()
                    .scaledToFill()
                    .frame(maxWidth: .infinity)
                    .frame(height: 160)
                    .clipped()
                    .listRowInsets(EdgeInsets())
            } else {
                Text("未设置背景图")
                    .foregroundStyle(.secondary)
            }
        }
    }

    private var wallpaperActionsSection: some View {
        Section {
            PhotosPicker(selection: $photoItem, matching: .images) {
                Label(appearance.hasBackground ? "更换背景图" : "选择背景图", systemImage: "photo.on.rectangle")
            }
            .disabled(busy)

            if appearance.hasBackground {
                Button("清除背景图", role: .destructive) {
                    appearance.clearBackground()
                    message = "已清除背景"
                }
            }
        } footer: {
            Text("背景图仅保存在本机，不会上传。")
        }
    }

    private var dimSection: some View {
        Section {
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Text("遮罩浓度")
                    Spacer()
                    Text("\(Int(appearance.dimOpacity * 100))%")
                        .foregroundStyle(.secondary)
                        .monospacedDigit()
                }
                Slider(value: $appearance.dimOpacity, in: 0.1...0.75, step: 0.05)
            }
        } footer: {
            Text("背景较亮时可提高遮罩，避免文字看不清。")
        }
    }

    private func importPhoto(_ item: PhotosPickerItem) async {
        busy = true
        defer {
            busy = false
            photoItem = nil
        }
        do {
            guard let data = try await item.loadTransferable(type: Data.self) else {
                message = "无法读取图片"
                return
            }
            await MainActor.run {
                appearance.setBackground(data: data)
                message = "背景已更新"
            }
        } catch {
            message = error.localizedDescription
        }
    }
}
