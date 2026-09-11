import { useEffect, useMemo, useState } from "react";
import { useCopilotChat } from "@/hooks/useCopilotChat";
import type { CopilotSession } from "@/api/client";
import { ResizeHandle } from "@/components/ui/ResizeHandle";
import { displaySessionTitle } from "@/lib/sessionTitle";

/** 三栏布局左栏：品牌 + 会话列表 + 底部工作区/设置（Cursor 式沉底）。 */

/** 会话活跃时间:与后端排序键一致(last_message_at ?? created_at),
 * 分组与显示若用 created_at 会和排序两把尺子,产出重复组头 */
function activityTime(s: CopilotSession): string {
  return s.last_message_at ?? s.created_at;
}

function groupLabel(dateStr: string): "今天" | "本周" | "更早" {
  const d = new Date(dateStr);
  const now = new Date();
  if (d.toDateString() === now.toDateString()) return "今天";
  if (now.getTime() - d.getTime() < 7 * 86400000) return "本周";
  return "更早";
}

function sessTime(s: CopilotSession): string {
  const d = new Date(activityTime(s));
  const now = new Date();
  return d.toDateString() === now.toDateString()
    ? `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`
    : `${String(d.getMonth() + 1).padStart(2, "0")}/${String(d.getDate()).padStart(2, "0")}`;
}

export function LeftSidebar({ onOpenSettings, onOpenWorkspace }: {
  onOpenSettings: () => void;
  onOpenWorkspace: () => void;
}) {
  const {
    sessions, currentSession, sessionActivity,
    switchSession, handleNewSession, handleRenameSession, handleDeleteSession,
  } = useCopilotChat();

  const [workspaceName, setWorkspaceName] = useState("工作区");
  useEffect(() => {
    let alive = true;
    const refresh = () => {
      import("@/api/client").then(({ apiGet }) =>
        apiGet<{ name: string }>("/api/workspace")
          .then((w) => { if (alive && w.name) setWorkspaceName(w.name); })
          .catch(() => { /* ignore */ }),
      );
    };
    refresh();
    window.addEventListener("workspace-changed", refresh);
    return () => { alive = false; window.removeEventListener("workspace-changed", refresh); };
  }, []);

  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = q ? sessions.filter((s) => s.title.toLowerCase().includes(q)) : sessions;
    const out: { label: string; items: CopilotSession[] }[] = [];
    for (const s of filtered) {
      const label = groupLabel(activityTime(s));
      const g = out[out.length - 1];
      if (g && g.label === label) g.items.push(s);
      else out.push({ label, items: [s] });
    }
    return out;
  }, [sessions, query]);

  return (
    <aside className="left-sidebar">
      <ResizeHandle cssVar="--left-sidebar-w" storageKey="left-sidebar-w" min={200} max={480} edge="right" />
      <div className="brand" data-tauri-drag-region="">
        <div className="brand-logo" aria-hidden>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
            <path d="M4 19V5M9 19v-6M14 19V9M19 19v-9" />
          </svg>
        </div>
        <div>
          <div className="brand-name">Stock Agent</div>
          <div className="brand-sub">local · 8686</div>
        </div>
      </div>

      <div className="left-actions">
        <button className="new-chat" onClick={handleNewSession}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4"><path d="M12 5v14M5 12h14"/></svg>
          新建对话
        </button>
        <button
          className={`side-icon-btn${searchOpen ? " on" : ""}`}
          title="搜索会话"
          onClick={() => { setSearchOpen((v) => !v); setQuery(""); }}
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>
        </button>
      </div>
      {searchOpen && (
        <div className="sess-search">
          <input
            autoFocus
            placeholder="搜索会话标题…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Escape") { setSearchOpen(false); setQuery(""); } }}
          />
        </div>
      )}

      <nav className="sessions">
        {groups.length === 0 && (
          <div className="sess-empty">
            <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
            </svg>
            <div>{query ? "没有匹配的会话" : "暂无对话"}</div>
            {!query && <div className="sess-empty-hint">点上方「新建对话」开始</div>}
          </div>
        )}
        {groups.map((g) => (
          <div key={g.label + g.items[0]?.session_id}>
            <div className="sess-group">{g.label}</div>
            {g.items.map((s) => {
              const activity = sessionActivity[s.session_id];
              const meta = activity?.summary
                ?? ((s.message_count ?? 0) > 0 ? `${s.message_count} 条消息` : "未开始");
              const liveKind = activity?.kind;
              return (
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
                    className={[
                      "sess",
                      s.session_id === currentSession?.session_id ? "active" : "",
                      liveKind ? `live live-${liveKind}` : "",
                    ].filter(Boolean).join(" ")}
                    onClick={() => switchSession(s.session_id)}
                  >
                    {/* 标题行右侧挂 mono 时间（TeamClaw 卡片解剖）,hover 时让位给操作按钮 */}
                    <div className="sess-head">
                      <div className="sess-title">{displaySessionTitle(s.title)}</div>
                      <span className="sess-time">{sessTime(s)}</span>
                    </div>
                    <div className="sess-meta">
                      {liveKind && (
                        <span
                          className={`sess-live-dot${liveKind === "clarification" ? " wait" : ""}${liveKind === "error" ? " err" : ""}`}
                          aria-hidden
                        />
                      )}
                      <span className="sess-meta-text">{meta}</span>
                    </div>
                    <div className="sess-actions">
                      <button
                        className="session-action-btn" title="重命名"
                        onClick={(e) => { e.stopPropagation(); setRenamingId(s.session_id); setRenameValue(s.title); }}
                      >✎</button>
                      <button
                        className="session-action-btn danger" title="删除"
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
              );
            })}
          </div>
        ))}
      </nav>

      <div className="left-foot">
        <button className="left-foot-user" onClick={onOpenWorkspace} title={`工作区：${workspaceName}`} type="button">
          <span className="left-foot-avatar" aria-hidden>{workspaceName.charAt(0).toUpperCase()}</span>
          <span className="left-foot-name">{workspaceName}</span>
        </button>
        <button className="left-foot-icon" onClick={onOpenSettings} title="系统设置" type="button">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
            <circle cx="12" cy="12" r="3"/>
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l-.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
          </svg>
        </button>
      </div>
    </aside>
  );
}
