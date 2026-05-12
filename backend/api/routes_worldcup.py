from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request

from backend.api.deps import get_services
from backend.bootstrap import AppServices

router = APIRouter(prefix="/api/worldcup", tags=["worldcup"])


@router.get("/matches")
def list_matches(
    request: Request,
    match_id: Optional[str] = Query(default=None, description="比赛ID"),
    stage: Optional[str] = Query(default=None, description="比赛阶段筛选"),
    status: Optional[str] = Query(default=None, description="比赛状态筛选"),
    services: AppServices = Depends(get_services),
):
    items = services.worldcup_service.get_matches(
        match_id=match_id,
        stage=stage,
        status=status,
    )
    return {"items": items, "count": len(items)}


@router.get("/matches/{match_id}")
def get_match(
    match_id: str,
    request: Request,
    services: AppServices = Depends(get_services),
):
    items = services.worldcup_service.get_matches(match_id=match_id)
    if not items:
        raise HTTPException(status_code=404, detail="Match not found")
    return items[0]


@router.get("/matches/{match_id}/odds")
def get_match_odds(
    match_id: str,
    request: Request,
    services: AppServices = Depends(get_services),
):
    return services.worldcup_service.get_odds(match_id)


@router.post("/matches/{match_id}/odds")
def set_match_odds(
    match_id: str,
    request: Request,
    payload: dict = Body(...),
    services: AppServices = Depends(get_services),
):
    home_odds = payload.get("home_odds", 0)
    draw_odds = payload.get("draw_odds", 0)
    away_odds = payload.get("away_odds", 0)
    bookmaker = payload.get("bookmaker", "手动输入")
    
    return services.worldcup_service.set_odds(
        match_id=match_id,
        home_odds=home_odds,
        draw_odds=draw_odds,
        away_odds=away_odds,
        bookmaker=bookmaker,
    )


@router.get("/matches/{match_id}/analysis")
def get_match_analysis(
    match_id: str,
    request: Request,
    services: AppServices = Depends(get_services),
):
    return services.worldcup_service.get_analysis(match_id)


@router.post("/predictions")
def create_prediction(
    request: Request,
    payload: dict = Body(...),
    services: AppServices = Depends(get_services),
):
    match_id = payload.get("match_id", "")
    home_score = payload.get("home_score", 0)
    away_score = payload.get("away_score", 0)
    confidence = payload.get("confidence", 0.5)
    
    if not match_id:
        raise HTTPException(status_code=400, detail="match_id is required")
    
    return services.worldcup_service.create_prediction(
        match_id=match_id,
        home_score=home_score,
        away_score=away_score,
        confidence=confidence,
    )


@router.get("/bets")
def list_bets(
    request: Request,
    status: Optional[str] = Query(default=None, description="投注状态筛选"),
    limit: int = Query(default=20, ge=1, le=100),
    services: AppServices = Depends(get_services),
):
    items = services.worldcup_service.list_bets(status=status, limit=limit)
    return {"items": items, "count": len(items)}


@router.post("/bets")
def create_bet(
    request: Request,
    payload: dict = Body(...),
    services: AppServices = Depends(get_services),
):
    match_id = payload.get("match_id", "")
    bet_type = payload.get("bet_type", "home")
    odds = payload.get("odds", 1.0)
    stake = payload.get("stake", 0)
    probability = payload.get("probability", 50)
    
    if not match_id:
        raise HTTPException(status_code=400, detail="match_id is required")
    
    return services.worldcup_service.create_bet(
        match_id=match_id,
        bet_type=bet_type,
        odds=odds,
        stake=stake,
        probability=probability,
    )


@router.put("/bets/{bet_id}")
def update_bet(
    bet_id: str,
    request: Request,
    payload: dict = Body(...),
    services: AppServices = Depends(get_services),
):
    status = payload.get("status", "pending")
    profit = payload.get("profit")
    
    return services.worldcup_service.update_bet(
        bet_id=bet_id,
        status=status,
        profit=profit,
    )


@router.delete("/bets/{bet_id}")
def delete_bet(
    bet_id: str,
    request: Request,
    services: AppServices = Depends(get_services),
):
    return services.worldcup_service.delete_bet(bet_id)
