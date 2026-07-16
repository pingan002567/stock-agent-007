import { useEffect, useMemo, useState } from "react";
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
      <div className="brand-avatar">Z</div>
    </div>
  );
}

/** 三栏布局左栏（doc/design/three-column-mockup.html）：
 * 品牌区 + 新建/搜索 + 按时间分组的会话列表 + 系统设置沉底。
 * 会话即一级导航；业务页面入口在右侧 FunctionDock。 */

function groupLabel(dateStr: string): "今天" | "本周" | "更早" {
  const d = new Date(dateStr);
  const now = new Date();
  if (d.toDateString() === now.toDateString()) return "今天";
  if (now.getTime() - d.getTime() < 7 * 86400000) return "本周";
  return "更早";
}

function sessTime(s: CopilotSession): string {
  const d = new Date(s.created_at);
  const now = new Date();
  return d.toDateString() === now.toDateString()
    ? `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`
    : `${String(d.getMonth() + 1).padStart(2, "0")}/${String(d.getDate()).padStart(2, "0")}`;
}

export function LeftSidebar({ onOpenSettings }: { onOpenSettings: () => void }) {
  const {
    sessions, currentSession,
    switchSession, handleNewSession, handleRenameSession, handleDeleteSession,
  } = useCopilotChat();

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
      const label = groupLabel(s.created_at);
      const g = out[out.length - 1];
      if (g && g.label === label) g.items.push(s);
      else out.push({ label, items: [s] });
    }
    return out;
  }, [sessions, query]);

  return (
    <aside className="left-sidebar">
      <div className="brand">
        {/* 与桌面应用图标同款「辉光上行」徽标 */}
        <div className="brand-logo" title="Stock Agent">
          <svg width="22" height="22" viewBox="0 0 100 100">
            <defs>
              <linearGradient id="brand-line" x1="0" y1="1" x2="1" y2="0">
                <stop offset="0" stopColor="#3a6aec"/>
                <stop offset="1" stopColor="#89a8ff"/>
              </linearGradient>
            </defs>
            <g opacity="0.62">
              <rect x="26" y="60" width="9" height="18" rx="2.5" fill="#4aa07a"/>
              <rect x="41" y="65" width="9" height="13" rx="2.5" fill="#cc5c5c"/>
              <rect x="56" y="55" width="9" height="23" rx="2.5" fill="#4aa07a"/>
            </g>
            <polyline points="18,72 42,55 53,61 74,32" fill="none" stroke="url(#brand-line)"
              strokeWidth="9" strokeLinecap="round" strokeLinejoin="round"/>
            <circle cx="74" cy="32" r="8.5" fill="#89a8ff"/>
            <circle cx="74" cy="32" r="4.6" fill="#f0f6ff"/>
          </svg>
        </div>
        <div>
          <div className="brand-name">Stock Agent</div>
          <div className="brand-sub">local · {window.location.port || "80"}</div>
        </div>
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
                    <div className="sess-meta">{s.message_count ?? 0} 条消息</div>
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

      <div className="left-foot">
        <button className="foot-item" onClick={onOpenSettings}>
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
          系统设置
        </button>
      </div>
    </aside>
  );
}
