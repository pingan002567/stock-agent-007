/* eslint-disable react-refresh/only-export-components */
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

/** 右栏详情当前展示的工具卡内容（doc/DESKTOP_APP_PLAN.md §3.4 迁移第 2 步）。 */
export interface ToolDetail {
  id: string;
  name: string;
  status: "done" | "failed" | "running";
  resultText?: string;
}

interface ChatDetailValue {
  detail: ToolDetail | null;
  /** 折叠时 detail 保留（面板收起不卸载，重新展开内容还在） */
  open: boolean;
  openDetail: (d: ToolDetail) => void;
  closeDetail: () => void;
}

const ChatDetailContext = createContext<ChatDetailValue | null>(null);

export function ChatDetailProvider({ children }: { children: ReactNode }) {
  const [detail, setDetail] = useState<ToolDetail | null>(null);
  const [open, setOpen] = useState(false);

  const openDetail = useCallback((d: ToolDetail) => {
    setDetail(d);
    setOpen(true);
  }, []);
  const closeDetail = useCallback(() => setOpen(false), []);

  const value = useMemo(
    () => ({ detail, open, openDetail, closeDetail }),
    [detail, open, openDetail, closeDetail],
  );
  return <ChatDetailContext.Provider value={value}>{children}</ChatDetailContext.Provider>;
}

export function useChatDetail(): ChatDetailValue {
  const ctx = useContext(ChatDetailContext);
  if (!ctx) throw new Error("useChatDetail must be used within ChatDetailProvider");
  return ctx;
}
