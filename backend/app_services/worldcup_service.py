from __future__ import annotations

import httpx
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from backend.persistence.repositories import WorkbenchRepository
from backend.schemas import (
    WorldCupBet,
    WorldCupMatch,
    WorldCupOdds,
    WorldCupPrediction,
    WorldCupTeam,
    model_to_dict,
    now_iso,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# World Cup 2026 API
WORLDCUP_API_BASE = "https://wc2026.moothz.win"

# 国旗 emoji 映射
FLAG_EMOJIS: Dict[str, str] = {
    "QAT": "🇶🇦", "ECU": "🇪🇨", "SEN": "🇸🇳", "NED": "🇳🇱",
    "ENG": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "IRN": "🇮🇷", "USA": "🇺🇸", "WAL": "🏴󠁧󠁢󠁷󠁬󠁳󠁿",
    "ARG": "🇦🇷", "KSA": "🇸🇦", "MEX": "🇲🇽", "POL": "🇵🇱",
    "FRA": "🇫🇷", "AUS": "🇦🇺", "DEN": "🇩🇰", "TUN": "🇹🇳",
    "ESP": "🇪🇸", "CRC": "🇨🇷", "GER": "🇩🇪", "JPN": "🇯🇵",
    "BEL": "🇧🇪", "CAN": "🇨🇦", "MAR": "🇲🇦", "CRO": "🇭🇷",
    "BRA": "🇧🇷", "SRB": "🇷🇸", "SUI": "🇨🇭", "CMR": "🇨🇲",
    "POR": "🇵🇹", "GHA": "🇬🇭", "URU": "🇺🇾", "KOR": "🇰🇷",
}

# ELO 评分（用于分析）
ELO_RATINGS: Dict[str, int] = {
    "BRA": 2150, "ARG": 2200, "FRA": 2180, "ESP": 2050, "GER": 1950,
    "JPN": 1850, "SRB": 1780, "CRC": 1700, "AUS": 1650, "KSA": 1550,
    "ENG": 2100, "IRN": 1750, "USA": 1900, "WAL": 1800, "NED": 2050,
    "SEN": 1800, "ECU": 1700, "QAT": 1600, "MAR": 1850, "CRO": 2000,
    "BEL": 2050, "CAN": 1700, "CMR": 1650, "POL": 1900, "MEX": 1800,
    "KOR": 1800, "URU": 1950, "GHA": 1700, "POR": 2100, "TUN": 1650,
    "DEN": 1950, "SUI": 1900,
}

# FIFA 排名
FIFA_RANKINGS: Dict[str, int] = {
    "BRA": 3, "ARG": 1, "FRA": 2, "ESP": 8, "GER": 16,
    "JPN": 20, "SRB": 25, "CRC": 32, "AUS": 38, "KSA": 50,
    "ENG": 5, "IRN": 22, "USA": 14, "WAL": 19, "NED": 8,
    "SEN": 18, "ECU": 44, "QAT": 50, "MAR": 24, "CRO": 12,
    "BEL": 4, "CAN": 43, "CMR": 43, "POL": 26, "MEX": 13,
    "KOR": 28, "URU": 16, "GHA": 61, "POR": 9, "TUN": 35,
    "DEN": 11, "SUI": 14,
}


class WorldCupService:
    def __init__(self, repo: WorkbenchRepository) -> None:
        self.repo = repo
        self._initialized = False
        self._matches_cache: List[Dict[str, Any]] = []
        self._cache_time: Optional[datetime] = None

    async def _fetch_from_api(self, endpoint: str) -> Dict[str, Any]:
        """从 World Cup 2026 API 获取数据"""
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{WORLDCUP_API_BASE}{endpoint}", timeout=10.0)
            resp.raise_for_status()
            return resp.json()

    def _get_flag(self, team_code: str) -> str:
        """获取球队国旗 emoji"""
        return FLAG_EMOJIS.get(team_code.upper(), "🏳️")

    def _get_elo(self, team_code: str) -> int:
        """获取球队 ELO 评分"""
        return ELO_RATINGS.get(team_code.upper(), 1700)

    def _get_fifa_ranking(self, team_code: str) -> int:
        """获取球队 FIFA 排名"""
        return FIFA_RANKINGS.get(team_code.upper(), 50)

    def _calculate_probabilities(self, home_odds: float, draw_odds: float, away_odds: float) -> Dict[str, float]:
        """计算隐含概率"""
        home_prob = 1 / home_odds
        draw_prob = 1 / draw_odds
        away_prob = 1 / away_odds
        total = home_prob + draw_prob + away_prob
        return {
            "home": round(home_prob / total * 100, 1),
            "draw": round(draw_prob / total * 100, 1),
            "away": round(away_prob / total * 100, 1),
        }

    def _calculate_value(self, true_prob: float, implied_prob: float) -> float:
        """计算价值"""
        return round(true_prob - implied_prob, 1)

    def _transform_match(self, api_match: Dict[str, Any]) -> Dict[str, Any]:
        """将 API 数据转换为内部格式"""
        home_name = api_match.get("home_team_name_en", "")
        away_name = api_match.get("away_team_name_en", "")
        
        # 从名称推断代码
        home_code = self._get_team_code(home_name)
        away_code = self._get_team_code(away_name)
        
        status = "finished" if api_match.get("finished") == "TRUE" else "upcoming"
        
        return {
            "match_id": f"match_{api_match.get('id', '')}",
            "stage": api_match.get("type", "group"),
            "group": api_match.get("group"),
            "home_team_id": home_code,
            "away_team_id": away_code,
            "home_team_name": home_name,
            "away_team_name": away_name,
            "home_flag": self._get_flag(home_code),
            "away_flag": self._get_flag(away_code),
            "match_time": api_match.get("local_date", ""),
            "venue": f"场馆 {api_match.get('stadium_id', '')}",
            "home_score": int(api_match["home_score"]) if api_match.get("home_score") and api_match["home_score"] != "null" else None,
            "away_score": int(api_match["away_score"]) if api_match.get("away_score") and api_match["away_score"] != "null" else None,
            "status": status,
        }

    def _get_team_code(self, name: str) -> str:
        """从球队名称获取代码"""
        name_map = {
            "Mexico": "MEX", "South Africa": "RSA", "South Korea": "KOR",
            "Czech Republic": "CZE", "Germany": "GER", "Japan": "JPN",
            "Spain": "ESP", "Brazil": "BRA", "France": "FRA",
            "Argentina": "ARG", "England": "ENG", "USA": "USA",
            "Portugal": "POR", "Netherlands": "NED", "Belgium": "BEL",
            "Croatia": "CRO", "Morocco": "MAR", "Australia": "AUS",
            "Saudi Arabia": "KSA", "Iran": "IRN", "Senegal": "SEN",
            "Ecuador": "ECU", "Qatar": "QAT", "Canada": "CAN",
            "Cameroon": "CMR", "Poland": "POL", "Tunisia": "TUN",
            "Denmark": "DEN", "Serbia": "SRB", "Switzerland": "SUI",
            "Uruguay": "URU", "Ghana": "GHA", "Wales": "WAL",
        }
        return name_map.get(name, name[:3].upper())

    async def _load_matches_from_api(self) -> List[Dict[str, Any]]:
        """从 API 加载比赛数据"""
        try:
            data = await self._fetch_from_api("/get/games")
            # API 返回 {games: [...]} 格式
            games = data.get("games", data) if isinstance(data, dict) else data
            matches = [self._transform_match(m) for m in games]
            self._matches_cache = matches
            self._cache_time = _utc_now()
            return matches
        except Exception as e:
            print(f"Failed to fetch matches from API: {e}")
            return self._matches_cache

    def get_matches(
        self,
        match_id: Optional[str] = None,
        stage: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取比赛列表"""
        # 检查缓存是否有效（5分钟）
        if self._cache_time and (_utc_now() - self._cache_time).total_seconds() < 300:
            matches = self._matches_cache
        else:
            # 同步获取数据
            import asyncio
            try:
                matches = asyncio.run(self._load_matches_from_api())
            except RuntimeError:
                # 如果已经有事件循环在运行，使用线程池
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, self._load_matches_from_api())
                    matches = future.result(timeout=15)
            except Exception as e:
                print(f"Error loading matches: {e}")
                matches = self._matches_cache
        
        # 筛选
        if match_id:
            matches = [m for m in matches if m["match_id"] == match_id]
        if stage:
            matches = [m for m in matches if m["stage"] == stage]
        if status:
            matches = [m for m in matches if m["status"] == status]
        
        return matches

    def get_odds(self, match_id: str) -> Dict[str, Any]:
        """获取赔率数据（用户手动输入）"""
        odds_data = self.repo.get_config("worldcup_odds", {"items": []})
        match_odds = [o for o in odds_data.get("items", []) if o.get("match_id") == match_id]
        
        if not match_odds:
            return {
                "match_id": match_id,
                "odds": {},
                "implied_probabilities": {},
                "message": "暂无赔率数据，请手动输入",
            }
        
        latest_odds = match_odds[-1]
        home_odds = latest_odds.get("home_win", 0)
        draw_odds = latest_odds.get("draw", 0)
        away_odds = latest_odds.get("away_win", 0)
        
        if home_odds > 0 and draw_odds > 0 and away_odds > 0:
            probs = self._calculate_probabilities(home_odds, draw_odds, away_odds)
        else:
            probs = {"home": 0, "draw": 0, "away": 0}
        
        return {
            "match_id": match_id,
            "odds": {
                "home": home_odds,
                "draw": draw_odds,
                "away": away_odds,
                "bookmaker": latest_odds.get("bookmaker", "手动输入"),
                "updated_at": latest_odds.get("created_at", ""),
            },
            "implied_probabilities": probs,
        }

    def set_odds(self, match_id: str, home_odds: float, draw_odds: float, away_odds: float, bookmaker: str = "手动输入") -> Dict[str, Any]:
        """设置赔率数据（用户手动输入）"""
        odds_data = self.repo.get_config("worldcup_odds", {"items": []})
        items = odds_data.get("items", [])
        
        new_odds = {
            "odds_id": f"odds_{uuid4().hex[:10]}",
            "match_id": match_id,
            "bookmaker": bookmaker,
            "home_win": home_odds,
            "draw": draw_odds,
            "away_win": away_odds,
            "created_at": now_iso(),
        }
        
        items.append(new_odds)
        self.repo.set_config("worldcup_odds", {"items": items})
        
        return new_odds

    def get_analysis(self, match_id: str) -> Dict[str, Any]:
        """获取比赛分析"""
        match = next((m for m in self.get_matches() if m["match_id"] == match_id), None)
        if not match:
            return {"match_id": match_id, "error": "比赛未找到"}
        
        odds_data = self.get_odds(match_id)
        odds = odds_data.get("odds", {})
        
        home_odds = odds.get("home", 0)
        draw_odds = odds.get("draw", 0)
        away_odds = odds.get("away", 0)
        
        home_code = match.get("home_team_id", "")
        away_code = match.get("away_team_id", "")
        
        if home_odds == 0:
            return {
                "match_id": match_id,
                "match_info": match,
                "team_comparison": {
                    "home": {"name": match.get("home_team_name"), "fifa_ranking": self._get_fifa_ranking(home_code), "elo_rating": self._get_elo(home_code)},
                    "away": {"name": match.get("away_team_name"), "fifa_ranking": self._get_fifa_ranking(away_code), "elo_rating": self._get_elo(away_code)},
                },
                "analysis": {
                    "message": "请先输入赔率数据以获取分析",
                },
            }
        
        home_elo = self._get_elo(home_code)
        away_elo = self._get_elo(away_code)
        
        elo_diff = home_elo - away_elo
        home_base_prob = 1 / (1 + math.pow(10, -elo_diff / 400))
        draw_prob = 0.25
        away_base_prob = 1 - home_base_prob - draw_prob
        
        implied = odds_data.get("implied_probabilities", {})
        home_implied = implied.get("home", 33.3)
        draw_implied = implied.get("draw", 33.3)
        away_implied = implied.get("away", 33.3)
        
        home_value = self._calculate_value(home_base_prob * 100, home_implied)
        draw_value = self._calculate_value(draw_prob * 100, draw_implied)
        away_value = self._calculate_value(away_base_prob * 100, away_implied)
        
        # 推荐价值最高的选项
        values = {"home": home_value, "draw": draw_value, "away": away_value}
        recommended = max(values, key=values.get)
        ev = values[recommended]
        
        if ev <= 0:
            recommended = "none"
            ev = 0
        
        if recommended == "home":
            kelly = ((home_odds - 1) * home_base_prob - (1 - home_base_prob)) / (home_odds - 1) * 100
        elif recommended == "draw":
            kelly = ((draw_odds - 1) * draw_prob - (1 - draw_prob)) / (draw_odds - 1) * 100
        elif recommended == "away":
            kelly = ((away_odds - 1) * away_base_prob - (1 - away_base_prob)) / (away_odds - 1) * 100
        else:
            kelly = 0
        
        return {
            "match_id": match_id,
            "match_info": match,
            "team_comparison": {
                "home": {"name": match.get("home_team_name"), "fifa_ranking": self._get_fifa_ranking(home_code), "elo_rating": home_elo},
                "away": {"name": match.get("away_team_name"), "fifa_ranking": self._get_fifa_ranking(away_code), "elo_rating": away_elo},
            },
            "analysis": {
                "home_win_prob": round(home_base_prob * 100, 1),
                "draw_prob": round(draw_prob * 100, 1),
                "away_win_prob": round(away_base_prob * 100, 1),
                "home_value": round(home_value, 1),
                "draw_value": round(draw_value, 1),
                "away_value": round(away_value, 1),
                "recommended_bet": recommended,
                "expected_value": round(ev, 1),
                "kelly_fraction": round(max(0, kelly), 1),
                "confidence": "high" if abs(ev) > 10 else "medium" if abs(ev) > 5 else "low",
            },
            "odds_summary": odds,
        }

    def create_prediction(self, match_id: str, home_score: int, away_score: int, confidence: float = 0.5) -> Dict[str, Any]:
        """创建预测"""
        prediction_id = f"pred_{uuid4().hex[:10]}"
        prediction = WorldCupPrediction(
            prediction_id=prediction_id,
            match_id=match_id,
            predicted_home_score=home_score,
            predicted_away_score=away_score,
            confidence=confidence,
        )
        # TODO: 保存到数据库
        return model_to_dict(prediction)

    def create_bet(self, match_id: str, bet_type: str, odds: float, stake: float, probability: float) -> Dict[str, Any]:
        """创建投注"""
        bet_id = f"bet_{uuid4().hex[:10]}"
        expected_value = (probability / 100 * odds - 1) * 100
        
        match = next((m for m in self.get_matches() if m["match_id"] == match_id), None)
        match_name = f"{match.get('home_team_name', '?')} vs {match.get('away_team_name', '?')}" if match else match_id
        
        bet = WorldCupBet(
            bet_id=bet_id,
            match_id=match_id,
            match_name=match_name,
            bet_type=bet_type,
            odds=odds,
            stake=stake,
            probability=probability,
            expected_value=round(expected_value, 1),
            status="pending",
        )
        # TODO: 保存到数据库
        return model_to_dict(bet)

    def update_bet(self, bet_id: str, status: str, profit: Optional[float] = None) -> Dict[str, Any]:
        """更新投注状态"""
        # TODO: 更新数据库
        return {
            "bet_id": bet_id,
            "status": status,
            "profit": profit,
            "updated_at": now_iso(),
        }

    def delete_bet(self, bet_id: str) -> Dict[str, Any]:
        """删除投注"""
        # TODO: 从数据库删除
        return {
            "bet_id": bet_id,
            "deleted": True,
        }

    def list_bets(self, status: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        """获取投注列表"""
        # TODO: 从数据库获取
        return []
