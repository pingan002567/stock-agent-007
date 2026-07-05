import { useEffect, useState } from "react";
import { useAppState } from "@/hooks/useAppState";

const WEEKDAYS = ["日", "一", "二", "三", "四", "五", "六"];

function formatClock(d: Date): { date: string; time: string } {
  const pad = (n: number) => String(n).padStart(2, "0");
  return {
    date: `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} 周${WEEKDAYS[d.getDay()]}`,
    time: `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`,
  };
}

function TopbarClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);
  const { date, time } = formatClock(now);
  return (
    <div className="topbar-clock" title="本地时间">
      <span className="topbar-clock-date">{date}</span>
      <span className="topbar-clock-time">{time}</span>
    </div>
  );
}

export function PageContainer({ children }: { children: React.ReactNode }) {
  const { currentScreenLabel } = useAppState();
  return (
    <>
      <header className="topbar">
        <div className="topbar-left">
          <h1 className="topbar-title">AI Stock Workbench</h1>
          <div className="topbar-search">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="11" cy="11" r="8"/>
              <path d="M21 21l-4.35-4.35"/>
            </svg>
            <input type="text" placeholder="搜索股票代码、名称或情报..." />
          </div>
        </div>
        <div className="topbar-right">
          <TopbarClock />
          <div className="topbar-status">
            <span className="topbar-status-dot"></span>
            <span>AI 就绪</span>
          </div>
          <div className="topbar-user">Z</div>
        </div>
      </header>
      <section className="content">
        {children}
      </section>
    </>
  );
}
