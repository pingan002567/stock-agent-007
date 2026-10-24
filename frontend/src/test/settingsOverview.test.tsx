import { describe, expect, it } from "vitest";
import { collectIssues, type OverviewSettings } from "@/lib/settingsOverview";

const base: OverviewSettings = {
  agent_runtime: { available: true, active_client: "embedded" },
  runtime_config: { has_api_key: true, model_name: "deepseek-v4-flash" },
  risk_policy: { active: { name: "稳健档", rules: { single_position_max_weight_pct: 20, sector_max_weight_pct: 35 } } },
  data_sources: { provider_states: { eastmoney: { enabled: true } } },
  trading_controls: { real_order: "blocked" },
};

describe("配置概览的待确认项", () => {
  it("一切正常时没有阻塞项", () => {
    const issues = collectIssues(base, [{ enabled: true }], true);
    expect(issues.filter((i) => i.level === "block")).toHaveLength(0);
  });

  it("缺 Key 算阻塞，指向模型分区", () => {
    const issues = collectIssues({ ...base, runtime_config: {} }, [{ enabled: true }], true);
    const block = issues.find((i) => i.level === "block");
    expect(block?.title).toContain("凭证");
    expect(block?.tab).toBe("ai");
  });

  it("单票上限 ≥50% 提醒确认（真实激进档）", () => {
    const issues = collectIssues(
      { ...base, risk_policy: { active: { name: "激进全仓型", rules: { single_position_max_weight_pct: 100 } } } },
      [{ enabled: true }], true,
    );
    const warn = issues.find((i) => i.level === "warn");
    expect(warn?.title).toContain("100%");
    expect(warn?.detail).toContain("激进全仓型");
  });

  it("任务列表没加载成功时，不把网络失败说成「没有任务」", () => {
    const notLoaded = collectIssues(base, [], false);
    expect(notLoaded.some((i) => i.title.includes("定时任务"))).toBe(false);
    const loaded = collectIssues(base, [], true);
    expect(loaded.some((i) => i.title.includes("定时任务"))).toBe(true);
  });
});

describe("概览组件能渲染", () => {
  it("渲染不抛异常（曾因缺 RISK_LEVEL_LABEL 整页崩成「页面渲染异常」）", async () => {
    const { render } = await import("@testing-library/react");
    const { SettingsOverview } = await import("@/components/settings/SettingsOverview");
    const { container } = render(
      <SettingsOverview
        settings={{
          agent_runtime: { available: true, active_client: "embedded" },
          runtime_config: { has_api_key: true, model_name: "deepseek-v4-flash", thinking_enabled: true },
          risk_policy: { active: { name: "激进全仓型", rules: { single_position_max_weight_pct: 100, sector_max_weight_pct: 100 } } },
          data_sources: { provider_states: { eastmoney: { enabled: true } } },
          investor_profile: { risk_level: "aggressive" },
          trading_controls: { real_order: "blocked" },
          skills: [{ enabled: true }],
        }}
        onNavigate={() => {}}
      />,
    );
    const text = container.textContent ?? "";
    expect(text).toContain("当前生效");
    expect(text).toContain("激进");        // 画像标签查表命中
    expect(text).toContain("激进全仓型");   // 风控档位名
  });
});
