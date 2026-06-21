import { useState, useEffect, useCallback } from "react";
import { PageContainer } from "@/components/layout/PageContainer";
import { RefreshButton } from "@/components/ui/RefreshButton";
import { apiGet, apiPost, apiDelete } from "@/api/client";

interface Match {
  match_id: string;
  home_team_id: string;
  home_team_name: string;
  home_flag: string;
  away_team_id: string;
  away_team_name: string;
  away_flag: string;
  match_time: string;
  venue: string;
  stage: string;
  group?: string;
  status: string;
}

interface BetRecord {
  bet_id: string;
  match_id: string;
  match_name: string;
  bet_type: string;
  odds: number;
  stake: number;
  probability: number;
  expected_value: number;
  status: "pending" | "won" | "lost";
  profit?: number;
  created_at: string;
}

interface AnalysisResult {
  match_id: string;
  match_info: Match;
  team_comparison: {
    home: { name: string; fifa_ranking: number; elo_rating: number };
    away: { name: string; fifa_ranking: number; elo_rating: number };
  };
  analysis: {
    home_win_prob?: number;
    draw_prob?: number;
    away_win_prob?: number;
    recommended_bet?: string;
    expected_value?: number;
    kelly_fraction?: number;
    confidence?: string;
    message?: string;
  };
  odds_summary?: {
    home?: number;
    draw?: number;
    away?: number;
  };
}

const tabs = [
  { id: "schedule", label: "赛程表", icon: "📅" },
  { id: "odds", label: "赔率分析", icon: "📊" },
  { id: "value", label: "价值投注", icon: "💰" },
  { id: "bets", label: "投注记录", icon: "📝" },
];

