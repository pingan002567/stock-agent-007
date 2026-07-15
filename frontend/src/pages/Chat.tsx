import { SessionListColumn } from "@/components/features/SessionListColumn";
import { CopilotPanel } from "@/components/features/CopilotPanel";

/** 聊天会话中心主屏：会话列表列 + 聊天主区。
 * CopilotPanel(main) 与业务页侧栏共享 CopilotChatProvider 状态，切屏不断流。 */
export default function Chat() {
  return (
    <div className="chat-screen">
      <SessionListColumn />
      <CopilotPanel variant="main" />
    </div>
  );
}
