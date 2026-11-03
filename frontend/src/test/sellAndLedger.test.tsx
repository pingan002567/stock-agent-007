import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const apiPost = vi.fn();
const apiGet = vi.fn();
vi.mock("@/api/client", () => ({
  apiPost: (...a: unknown[]) => apiPost(...a),
  apiGet: (...a: unknown[]) => apiGet(...a),
}));

import { SellHoldingDialog } from "@/components/features/SellHoldingDialog";
import { CashLedgerDialog } from "@/components/features/CashLedgerDialog";

describe("卖出弹窗", () => {
  beforeEach(() => { apiPost.mockReset(); });

  it("提交卖出：数量/成交价/手续费，成功后回调", async () => {
    apiPost.mockResolvedValue({ trade: { cash_delta: 2695 }, available_cash: 10075, summary: { items: [] } });
    const onSold = vi.fn();
    render(
      <SellHoldingDialog symbol="600963" name="华东医药" currency="CNY" held={100}
        onClose={() => {}} onSold={onSold} />,
    );
    fireEvent.change(screen.getByPlaceholderText("按真实成交价填"), { target: { value: "27" } });
    fireEvent.change(screen.getByPlaceholderText("0"), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "确认卖出" }));

    await waitFor(() => expect(apiPost).toHaveBeenCalled());
    expect(apiPost.mock.calls[0][0]).toBe("/api/holdings/trades");
    expect(apiPost.mock.calls[0][1]).toMatchObject({
      action: "sell", symbol: "600963", quantity: 100, fill_price: 27, fee: 5, currency: "CNY",
    });
    await waitFor(() => expect(onSold).toHaveBeenCalled());
  });

  it("数量超过持有 → 不允许提交", () => {
    render(
      <SellHoldingDialog symbol="600963" currency="CNY" held={100} onClose={() => {}} onSold={() => {}} />,
    );
    fireEvent.change(screen.getByDisplayValue("100"), { target: { value: "200" } });
    expect((screen.getByRole("button", { name: "确认卖出" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("后端拒绝时展示「持仓不足」类原因", async () => {
    apiPost.mockRejectedValue({
      detail: '409 Conflict: {"detail":{"code":"insufficient_holding","message":"600963 持仓不足：持有 100，要卖 200","symbol":"600963","held":100,"requested":200}}',
    });
    render(
      <SellHoldingDialog symbol="600963" currency="CNY" held={100} onClose={() => {}} onSold={() => {}} />,
    );
    fireEvent.change(screen.getByPlaceholderText("按真实成交价填"), { target: { value: "27" } });
    fireEvent.click(screen.getByRole("button", { name: "确认卖出" }));
    await waitFor(() => expect(screen.getByText(/持仓不足/)).toBeTruthy());
  });
});

describe("资金流水弹窗", () => {
  it("渲染流水行与分币种余额", async () => {
    apiGet.mockResolvedValue({
      items: [
        { ledger_id: "l1", currency: "USDT", delta: -150, balance_after: 350, reason: "buy",
          ref_type: "holding", ref_id: "BTC", note: null, created_at: "2026-11-04T00:10:00+00:00" },
        { ledger_id: "l2", currency: "CNY", delta: 1000, balance_after: 1000, reason: "adjust",
          ref_type: "manual", ref_id: null, note: "manual set", created_at: "2026-11-04T00:05:00+00:00" },
      ],
      cash_by_currency: { USDT: 350, CNY: 1000 },
    });
    render(<CashLedgerDialog onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText("买入")).toBeTruthy());
    expect(screen.getByText("校准")).toBeTruthy();
    expect(screen.getByText("-150.00")).toBeTruthy();
    expect(screen.getAllByText("USDT").length).toBeGreaterThan(0);
  });
});

describe("一键校准现金", () => {
  it("填多个币种 → 提交 amounts，空值跳过", async () => {
    apiPost.mockReset();
    apiPost.mockResolvedValue({ cash_by_currency: { CNY: 1000, USDT: 200 }, summary: {} });
    const onSaved = vi.fn();
    const { CashCalibrationDialog } = await import("@/components/features/CashCalibrationDialog");
    render(
      <CashCalibrationDialog
        current={{ CNY: 500, USDT: 100 }}
        onClose={() => {}}
        onSaved={onSaved}
      />,
    );
    // 预填 CNY 500 / USDT 100，改 CNY 为 1000，再给 HKD 填 0
    fireEvent.change(screen.getByLabelText("CNY 可用现金"), { target: { value: "1000" } });
    fireEvent.change(screen.getByLabelText("HKD 可用现金"), { target: { value: "0" } });
    fireEvent.click(screen.getByRole("button", { name: "保存校准" }));

    await waitFor(() => expect(apiPost).toHaveBeenCalled());
    expect(apiPost.mock.calls[0][0]).toBe("/api/holdings/cash-calibration");
    expect(apiPost.mock.calls[0][1]).toMatchObject({ amounts: { CNY: 1000, USDT: 100, HKD: 0 } });
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
  });
});