export default function WorldCup() {
  const [activeTab, setActiveTab] = useState("schedule");
  const [matches, setMatches] = useState<Match[]>([]);
  const [selectedMatch, setSelectedMatch] = useState<Match | null>(null);
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);
  const [bets, setBets] = useState<BetRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAddBet, setShowAddBet] = useState(false);
  const [newBet, setNewBet] = useState({
    matchId: "",
    betType: "home" as "home" | "draw" | "away",
    odds: 1.5,
    stake: 1000,
    probability: 60,
  });
  const [newOdds, setNewOdds] = useState({
    matchId: "",
    homeOdds: 1.5,
    drawOdds: 4.0,
    awayOdds: 6.0,
  });

  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const today = new Date();
  const [currentMonth, setCurrentMonth] = useState(today.getMonth());
  const [currentYear, setCurrentYear] = useState(today.getFullYear());

  // 按日期分组比赛
  const matchesByDate = matches.reduce<Record<string, Match[]>>((acc, match) => {
    const date = match.match_time?.split(" ")[0] || "";
    const key = date && date !== "null" && date !== "undefined" ? date : "未知日期";
    if (!acc[key]) acc[key] = [];
    acc[key].push(match);
    return acc;
  }, {});

  // 获取所有日期并排序
  const uniqueDates = Object.keys(matchesByDate).sort();

  // 根据选中日期筛选
  const filteredDates = selectedDate ? [selectedDate] : uniqueDates;

  // 计算日历天数
  const calendarDays = (() => {
    const firstDay = new Date(currentYear, currentMonth, 1).getDay();
    const daysInMonth = new Date(currentYear, currentMonth + 1, 0).getDate();
    const days: (number | null)[] = [];
    
    // 填充月初空白天数
    for (let i = 0; i < firstDay; i++) {
      days.push(null);
    }
    
    // 填充月份天数
    for (let i = 1; i <= daysInMonth; i++) {
      days.push(i);
    }
    
    return days;
  })();

  // 格式化日期显示
  const formatDateLabel = (date: string) => {
    if (!date || date === "未知日期") return "未知日期";
    
    // 解析 MM/DD/YYYY 格式
    const parts = date.split("/");
    if (parts.length === 3) {
      const [month, day, year] = parts;
      const d = new Date(parseInt(year), parseInt(month) - 1, parseInt(day));
      if (isNaN(d.getTime())) return date;
      
      const today = new Date();
      const tomorrow = new Date(today);
      tomorrow.setDate(tomorrow.getDate() + 1);
      
      if (d.toDateString() === today.toDateString()) return "今日赛程";
      if (d.toDateString() === tomorrow.toDateString()) return "明日赛程";
      
      const weekdays = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];
      return `${date} ${weekdays[d.getDay()]}`;
    }
    
    // 尝试其他格式
    const d = new Date(date);
    if (isNaN(d.getTime())) return date || "未知日期";
    
    const today = new Date();
    const tomorrow = new Date(today);
    tomorrow.setDate(tomorrow.getDate() + 1);
    
    if (d.toDateString() === today.toDateString()) return "今日赛程";
    if (d.toDateString() === tomorrow.toDateString()) return "明日赛程";
    
    const weekdays = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];
    return `${date} ${weekdays[d.getDay()]}`;
  };

  const loadMatches = useCallback(async () => {
    try {
      setLoading(true);
      const data = await apiGet<{ items: Match[] }>("/api/worldcup/matches");
      setMatches(data.items || []);
    } catch (err) {
      console.error("Failed to load matches:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadBets = useCallback(async () => {
    try {
      const data = await apiGet<{ items: BetRecord[] }>("/api/worldcup/bets");
      setBets(data.items || []);
    } catch (err) {
      console.error("Failed to load bets:", err);
    }
  }, []);

  const loadAnalysis = useCallback(async (matchId: string) => {
    try {
      const data = await apiGet<AnalysisResult>(`/api/worldcup/matches/${matchId}/analysis`);
      setAnalysis(data);
    } catch (err) {
      console.error("Failed to load analysis:", err);
    }
  }, []);

  useEffect(() => {
    void loadMatches();
    void loadBets();
  }, [loadMatches, loadBets]);

  const handleSelectMatch = (match: Match) => {
    setSelectedMatch(match);
    void loadAnalysis(match.match_id);
    // 初始化赔率输入框
    setNewOdds({
      matchId: match.match_id,
      homeOdds: 1.5,
      drawOdds: 4.0,
      awayOdds: 6.0,
    });
  };

  const handleAddOdds = async () => {
    if (!selectedMatch) return;
    try {
      await apiPost(`/api/worldcup/matches/${selectedMatch.match_id}/odds`, {
        home_odds: newOdds.homeOdds,
        draw_odds: newOdds.drawOdds,
        away_odds: newOdds.awayOdds,
      });
      // 保存后自动加载分析结果
      void loadAnalysis(selectedMatch.match_id);
    } catch (err) {
      console.error("Failed to add odds:", err);
    }
  };

  const handleAddBet = async () => {
    try {
      await apiPost("/api/worldcup/bets", {
        match_id: newBet.matchId,
        bet_type: newBet.betType,
        odds: newBet.odds,
        stake: newBet.stake,
        probability: newBet.probability,
      });
      setShowAddBet(false);
      void loadBets();
    } catch (err) {
      console.error("Failed to add bet:", err);
    }
  };

  const handleDeleteBet = async (betId: string) => {
    try {
      await apiDelete(`/api/worldcup/bets/${betId}`);
      void loadBets();
    } catch (err) {
      console.error("Failed to delete bet:", err);
    }
  };

  const handleUpdateBetStatus = async (betId: string, status: "won" | "lost", profit: number) => {
    try {
      await apiPost(`/api/worldcup/bets/${betId}`, { status, profit });
      void loadBets();
    } catch (err) {
      console.error("Failed to update bet:", err);
    }
  };

  // 计算投注统计
  const totalBets = bets.length;
  const wonBets = bets.filter(b => b.status === "won").length;
  const lostBets = bets.filter(b => b.status === "lost").length;
  const pendingBets = bets.filter(b => b.status === "pending").length;
  const totalProfit = bets.reduce((sum, b) => sum + (b.profit || 0), 0);
  const totalStake = bets.reduce((sum, b) => sum + b.stake, 0);
  const roi = totalStake > 0 ? (totalProfit / totalStake * 100).toFixed(1) : "0.0";

  return (
    <PageContainer>
      <div className="page-stack fade-in">
        {/* Hero 区域 */}
        <div className="market-hero">
          <div className="market-hero-header">
            <div className="market-title">
              <h1>世界杯预测</h1>
              <p>基于赔率分析的智能预测系统，发现价值投注机会。</p>
            </div>
            <div className="hero-actions">
              <RefreshButton refreshing={loading} onClick={() => void loadMatches()} />
            </div>
          </div>
          <div className="market-stats">
            <div className="market-stat">
              <span className="market-stat-label">今日比赛</span>
              <span className="market-stat-value">{matches.length}</span>
              <span className="market-stat-change neutral">场</span>
            </div>
            <div className="market-stat">
              <span className="market-stat-label">累计收益</span>
              <span className={`market-stat-value ${totalProfit >= 0 ? "up" : "down"}`}>
                {totalProfit >= 0 ? "+" : ""}{totalProfit.toLocaleString()}
              </span>
              <span className={`market-stat-change ${totalProfit >= 0 ? "up" : "down"}`}>
                ROI {roi}%
              </span>
            </div>
            <div className="market-stat">
              <span className="market-stat-label">投注记录</span>
              <span className="market-stat-value">{totalBets}</span>
              <span className="market-stat-change neutral">
                {wonBets}胜 {lostBets}负 {pendingBets}待
              </span>
            </div>
          </div>
        </div>

        {/* KPI 卡片 */}
        <div className="kpi-grid">
          <div className="kpi-card">
            <div className="kpi-header">
              <span className="kpi-label">累计收益</span>
              <div className="kpi-icon green">💰</div>
            </div>
            <div className="kpi-value" style={{ color: totalProfit >= 0 ? "var(--green)" : "var(--red)" }}>
              {totalProfit >= 0 ? "+" : ""}{totalProfit.toLocaleString()}
            </div>
            <div className="kpi-change" style={{ color: totalProfit >= 0 ? "var(--green)" : "var(--red)" }}>
              ROI {roi}%
            </div>
          </div>
          <div className="kpi-card">
            <div className="kpi-header">
              <span className="kpi-label">胜率</span>
              <div className="kpi-icon amber">📊</div>
            </div>
            <div className="kpi-value">
              {totalBets > 0 ? ((wonBets / (wonBets + lostBets)) * 100).toFixed(0) : 0}%
            </div>
            <div className="kpi-change neutral">{wonBets}胜 / {lostBets}负</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-header">
              <span className="kpi-label">比赛场次</span>
              <div className="kpi-icon blue">⚽</div>
            </div>
            <div className="kpi-value">{matches.length}</div>
            <div className="kpi-change neutral">场</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-header">
              <span className="kpi-label">待结算</span>
              <div className="kpi-icon" style={{ background: "rgba(139, 92, 246, 0.12)", color: "#8b5cf6" }}>⏳</div>
            </div>
            <div className="kpi-value">{pendingBets}</div>
            <div className="kpi-change neutral">笔投注</div>
          </div>
        </div>

        {/* 标签页导航 */}
        <div style={{ display: "flex", gap: 4, padding: 4, background: "var(--bg-secondary)", borderRadius: 12, border: "1px solid var(--border)" }}>
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              style={{
                flex: 1,
                padding: 10,
                background: activeTab === tab.id ? "var(--accent)" : "transparent",
                color: activeTab === tab.id ? "white" : "var(--muted)",
                border: "none",
                borderRadius: 8,
                fontSize: 13,
                fontWeight: 600,
                cursor: "pointer",
                transition: "all 0.2s ease",
              }}
            >
              {tab.icon} {tab.label}
            </button>
          ))}
        </div>

        {/* 赛程表 */}
        {activeTab === "schedule" && (
          <div>
            {/* 日历筛选器 */}
            <div className="panel" style={{ marginBottom: 20 }}>
              <div className="panel-header">
                <div className="panel-title">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>
                    <line x1="16" y1="2" x2="16" y2="6"/>
                    <line x1="8" y1="2" x2="8" y2="6"/>
                    <line x1="3" y1="10" x2="21" y2="10"/>
                  </svg>
                  赛程日历
                </div>
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <button
                    className="small"
                    onClick={() => {
                      const d = new Date(currentYear, currentMonth - 1, 1);
                      setCurrentMonth(d.getMonth());
                      setCurrentYear(d.getFullYear());
                    }}
                    type="button"
                  >
                    ←
                  </button>
                  <span style={{ fontWeight: 600, minWidth: 100, textAlign: "center" }}>
                    {currentYear}年{currentMonth + 1}月
                  </span>
                  <button
                    className="small"
                    onClick={() => {
                      const d = new Date(currentYear, currentMonth + 1, 1);
                      setCurrentMonth(d.getMonth());
                      setCurrentYear(d.getFullYear());
                    }}
                    type="button"
                  >
                    →
                  </button>
                  <button
                    className="small"
                    onClick={() => setSelectedDate(null)}
                    type="button"
                    style={!selectedDate ? { background: "var(--blue-soft)", color: "var(--blue)" } : {}}
                  >
                    全部
                  </button>
                </div>
              </div>
              <div className="panel-body">
                {/* 星期头部 */}
                <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)", gap: 4, marginBottom: 8 }}>
                  {["日", "一", "二", "三", "四", "五", "六"].map(day => (
                    <div key={day} style={{ textAlign: "center", fontSize: 12, fontWeight: 600, color: "var(--muted)", padding: "8px 0" }}>
                      {day}
                    </div>
                  ))}
                </div>
                {/* 日历网格 */}
                <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)", gap: 4 }}>
                  {calendarDays.map((day, index) => {
                    if (!day) {
                      return <div key={`empty-${index}`} style={{ padding: 8 }} />;
                    }
                    const dateStr = `${String(currentMonth + 1).padStart(2, "0")}/${String(day).padStart(2, "0")}/${currentYear}`;
                    const matchCount = matchesByDate[dateStr]?.length || 0;
                    const isSelected = selectedDate === dateStr;
                    const isToday = new Date().toDateString() === new Date(currentYear, currentMonth, day).toDateString();
                    const hasMatches = matchCount > 0;
                    
                    return (
                      <button
                        key={dateStr}
                        onClick={() => setSelectedDate(isSelected ? null : dateStr)}
                        style={{
                          padding: 8,
                          background: isToday ? "var(--green-soft)" : "transparent",
                          color: isToday ? "var(--green)" : "var(--ink)",
                          border: isSelected ? "2px solid var(--blue)" : isToday ? "2px solid var(--green)" : hasMatches ? "1px solid var(--blue)" : "1px solid var(--border)",
                          borderRadius: 8,
                          cursor: "pointer",
                          fontSize: 13,
                          fontWeight: isToday || hasMatches ? 700 : 400,
                          position: "relative",
                          minHeight: 48,
                          display: "flex",
                          flexDirection: "column",
                          alignItems: "center",
                          justifyContent: "center",
                          gap: 2,
                          transition: "all 0.2s ease",
                          boxShadow: isToday ? "0 0 8px rgba(34, 197, 94, 0.3)" : isSelected ? "0 0 8px rgba(59, 130, 246, 0.3)" : "none",
                        }}
                      >
                        {isToday && (
                          <span style={{
                            position: "absolute",
                            top: 2,
                            right: 4,
                            fontSize: 8,
                            background: "var(--green)",
                            color: "white",
                            padding: "1px 4px",
                            borderRadius: 4,
                            fontWeight: 700,
                          }}>
                            今天
                          </span>
                        )}
                        <span>{day}</span>
                        {hasMatches && (
                          <span style={{
                            fontSize: 10,
                            color: isToday ? "var(--green)" : "var(--blue)",
                            fontWeight: 600,
                          }}>
                            {matchCount}场
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>

            {/* 按日期分组的比赛列表 */}
            {loading ? (
              <div className="panel">
                <div className="panel-body">
                  <div className="muted">加载中...</div>
                </div>
              </div>
            ) : filteredDates.length === 0 ? (
              <div className="panel">
                <div className="panel-body">
                  <div className="muted">暂无比赛</div>
                </div>
              </div>
            ) : (
              filteredDates.map(date => (
                <div key={date} className="panel" style={{ marginBottom: 20 }}>
                  <div className="panel-header">
                    <div className="panel-title">
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>
                        <line x1="16" y1="2" x2="16" y2="6"/>
                        <line x1="8" y1="2" x2="8" y2="6"/>
                        <line x1="3" y1="10" x2="21" y2="10"/>
                      </svg>
                      {formatDateLabel(date)}
                      <span className="panel-badge">{matchesByDate[date]?.length || 0} 场</span>
                    </div>
                  </div>
                  <div className="panel-body">
                    {(matchesByDate[date] || []).map((match) => (
                      <div
                        key={match.match_id}
                        className="intel-item"
                        style={selectedMatch?.match_id === match.match_id ? { background: "var(--hover-row)", borderLeft: "3px solid var(--blue)" } : {}}
                        onClick={() => handleSelectMatch(match)}
                      >
                        <div style={{ display: "flex", alignItems: "center", gap: 12, flex: 1 }}>
                          <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 120 }}>
                            <span style={{ fontSize: 20 }}>{match.home_flag}</span>
                            <span style={{ fontWeight: 600, fontSize: 13 }}>{match.home_team_name}</span>
                          </div>
                          <div style={{ textAlign: "center", minWidth: 60 }}>
                            <div style={{ fontSize: 11, color: "var(--muted)" }}>{match.match_time?.split(" ")[1] || ""}</div>
                            <div style={{ fontSize: 10, color: "var(--text-muted)" }}>vs</div>
                          </div>
                          <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 120 }}>
                            <span style={{ fontWeight: 600, fontSize: 13 }}>{match.away_team_name}</span>
                            <span style={{ fontSize: 20 }}>{match.away_flag}</span>
                          </div>
                        </div>
                        <div className="intel-time">{match.stage}</div>
                      </div>
                    ))}
                  </div>
                </div>
              ))
            )}
          </div>
        )}

        {/* 赔率分析 */}
        {activeTab === "odds" && (
          <div>
            {/* 选择比赛 */}
            <div className="panel" style={{ marginBottom: 20 }}>
              <div className="panel-header">
                <div className="panel-title">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <polygon points="22,3 2,3 10,12.46 10,19 14,21 14,12.46"/>
                  </svg>
                  选择比赛
                </div>
              </div>
              <div className="panel-body">
                <select
                  value={selectedMatch?.match_id || ""}
                  onChange={(e) => {
                    const match = matches.find(m => m.match_id === e.target.value);
                    if (match) handleSelectMatch(match);
                  }}
                  style={{ width: "100%", height: 40, padding: "0 12px", background: "var(--bg-tertiary)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--ink)", fontSize: 13 }}
                >
                  <option value="">选择比赛进行分析</option>
                  {matches.map(m => (
                    <option key={m.match_id} value={m.match_id}>{m.home_team_name} vs {m.away_team_name} ({m.match_time})</option>
                  ))}
                </select>
              </div>
            </div>

            {/* 输入赔率 + 分析结果 */}
            {selectedMatch && (
              <div className="two-col">
                <div className="panel">
                  <div className="panel-header">
                    <div className="panel-title">
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>
                      </svg>
                      输入赔率
                    </div>
                    <button 
                      className="small primary" 
                      onClick={() => void handleAddOdds()} 
                      disabled={!selectedMatch}
                      type="button"
                    >
                      保存并分析
                    </button>
                  </div>
                  <div className="panel-body">
                    <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 20 }}>
                      <span style={{ fontSize: 24 }}>{selectedMatch.home_flag}</span>
                      <span style={{ fontSize: 18, fontWeight: 700 }}>{selectedMatch.home_team_name}</span>
                      <span style={{ fontSize: 14, color: "var(--muted)" }}>vs</span>
                      <span style={{ fontSize: 18, fontWeight: 700 }}>{selectedMatch.away_team_name}</span>
                      <span style={{ fontSize: 24 }}>{selectedMatch.away_flag}</span>
                    </div>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
                      <div>
                        <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 4 }}>主胜赔率</div>
                        <input
                          type="number"
                          step="0.01"
                          value={newOdds.homeOdds}
                          onChange={(e) => setNewOdds(prev => ({ ...prev, homeOdds: Number(e.target.value) }))}
                          style={{ width: "100%", height: 40, padding: "0 12px", background: "var(--bg-tertiary)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--ink)", fontSize: 16, fontFamily: "var(--font-mono)", textAlign: "center" }}
                        />
                      </div>
                      <div>
                        <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 4 }}>平局赔率</div>
                        <input
                          type="number"
                          step="0.01"
                          value={newOdds.drawOdds}
                          onChange={(e) => setNewOdds(prev => ({ ...prev, drawOdds: Number(e.target.value) }))}
                          style={{ width: "100%", height: 40, padding: "0 12px", background: "var(--bg-tertiary)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--ink)", fontSize: 16, fontFamily: "var(--font-mono)", textAlign: "center" }}
                        />
                      </div>
                      <div>
                        <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 4 }}>客胜赔率</div>
                        <input
                          type="number"
                          step="0.01"
                          value={newOdds.awayOdds}
                          onChange={(e) => setNewOdds(prev => ({ ...prev, awayOdds: Number(e.target.value) }))}
                          style={{ width: "100%", height: 40, padding: "0 12px", background: "var(--bg-tertiary)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--ink)", fontSize: 16, fontFamily: "var(--font-mono)", textAlign: "center" }}
                        />
                      </div>
                    </div>
                  </div>
                </div>

                <div className="panel">
                  <div className="panel-header">
                    <div className="panel-title">
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>
                      </svg>
                      分析结果
                    </div>
                  </div>
                  <div className="panel-body">
                    {analysis && !analysis.analysis.message ? (
                      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                        <div style={{ padding: 12, background: "var(--bg-tertiary)", borderRadius: 8 }}>
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                            <span style={{ fontSize: 13, fontWeight: 600 }}>推荐投注</span>
                            <span style={{ fontSize: 14, fontWeight: 700, color: analysis.analysis.recommended_bet !== "none" ? "var(--green)" : "var(--muted)" }}>
                              {analysis.analysis.recommended_bet === "home" ? "主胜" : 
                               analysis.analysis.recommended_bet === "draw" ? "平局" : 
                               analysis.analysis.recommended_bet === "away" ? "客胜" : "无"}
                            </span>
                          </div>
                        </div>
                        <div style={{ padding: 12, background: "var(--bg-tertiary)", borderRadius: 8 }}>
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                            <span style={{ fontSize: 13, fontWeight: 600 }}>期望值</span>
                            <span style={{ fontSize: 14, fontWeight: 700, color: (analysis.analysis.expected_value || 0) > 0 ? "var(--green)" : "var(--red)" }}>
                              {analysis.analysis.expected_value ? `+${analysis.analysis.expected_value}%` : "-"}
                            </span>
                          </div>
                        </div>
                        <div style={{ padding: 12, background: "var(--bg-tertiary)", borderRadius: 8 }}>
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                            <span style={{ fontSize: 13, fontWeight: 600 }}>凯利比例</span>
                            <span style={{ fontSize: 14, fontWeight: 700, fontFamily: "var(--font-mono)" }}>
                              {analysis.analysis.kelly_fraction != null ? `${analysis.analysis.kelly_fraction}%` : "-"}
                            </span>
                          </div>
                        </div>
                        <div style={{ padding: 12, background: "var(--bg-tertiary)", borderRadius: 8 }}>
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                            <span style={{ fontSize: 13, fontWeight: 600 }}>置信度</span>
                            <span className={`tag ${analysis.analysis.confidence === "high" ? "green" : analysis.analysis.confidence === "medium" ? "amber" : ""}`}>
                              {analysis.analysis.confidence || "-"}
                            </span>
                          </div>
                        </div>
                      </div>
                    ) : (
                      <div className="muted">输入赔率后点击"保存并分析"</div>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* 概率对比 */}
            {analysis && analysis.odds_summary?.home && (
              <div className="panel" style={{ marginTop: 20 }}>
                <div className="panel-header">
                  <div className="panel-title">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M18 20V10"/>
                      <path d="M12 20V4"/>
                      <path d="M6 20v-6"/>
                    </svg>
                    概率对比
                  </div>
                </div>
                <div className="panel-body">
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
                    <div style={{ padding: 16, background: "var(--bg-tertiary)", borderRadius: 8, textAlign: "center" }}>
                      <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>主胜</div>
                      <div style={{ fontSize: 20, fontWeight: 700, fontFamily: "var(--font-mono)" }}>{analysis.odds_summary.home}</div>
                      <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 4 }}>概率: {analysis.analysis.home_win_prob || "-"}%</div>
                      <div style={{ fontSize: 12, marginTop: 2, color: (analysis.analysis.home_value || 0) > 0 ? "var(--green)" : (analysis.analysis.home_value || 0) < 0 ? "var(--red)" : "var(--muted)" }}>
                        价值: {analysis.analysis.home_value ? `${analysis.analysis.home_value > 0 ? "+" : ""}${analysis.analysis.home_value}%` : "-"}
                      </div>
                    </div>
                    <div style={{ padding: 16, background: "var(--bg-tertiary)", borderRadius: 8, textAlign: "center" }}>
                      <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>平局</div>
                      <div style={{ fontSize: 20, fontWeight: 700, fontFamily: "var(--font-mono)" }}>{analysis.odds_summary.draw}</div>
                      <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 4 }}>概率: {analysis.analysis.draw_prob || "-"}%</div>
                      <div style={{ fontSize: 12, marginTop: 2, color: (analysis.analysis.draw_value || 0) > 0 ? "var(--green)" : (analysis.analysis.draw_value || 0) < 0 ? "var(--red)" : "var(--muted)" }}>
                        价值: {analysis.analysis.draw_value ? `${analysis.analysis.draw_value > 0 ? "+" : ""}${analysis.analysis.draw_value}%` : "-"}
                      </div>
                    </div>
                    <div style={{ padding: 16, background: "var(--bg-tertiary)", borderRadius: 8, textAlign: "center" }}>
                      <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 4 }}>客胜</div>
                      <div style={{ fontSize: 20, fontWeight: 700, fontFamily: "var(--font-mono)" }}>{analysis.odds_summary.away}</div>
                      <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 4 }}>概率: {analysis.analysis.away_win_prob || "-"}%</div>
                      <div style={{ fontSize: 12, marginTop: 2, color: (analysis.analysis.away_value || 0) > 0 ? "var(--green)" : (analysis.analysis.away_value || 0) < 0 ? "var(--red)" : "var(--muted)" }}>
                        价值: {analysis.analysis.away_value ? `${analysis.analysis.away_value > 0 ? "+" : ""}${analysis.analysis.away_value}%` : "-"}
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* 价值投注 */}
        {activeTab === "value" && (
          <div className="panel">
            <div className="panel-header">
              <div className="panel-title">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>
                </svg>
                价值投注机会
              </div>
            </div>
            <div className="panel-body">
              <div className="muted">请先输入赔率数据，系统将自动分析价值投注机会。</div>
            </div>
          </div>
        )}

        {/* 投注记录 */}
        {activeTab === "bets" && (
          <div>
            {/* 新增投注表单 */}
            {showAddBet && (
              <div className="panel" style={{ marginBottom: 20 }}>
                <div className="panel-header">
                  <div className="panel-title">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <line x1="12" y1="5" x2="12" y2="19"/>
                      <line x1="5" y1="12" x2="19" y2="12"/>
                    </svg>
                    新增投注
                  </div>
                  <button className="small" onClick={() => setShowAddBet(false)} type="button">取消</button>
                </div>
                <div className="panel-body">
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 12 }}>
                    <div>
                      <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 4 }}>比赛</div>
                      <select
                        value={newBet.matchId}
                        onChange={(e) => setNewBet(prev => ({ ...prev, matchId: e.target.value }))}
                        style={{ width: "100%", height: 36, padding: "0 12px", background: "var(--bg-tertiary)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--ink)", fontSize: 13 }}
                      >
                        <option value="">选择比赛</option>
                        {matches.map(m => (
                          <option key={m.match_id} value={m.match_id}>{m.home_team_name} vs {m.away_team_name}</option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 4 }}>投注类型</div>
                      <select
                        value={newBet.betType}
                        onChange={(e) => setNewBet(prev => ({ ...prev, betType: e.target.value as "home" | "draw" | "away" }))}
                        style={{ width: "100%", height: 36, padding: "0 12px", background: "var(--bg-tertiary)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--ink)", fontSize: 13 }}
                      >
                        <option value="home">主胜</option>
                        <option value="draw">平局</option>
                        <option value="away">客胜</option>
                      </select>
                    </div>
                    <div>
                      <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 4 }}>赔率</div>
                      <input
                        type="number"
                        step="0.01"
                        value={newBet.odds}
                        onChange={(e) => setNewBet(prev => ({ ...prev, odds: Number(e.target.value) }))}
                        style={{ width: "100%", height: 36, padding: "0 12px", background: "var(--bg-tertiary)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--ink)", fontSize: 13 }}
                      />
                    </div>
                    <div>
                      <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 4 }}>投注金额</div>
                      <input
                        type="number"
                        value={newBet.stake}
                        onChange={(e) => setNewBet(prev => ({ ...prev, stake: Number(e.target.value) }))}
                        style={{ width: "100%", height: 36, padding: "0 12px", background: "var(--bg-tertiary)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--ink)", fontSize: 13 }}
                      />
                    </div>
                    <div>
                      <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 4 }}>真实概率 (%)</div>
                      <input
                        type="number"
                        value={newBet.probability}
                        onChange={(e) => setNewBet(prev => ({ ...prev, probability: Number(e.target.value) }))}
                        style={{ width: "100%", height: 36, padding: "0 12px", background: "var(--bg-tertiary)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--ink)", fontSize: 13 }}
                      />
                    </div>
                    <div style={{ display: "flex", alignItems: "flex-end" }}>
                      <button
                        className="primary"
                        onClick={() => void handleAddBet()}
                        disabled={!newBet.matchId}
                        type="button"
                        style={{ width: "100%", height: 36 }}
                      >
                        添加投注
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* 投注记录列表 */}
            <div className="panel">
              <div className="panel-header">
                <div className="panel-title">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                    <polyline points="14,2 14,8 20,8"/>
                  </svg>
                  投注记录
                  <span className="panel-badge">{bets.length} 笔</span>
                </div>
                <button className="small primary" onClick={() => setShowAddBet(true)} type="button">+ 新增投注</button>
              </div>
              <div className="panel-body" style={{ padding: 0 }}>
                {bets.length === 0 ? (
                  <div className="muted" style={{ padding: 24 }}>暂无投注记录</div>
                ) : (
                  <table>
                    <thead>
                      <tr>
                        <th>比赛</th>
                        <th>投注类型</th>
                        <th>赔率</th>
                        <th>金额</th>
                        <th>概率</th>
                        <th>期望值</th>
                        <th>状态</th>
                        <th>盈亏</th>
                        <th>操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {bets.map((bet) => (
                        <tr key={bet.bet_id}>
                          <td>
                            <div style={{ fontWeight: 600 }}>{bet.match_name}</div>
                            <div style={{ fontSize: 11, color: "var(--muted)" }}>{bet.created_at}</div>
                          </td>
                          <td>
                            <span className="tag">
                              {bet.bet_type === "home" ? "主胜" : bet.bet_type === "draw" ? "平局" : "客胜"}
                            </span>
                          </td>
                          <td className="num">{bet.odds.toFixed(2)}</td>
                          <td className="num">{bet.stake.toLocaleString()}</td>
                          <td className="num">{bet.probability}%</td>
                          <td className="num" style={{ color: "var(--green)" }}>+{bet.expected_value}%</td>
                          <td>
                            <span className={`tag ${bet.status === "won" ? "green" : bet.status === "lost" ? "red" : "amber"}`}>
                              {bet.status === "won" ? "✓ 赢" : bet.status === "lost" ? "✗ 输" : "⏳ 待结算"}
                            </span>
                          </td>
                          <td className="num" style={{ color: (bet.profit || 0) >= 0 ? "var(--green)" : "var(--red)" }}>
                            {bet.profit !== undefined ? (
                              <>
                                {bet.profit >= 0 ? "+" : ""}{bet.profit.toLocaleString()}
                              </>
                            ) : "-"}
                          </td>
                          <td>
                            <div style={{ display: "flex", gap: 4 }}>
                              {bet.status === "pending" && (
                                <>
                                  <button
                                    className="small"
                                    style={{ color: "var(--green)" }}
                                    onClick={() => void handleUpdateBetStatus(bet.bet_id, "won", bet.stake * (bet.odds - 1))}
                                    type="button"
                                  >
                                    赢
                                  </button>
                                  <button
                                    className="small"
                                    style={{ color: "var(--red)" }}
                                    onClick={() => void handleUpdateBetStatus(bet.bet_id, "lost", -bet.stake)}
                                    type="button"
                                  >
                                    输
                                  </button>
                                </>
                              )}
                              <button
                                className="small"
                                style={{ color: "var(--red)" }}
                                onClick={() => void handleDeleteBet(bet.bet_id)}
                                type="button"
                              >
                                删除
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </PageContainer>
  );
}
