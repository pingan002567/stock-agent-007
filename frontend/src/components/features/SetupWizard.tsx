import { useEffect, useMemo, useState } from "react";
import { finishSetup, type SetupStatus } from "@/api/setup";
import {
  fetchLlmProviders,
  setDefaultLlmModel,
  type LlmProviderItem,
  type LlmProvidersSnapshot,
} from "@/api/llmProviders";
import { ConnectProviderModal } from "@/components/settings/ai/ConnectProviderModal";
import { useCopilotChat } from "@/hooks/useCopilotChat";
import { isSetupModelReady, SETUP_WIZARD_COPY } from "@/lib/onboarding";

function collectModels(snapshot: LlmProvidersSnapshot): { value: string; label: string }[] {
  const rows: { value: string; label: string }[] = [];
  for (const item of snapshot.connected) {
    for (const model of item.models ?? []) {
      rows.push({
        value: `${item.id}/${model.id}`,
        label: `${item.name} · ${model.name}`,
      });
    }
  }
  return rows;
}

export function SetupWizard({
  initialStatus,
  onFinished,
}: {
  initialStatus: SetupStatus;
  onFinished: () => void;
}) {
  const { handleNewSession } = useCopilotChat();
  const [step, setStep] = useState<2 | 3>(initialStatus.model_connected && initialStatus.default_model ? 3 : 2);
  const [snapshot, setSnapshot] = useState<LlmProvidersSnapshot | null>(null);
  const [status, setStatus] = useState(initialStatus);
  const [connectId, setConnectId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refreshProviders = async () => {
    const next = await fetchLlmProviders();
    setSnapshot(next);
    setStatus((prev) => ({
      ...prev,
      model_connected: next.connected.length > 0 || next.runtime.connected,
      default_model: next.default_model ?? next.runtime.default_model,
    }));
    return next;
  };

  useEffect(() => {
    void refreshProviders().catch((err) => {
      setError(err instanceof Error ? err.message : "加载模型服务失败");
    });
    // 进场只拉一次模型列表
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const models = useMemo(() => (snapshot ? collectModels(snapshot) : []), [snapshot]);
  const catalog = snapshot?.catalog ?? [];
  const available = useMemo(
    () => (snapshot?.catalog ?? []).filter((item) => !item.custom && !item.connected),
    [snapshot],
  );
  const modelReady = isSetupModelReady(status);

  const pickDefault = async (value: string) => {
    setError("");
    try {
      const next = await setDefaultLlmModel(value);
      setSnapshot(next);
      setStatus((prev) => ({
        ...prev,
        model_connected: true,
        default_model: next.default_model ?? value,
      }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "设置默认模型失败");
    }
  };

  const enterWorkbench = async () => {
    setBusy(true);
    setError("");
    try {
      await finishSetup();
      await handleNewSession();
      onFinished();
    } catch (err) {
      setError(err instanceof Error ? err.message : "无法进入工作台");
      setBusy(false);
    }
  };

  return (
    <div className="setup-wizard" role="dialog" aria-modal="true" aria-label="开始使用">
      <div className="setup-wizard-card">
        <div className="setup-progress" aria-hidden="true">
          <span className="setup-progress-item done">1 工作区</span>
          <span className={`setup-progress-item${step === 2 ? " current" : " done"}`}>2 对话模型</span>
          <span className={`setup-progress-item${step === 3 ? " current" : ""}`}>3 准备开始</span>
        </div>

        {step === 2 ? (
          <>
            <h1 className="setup-title">{SETUP_WIZARD_COPY.step2Title}</h1>
            <p className="setup-lead">{SETUP_WIZARD_COPY.step2Lead}</p>

            {snapshot?.connected.length ? (
              <div className="setup-block">
                <div className="setup-block-title">已连接</div>
                {snapshot.connected.map((item) => (
                  <div key={item.id} className="setup-row">
                    <span className="setup-row-name">{item.name}</span>
                    <span className="setup-row-tag">已接上</span>
                  </div>
                ))}
                {models.length > 0 ? (
                  <label className="setup-default">
                    <span>默认模型</span>
                    <select
                      value={status.default_model ?? ""}
                      onChange={(e) => void pickDefault(e.target.value)}
                    >
                      <option value="" disabled>请选择</option>
                      {models.map((row) => (
                        <option key={row.value} value={row.value}>{row.label}</option>
                      ))}
                    </select>
                  </label>
                ) : null}
              </div>
            ) : null}

            {available.length > 0 ? (
              <div className="setup-block">
                <div className="setup-block-title">选择一个模型服务</div>
                {available.map((item: LlmProviderItem) => (
                  <div key={item.id} className="setup-row">
                    <div className="setup-row-name">{item.name}</div>
                    <button type="button" className="small primary" onClick={() => setConnectId(item.id)}>
                      连接
                    </button>
                  </div>
                ))}
              </div>
            ) : null}

            {error ? <div className="setup-error">{error}</div> : null}
            <button
              type="button"
              className="primary setup-next"
              disabled={!modelReady}
              onClick={() => setStep(3)}
            >
              {SETUP_WIZARD_COPY.next}
            </button>
          </>
        ) : (
          <>
            <h1 className="setup-title">{SETUP_WIZARD_COPY.step3Title}</h1>
            <p className="setup-lead">{SETUP_WIZARD_COPY.step3Lead}</p>
            <ol className="setup-list">
              {SETUP_WIZARD_COPY.step3Items.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ol>
            {error ? <div className="setup-error">{error}</div> : null}
            <button
              type="button"
              className="primary setup-next"
              disabled={busy}
              onClick={() => void enterWorkbench()}
            >
              {busy ? "正在准备…" : SETUP_WIZARD_COPY.enter}
            </button>
            <button type="button" className="ghost setup-back" disabled={busy} onClick={() => setStep(2)}>
              {SETUP_WIZARD_COPY.back}
            </button>
          </>
        )}
      </div>

      {connectId ? (
        <ConnectProviderModal
          catalog={catalog}
          providerId={connectId}
          keyLabel="密钥"
          onClose={() => setConnectId(null)}
          onConnected={() => {
            setConnectId(null);
            void refreshProviders();
          }}
        />
      ) : null}
    </div>
  );
}
