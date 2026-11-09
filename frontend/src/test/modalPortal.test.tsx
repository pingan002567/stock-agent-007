import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { ConfirmDialog } from "@/components/ui/ConfirmDialog";

describe("确认弹窗必须挂到 body（避免被页面容器劫持定位）", () => {
  it("渲染在容器之外、document.body 之下", () => {
    const { container } = render(
      // 模拟"页面里某个带 transform 的容器"
      <div style={{ transform: "translateY(0)" }}>
        <ConfirmDialog
          title="删除定时任务"
          description="删除「加密货币美洲时段前检查」？"
          onCancel={vi.fn()}
          onConfirm={vi.fn()}
        />
      </div>,
    );

    // 关键：不能留在页面容器里（那里是 position: fixed 的包含块）
    expect(container.querySelector(".session-delete-modal")).toBeNull();
    const modal = document.body.querySelector(".session-delete-modal");
    expect(modal).not.toBeNull();
    expect(screen.getByText("删除定时任务")).toBeTruthy();
  });
});
