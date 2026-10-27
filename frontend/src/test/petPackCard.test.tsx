import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { PetPackCard } from "@/components/settings/PetPackCard";

describe("桌宠包选择卡片", () => {
  it("浏览器环境下只列出内置宠物，不渲染桌面专属按钮", async () => {
    render(<PetPackCard />);
    // 内置包总在第一位
    expect(await screen.findByText("柴犬助手")).toBeTruthy();
    // 没有 __TAURI__ → 不展示「打开宠物目录」
    expect(screen.queryByText("打开宠物目录")).toBeNull();
  });
});
