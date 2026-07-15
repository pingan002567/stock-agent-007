import { useState } from "react";
import { useCopilotChat } from "@/hooks/useCopilotChat";

/** 聊天中心第二列：会话列表（doc/DESKTOP_APP_PLAN.md §3.4 迁移第 1 步）。
 * 状态全部来自 CopilotChatProvider，与聊天主区/业务页侧栏共享。 */
export function SessionListColumn() {
  const {
    sessions, currentSession,
    switchSession, handleNewSession, handleRenameSession, handleDeleteSession,
  } = useCopilotChat();

  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [deletingId, setDeletingId] = useState<string | null>(null);

  return (
    <aside className="session-col">
      <div className="session-col-head">
        <span className="session-col-title">对话</span>
        <button className="session-col-new" onClick={handleNewSession} title="新建对话">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
          </svg>
        </button>
      </div>
      <div className="session-col-list">
        {sessions.length === 0 && (
          <div className="session-col-empty">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
            </svg>
            <div>暂无对话</div>
            <div className="session-col-empty-hint">点右上角开始新对话</div>
          </div>
        )}
        {sessions.map((s) => (
          <div key={s.session_id}>
            {renamingId === s.session_id ? (
              <div className="session-rename">
                <input
                  className="session-rename-input"
                  value={renameValue}
                  onChange={(e) => setRenameValue(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") { handleRenameSession(s.session_id, renameValue); setRenamingId(null); }
                    if (e.key === "Escape") setRenamingId(null);
                  }}
                  onBlur={() => { handleRenameSession(s.session_id, renameValue); setRenamingId(null); }}
                  autoFocus
                />
              </div>
            ) : (
              <div
                className={`session-item${s.session_id === currentSession?.session_id ? " active" : ""}`}
                onClick={() => switchSession(s.session_id)}
              >
                <div className="session-item-content">
                  <div className="session-item-title">{s.title}</div>
                  <div className="session-item-meta">{s.message_count ?? 0} 条消息</div>
                </div>
                <div className="session-item-actions">
                  <button
                    className="session-action-btn"
                    title="重命名"
                    onClick={(e) => { e.stopPropagation(); setRenamingId(s.session_id); setRenameValue(s.title); }}
                  >✎</button>
                  <button
                    className="session-action-btn danger"
                    title="删除"
                    onClick={(e) => { e.stopPropagation(); setDeletingId(s.session_id); }}
                  >✕</button>
                </div>
              </div>
            )}
            {deletingId === s.session_id && (
              <div className="session-delete-modal">
                <div className="session-delete-content">
                  <div className="session-delete-icon">⚠️</div>
                  <div className="session-delete-title">删除会话</div>
                  <div className="session-delete-desc">
                    确定要删除会话「{s.title}」吗？此操作将删除该会话下的所有消息，且不可恢复。
                  </div>
                  <div className="session-delete-actions">
                    <button className="session-delete-cancel" onClick={() => setDeletingId(null)}>取消</button>
                    <button className="session-delete-confirm" onClick={() => { handleDeleteSession(s.session_id); setDeletingId(null); }}>确认删除</button>
                  </div>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </aside>
  );
}
