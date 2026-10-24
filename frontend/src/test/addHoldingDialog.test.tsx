import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { AddHoldingDialog } from "@/components/features/AddHoldingDialog";

const FX = { as_of: "2026-10-24", usd_cny: 6.684864, hkd_cny: 0.852381, usdt_usd: 1.0, degraded: false };

const apiGet = vi.fn();
const apiPost = vi.fn();

vi.mock("@/api/client", () => ({
  apiGet: (...args: unknown[]) => apiGet(...args),
  apiPost: (...args: unknown[]) => apiPost(...args),
}));

beforeEach(() => {
  apiGet.mockReset();
  apiPost.mockReset();
  apiGet.mockImplementation(async (url: string) => {
    if (url.startsWith("/api/stocks/search")) {
      return { items: [{ symbol: "BTC", name: "Bitcoin", market: "CRYPTO", instrument_type: "crypto" }] };
    }
    if (url.includes("/context")) {
      return { symbol: "BTC", price: { last: 80895.7, change_pct: -0.93, degraded: false } };
    }
    return {};
  });
});

describe("AddHoldingDialog", () => {
  it("搜币 → 选币 → 填数量，实时显示原币市值与折合占比", async () => {
    render(<AddHoldingDialog fx={FX} bookCny={50000} onClose={() => {}} onSaved={() => {}} />);

    fireEvent.change(screen.getByPlaceholderText("输入代码或名称搜索…"), { target: { value: "BT" } });
    const hit = await screen.findByRole("button", { name: /Bitcoin/ });
    fireEvent.click(hit);

    // 现价 80,895.7 应该出现（USDT 用 ₮）
    await waitFor(() => expect(screen.getByText(/₮80,896/)).toBeTruthy());

    const qty = screen.getByPlaceholderText("0.08");
    fireEvent.change(qty, { target: { value: "0.08" } });

    // 原币市值 = 80895.7 × 0.08 = 6471.656 → 千元以上取整 ₮6,472
    await waitFor(() => expect(screen.getByText(/₮6,472/)).toBeTruthy());
    // 折合 = 6471.656 × 6.684864 ≈ ¥43,262
    await waitFor(() => expect(screen.getByText(/¥43,262/)).toBeTruthy());
    // 占组合 = 43262 / (50000 + 43262) ≈ 46.4%
    await waitFor(() => expect(screen.getByText(/46\.\d\d%/)).toBeTruthy());
  });

  it("拿不到汇率时不折算，只提示按原币记（不按 1:1 硬算）", async () => {
    render(
      <AddHoldingDialog
        fx={{ ...FX, usd_cny: null, degraded: true }}
        bookCny={null}
        onClose={() => {}}
        onSaved={() => {}}
      />,
    );

    fireEvent.change(screen.getByPlaceholderText("输入代码或名称搜索…"), { target: { value: "BT" } });
    fireEvent.click(await screen.findByRole("button", { name: /Bitcoin/ }));
    fireEvent.change(await screen.findByPlaceholderText("0.08"), { target: { value: "1" } });

    await waitFor(() => expect(screen.getByText(/汇率不可用/)).toBeTruthy());
    // 绝不能出现一个假的折合人民币金额
    expect(screen.queryByText(/折算 ¥/)).toBeNull();
  });

  it("保存时提交原币数量与成本，不提交任何折算值", async () => {
    const onSaved = vi.fn();
    apiPost.mockResolvedValue({ items: [] });

    render(<AddHoldingDialog fx={FX} bookCny={50000} onClose={() => {}} onSaved={onSaved} />);

    fireEvent.change(screen.getByPlaceholderText("输入代码或名称搜索…"), { target: { value: "BT" } });
    fireEvent.click(await screen.findByRole("button", { name: /Bitcoin/ }));
    fireEvent.change(await screen.findByPlaceholderText("0.08"), { target: { value: "0.08" } });
    fireEvent.change(screen.getByPlaceholderText("可留空"), { target: { value: "76200" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => expect(apiPost).toHaveBeenCalled());
    const [url, body] = apiPost.mock.calls[0];
    expect(url).toBe("/api/holdings");
    expect(body).toEqual({ symbol: "BTC", quantity: 0.08, cost: 76200 });
    // 折算不落库：body 里不能有人民币市值
    expect(JSON.stringify(body)).not.toContain("market_value");
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
  });
});
