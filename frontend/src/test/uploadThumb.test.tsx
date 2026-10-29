import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

const uploadObjectUrl = vi.fn();
vi.mock("@/lib/uploadThumbs", () => ({
  uploadObjectUrl: (...args: unknown[]) => uploadObjectUrl(...args),
  releaseUploadObjectUrl: vi.fn(),
}));

import { UploadThumb } from "@/components/features/UploadThumb";

describe("图片附件缩略图", () => {
  beforeEach(() => uploadObjectUrl.mockReset());

  it("拿到 blob URL 时渲染缩略图，点击打开预览", async () => {
    uploadObjectUrl.mockResolvedValue("blob:chart");
    render(<UploadThumb sessionId="s1" filename="chart.png" />);

    const img = await screen.findByAltText("chart.png");
    expect(img).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();

    fireEvent.click(screen.getByLabelText("预览 chart.png"));
    expect(screen.getByRole("dialog")).toBeTruthy();
    // 预览层里也有一张同源图
    expect(screen.getAllByAltText("chart.png").length).toBe(2);
  });

  it("取不到图（404/非图片）时回退成文件名芯片，并保留删除按钮", async () => {
    uploadObjectUrl.mockResolvedValue(null);
    const onRemove = vi.fn();
    render(<UploadThumb sessionId="s1" filename="chart.png" onRemove={onRemove} />);

    expect(await screen.findByText("chart.png")).toBeTruthy();
    fireEvent.click(screen.getByLabelText("移除 chart.png"));
    expect(onRemove).toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
