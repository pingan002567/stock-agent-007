import { useCopilotChat } from "@/hooks/useCopilotChat";
import { useAppState } from "@/hooks/useAppState";
import { isMobileLayout } from "@/lib/connection";

/** 「问 AI ↗」快捷入口：功能页退居看板,动作统一回聊天——按钮把卡片上下文
 * (预填问题 + 可选 symbol 锚点)直接发进当前会话。蓝色只在 hover 态出现,
 * 遵守强调色预算(doc/design/FUNCTION_PAGES_PLAN.md 3.3)。 */
export function AskAiButton({ prompt, symbol, label = "问 AI", title }: {
  prompt: string;
  symbol?: string;
  label?: string;
  title?: string;
}) {
  const { handleSend, sending } = useCopilotChat();
  const { setCurrentScreen } = useAppState();
  return (
    <button
      className="ask-ai-btn"
      type="button"
      disabled={sending}
      title={title ?? prompt}
      onClick={() => {
        if (isMobileLayout()) setCurrentScreen("chat");
        void handleSend(prompt, symbol);
      }}
    >
      {label} ↗
    </button>
  );
}
