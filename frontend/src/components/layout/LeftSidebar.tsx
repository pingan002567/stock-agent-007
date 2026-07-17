import { useEffect, useMemo, useState } from "react";
import { actorColor } from "@/lib/actorColor";
import { useCopilotChat } from "@/hooks/useCopilotChat";
import type { CopilotSession } from "@/api/client";

const WEEKDAYS = ["日", "一", "二", "三", "四", "五", "六"];

/** 品牌区状态簇：时钟 + AI 状态 + 头像（原页面 topbar 右侧集群上移至此） */
function BrandStatus() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);
  const pad = (n: number) => String(n).padStart(2, "0");
  const date = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} 周${WEEKDAYS[now.getDay()]}`;
  const time = `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
  return (
    <div className="brand-status">
      <div className="brand-status-col" title={date}>
        <span className="brand-clock">{time}</span>
        <span className="brand-ai"><span className="dot-ok"/>AI 就绪</span>
      </div>
      <div className="brand-avatar" style={{ background: actorColor("local-user"), color: "#fff" }}>Z</div>
    </div>
  );
}

/** 三栏布局左栏（doc/design/three-column-mockup.html）：
 * 品牌区 + 新建/搜索 + 按时间分组的会话列表 + 系统设置沉底。
 * 会话即一级导航；业务页面入口在右侧 FunctionDock。 */

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
    sessions, currentSession,
    switchSession, handleNewSession, handleRenameSession, handleDeleteSession,
  } = useCopilotChat();

  // 当前工作区名（vault 切换器按钮文本）
  const [workspaceName, setWorkspaceName] = useState("工作区");
  useEffect(() => {
    let alive = true;
    import("@/api/client").then(({ apiGet }) =>
      apiGet<{ name: string }>("/api/workspace")
        .then((w) => { if (alive && w.name) setWorkspaceName(w.name); })
        .catch(() => { /* 旧后端无此接口时保持默认 */ })
    );
    return () => { alive = false; };
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
      {/* 顶行只留状态簇（时钟/AI 状态/头像）;品牌标识随统一顶栏化简去除 */}
      <div className="brand" data-tauri-drag-region="">
        <BrandStatus />
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
            {g.items.map((s) => (
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
                    className={`sess${s.session_id === currentSession?.session_id ? " active" : ""}`}
                    onClick={() => switchSession(s.session_id)}
                  >
                    {/* 标题行右侧挂 mono 时间（TeamClaw 卡片解剖）,hover 时让位给操作按钮 */}
                    <div className="sess-head">
                      <div className="sess-title">{s.title}</div>
                      <span className="sess-time">{sessTime(s)}</span>
                    </div>
                    <div className="sess-meta">{(s.message_count ?? 0) > 0 ? `${s.message_count} 条消息` : "未开始"}</div>
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
            ))}
          </div>
        ))}
      </nav>

      {/* 底部并排：系统设置 │ 工作区切换（按钮文本 = 当前工作区名） */}
      <div className="left-foot">
        <button className="foot-item" onClick={onOpenSettings}>
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
          系统设置
        </button>
        <button className="foot-item" onClick={onOpenWorkspace} title={`工作区：${workspaceName}`}>
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
          <span className="foot-item-text">{workspaceName}</span>
        </button>
      </div>
    </aside>
  );
}
