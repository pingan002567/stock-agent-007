import SwiftUI

struct HumanInputCardView: View {
    let request: HumanInputRequest
    var answered: Bool = false
    var disabled: Bool = false
    var onSubmit: (([String: Any], String) -> Void)?

    @State private var freeText = ""
    @State private var localError = ""

    private var interactive: Bool { onSubmit != nil && !answered && !disabled }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(request.title?.isEmpty == false ? request.title! : "AI 需要你的补充信息")
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)

            Text(request.question)
                .font(.subheadline)
                .fixedSize(horizontal: false, vertical: true)

            if let context = request.context, !context.isEmpty {
                Text(context)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            if answered {
                Text("已回答")
                    .font(.caption2)
                    .foregroundStyle(.green)
            } else if !request.options.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(request.options) { option in
                        Button {
                            guard interactive else { return }
                            let response = request.optionResponse(option: option)
                            onSubmit?(response, request.displayMessage(for: response))
                        } label: {
                            Text(option.label)
                                .font(.subheadline)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .padding(.horizontal, 12)
                                .padding(.vertical, 10)
                                .background(Color.accentColor.opacity(0.12))
                                .foregroundStyle(Color.accentColor)
                                .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                        }
                        .buttonStyle(.plain)
                        .disabled(!interactive)
                    }
                }
            }

            if interactive, request.options.isEmpty || request.inputMode == "choice_with_other" || request.inputMode == "free_text" {
                HStack(spacing: 8) {
                    TextField(request.options.isEmpty ? "输入补充信息…" : "其它回答…", text: $freeText, axis: .vertical)
                        .lineLimit(1...4)
                        .textFieldStyle(.roundedBorder)
                    Button("发送") {
                        submitText()
                    }
                    .disabled(freeText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }

            if !localError.isEmpty {
                Text(localError)
                    .font(.caption2)
                    .foregroundStyle(.red)
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.accentColor.opacity(0.08))
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .strokeBorder(Color.accentColor.opacity(0.25), lineWidth: 1)
        )
    }

    private func submitText() {
        let value = freeText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty else {
            localError = "请输入内容后再提交"
            return
        }
        localError = ""
        let response = request.textResponse(value: value)
        onSubmit?(response, request.displayMessage(for: response))
        freeText = ""
    }
}
