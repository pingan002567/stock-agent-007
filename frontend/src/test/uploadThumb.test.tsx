import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const uploadObjectUrl = vi.fn();
vi.mock("@/lib/uploadThumbs", () => ({
  uploadObjectUrl: (...args: unknown[]) => uploadObjectUrl(...args),
  uploadApiUrl: (sid: string, name: string) => `/api/x/${sid}/${name}`,
  uploadFilePath: (sid: string, name: string) => `/api/x/${sid}/${name}`,
  clearUploadThumbCache: vi.fn(),
}));

import { AttachmentChips } from "@/components/features/AttachmentChips";

const files = [{ filename: "a.png" }, { filename: "b.png" }, { filename: "notes.txt" }];

describe("图片附件缩略图与多图预览", () => {
  beforeEach(() => {
    uploadObjectUrl.mockReset();
    uploadObjectUrl.mockImplementation(async (_sid: string, name: string) =>
      name.endsWith(".png") ? `blob:${name}` : null,
    );
  });

  it("图片渲染缩略图，非图片仍是文件名芯片", async () => {
    render(<AttachmentChips sessionId="s1" files={files} />);
    expect(await screen.findByAltText("a.png")).toBeTruthy();
    expect(screen.getByAltText("b.png")).toBeTruthy();
    expect(screen.getByText("notes.txt")).toBeTruthy();
  });

  it("多图预览支持 ← → 切换与 1/N 计数，Esc 关闭", async () => {
    render(<AttachmentChips sessionId="s1" files={files} />);
    fireEvent.click(await screen.findByLabelText("预览 a.png"));

    const dialog = screen.getByRole("dialog");
    expect(dialog.textContent).toContain("1 / 2");
    expect(dialog.textContent).toContain("a.png");

    fireEvent.keyDown(window, { key: "ArrowRight" });
    await waitFor(() => expect(screen.getByRole("dialog").textContent).toContain("2 / 2"));
    expect(screen.getByRole("dialog").textContent).toContain("b.png");

    // 边界回绕
    fireEvent.keyDown(window, { key: "ArrowRight" });
    await waitFor(() => expect(screen.getByRole("dialog").textContent).toContain("1 / 2"));

    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("取不到图时回退芯片，且不出现破图", async () => {
    uploadObjectUrl.mockResolvedValue(null);
    const onRemove = vi.fn();
    render(<AttachmentChips sessionId="s1" files={[{ filename: "c.png" }]} onRemove={onRemove} />);
    expect(await screen.findByText("c.png")).toBeTruthy();
    fireEvent.click(screen.getByLabelText("移除 c.png"));
    expect(onRemove).toHaveBeenCalledWith("c.png");
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
